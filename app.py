"""CampusPulse AI — Flask backend (REST API + serves the HTML/CSS/JS frontend).

Run:   python app.py            → http://127.0.0.1:5000

Auth: email + password accounts (hashed), session cookie (HttpOnly, SameSite=Lax),
      CSRF guard on every state-changing request, login throttling.
Data: each account has its own database + WhatsApp folder (backend/userspace.py).
"""
from __future__ import annotations

import atexit
import json
import os
import secrets
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, Response, abort, jsonify, redirect, request, send_file, send_from_directory, session
from werkzeug.utils import secure_filename

import config
from agent import llm, orchestrator, planner
from agent.change_detector import fmt_dt
from backend import auth, bridge_manager, userspace
from database import repository as repo
from ingestion import live_sync
from ingestion.pdf_parser import digest_pdf
from ingestion.upload import UploadError, decode_upload, guess_group_name, import_chat
from rag.answer import ask, solve_doubt
from rag.citations import label
from utils.calendar_export import build_ics

WEB_DIR = config.BASE_DIR / "web"


def _secret_key() -> str:
    key = os.getenv("FLASK_SECRET_KEY")
    if key:
        return key
    f = config.DATA_DIR / ".secret_key"
    f.parent.mkdir(parents=True, exist_ok=True)
    if not f.exists():
        f.write_text(secrets.token_hex(32))
    return f.read_text().strip()


app = Flask(__name__, static_folder=None)
app.config.update(
    SECRET_KEY=_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "0") == "1",  # set 1 behind HTTPS
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    MAX_CONTENT_LENGTH=int(config.MAX_UPLOAD_MB * 1024 * 1024) + 1024 * 1024,
)
atexit.register(bridge_manager.stop_all)


# ------------------------------------------------------------------ helpers
def ok(data=None, status: int = 200):
    return Response(json.dumps(data if data is not None else {"ok": True}, default=str),
                    status=status, mimetype="application/json")


def err(message: str, status: int = 400):
    return ok({"error": message}, status)


def current_uid():
    return session.get("uid")


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        uid = current_uid()
        if not uid or not auth.get_account(uid):
            session.clear()
            return err("Please log in.", 401)
        with userspace.lock(uid):
            return fn(uid, *a, **kw)
    return wrapper


@app.before_request
def csrf_guard():
    """State-changing API calls must come from our own JS (custom header can't be sent cross-site
    without CORS, which we don't enable)."""
    if request.path.startswith("/api/") and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if request.headers.get("X-Requested-With") != "CampusPulse":
            return err("Missing CSRF header.", 403)


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    return resp


def body() -> dict:
    return request.get_json(silent=True) or {}


def ctx(uid):
    c = userspace.conn(uid)
    return c, userspace.now_for(c)


def rows(rs):
    return [dict(r) for r in rs]


# ------------------------------------------------------------------ pages
@app.get("/")
def index():
    if current_uid() and auth.get_account(current_uid()):
        return redirect("/app")
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/app")
def app_page():
    if not current_uid() or not auth.get_account(current_uid()):
        return redirect("/")
    return send_from_directory(WEB_DIR, "app.html")


@app.get("/css/<path:name>")
def css(name):
    return send_from_directory(WEB_DIR / "css", name)


@app.get("/js/<path:name>")
def js(name):
    return send_from_directory(WEB_DIR / "js", name)


# ------------------------------------------------------------------- auth
@app.post("/api/auth/register")
def register():
    b = body()
    try:
        acct = auth.register(b.get("name", ""), b.get("email", ""), b.get("password", ""))
    except auth.AuthError as e:
        return err(str(e))
    session.clear()
    session.permanent = True
    session["uid"] = acct["id"]
    userspace.conn(acct["id"], acct["name"])
    return ok({"user": acct}, 201)


@app.post("/api/auth/login")
def login():
    b = body()
    try:
        acct = auth.login(b.get("email", ""), b.get("password", ""), request.remote_addr or "")
    except auth.AuthError as e:
        return err(str(e), 401)
    session.clear()  # new session id on login (prevents fixation)
    session.permanent = bool(b.get("remember", True))
    session["uid"] = acct["id"]
    userspace.conn(acct["id"], acct["name"])
    return ok({"user": acct})


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return ok()


@app.get("/api/auth/me")
@login_required
def me(uid):
    c, now = ctx(uid)
    wa = live_sync.status(userspace.live_dir(uid))
    return ok({"user": auth.get_account(uid), "profile": repo.get_profile(c), "now": now,
               "llm": llm.provider() if llm.available() else None,
               "whatsapp": {"state": wa.get("state"), "alive": wa["alive"], "has_avatar": bool(wa.get("avatar_path"))},
               "has_data": bool(repo.list_groups(c))})


@app.post("/api/auth/password")
@login_required
def change_password(uid):
    b = body()
    try:
        auth.change_password(uid, b.get("current", ""), b.get("new", ""))
    except auth.AuthError as e:
        return err(str(e))
    return ok()


@app.delete("/api/auth/account")
@login_required
def delete_account(uid):
    try:
        auth.login(auth.get_account(uid)["email"], body().get("password", ""), request.remote_addr or "")
    except auth.AuthError as e:
        return err(str(e), 401)
    bridge_manager.stop(uid, logout=True, wait_s=3)
    userspace.delete_user_data(uid)
    auth.delete_account(uid)
    session.clear()
    return ok()


# ---------------------------------------------------------------- profile
@app.get("/api/profile")
@login_required
def get_profile(uid):
    c, now = ctx(uid)
    live = userspace.live_dir(uid)
    wa = live_sync.status(live)
    stats = {
        "groups": len(repo.list_groups(c)),
        "messages": c.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
        "tasks_done": c.execute("SELECT COUNT(*) FROM tasks WHERE status='done'").fetchone()[0],
        "tasks_open": c.execute("SELECT COUNT(*) FROM tasks WHERE status='pending'").fetchone()[0],
        "changes": c.execute("SELECT COUNT(*) FROM change_logs WHERE kind='change'").fetchone()[0],
    }
    return ok({"user": auth.get_account(uid), "profile": repo.get_profile(c), "stats": stats,
               "whatsapp": {"state": wa.get("state"), "alive": wa["alive"], "account": wa.get("account"),
                            "has_avatar": bool(wa.get("avatar_path")),
                            "groups_synced": len(live_sync.selected_groups(live))}})


@app.put("/api/profile")
@login_required
def put_profile(uid):
    c, _ = ctx(uid)
    b = body()
    p = repo.get_profile(c)

    def as_list(v):
        return [x.strip() for x in (v if isinstance(v, list) else str(v or "").split(",")) if x.strip()]
    try:
        p.update(
            name=(b.get("name") or p.get("name") or "Student").strip()[:60],
            branch=str(b.get("branch", p.get("branch", "")))[:60],
            year=int(b.get("year") or p.get("year") or 1),
            grad_year=int(b.get("grad_year") or p.get("grad_year") or datetime.now().year),
            interests=as_list(b.get("interests", p.get("interests", []))),
            skills=as_list(b.get("skills", p.get("skills", []))),
            teams=as_list(b.get("teams", p.get("teams", []))),
        )
    except (TypeError, ValueError):
        return err("Year and graduation year must be numbers.")
    if "demo_now" in b:
        p["demo_now"] = b["demo_now"] or None
    repo.save_profile(c, p)
    auth.update_name(uid, p["name"])
    orchestrator.run_pipeline(c, profile=p, now=userspace.now_for(c))
    return ok({"profile": p})


# -------------------------------------------------------------- dashboard
def _card(item):
    item = dict(item)
    item["when"] = item["when"].isoformat() if item.get("when") else None
    item["band"] = planner.priority_band(item["priority"])
    return item


@app.get("/api/dashboard")
@login_required
def dashboard(uid):
    c, now = ctx(uid)
    b = planner.build_brief(c, now)
    total = c.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    noise = c.execute("SELECT COUNT(*) FROM message_analyses WHERE is_noise=1").fetchone()[0]
    return ok({
        "now": now, "user": auth.get_account(uid),
        "metrics": {
            "groups": len(repo.list_groups(c)), "messages": total,
            "attention": len([i for i in b["top"] if i["priority"] >= 55]),
            "noise_pct": round(noise / total * 100) if total else 0,
            "changes": c.execute("SELECT COUNT(*) FROM change_logs WHERE kind='change'").fetchone()[0],
            "open_tasks": c.execute("SELECT COUNT(*) FROM tasks WHERE status='pending'").fetchone()[0],
            "rumors": b["rumors"], "conflicts": b["conflicts"],
        },
        "top": [_card(i) for i in b["top"]],
        "not_for_you": [_card(i) for i in b["not_for_you"]],
    })


@app.get("/api/changes")
@login_required
def changes(uid):
    c, _ = ctx(uid)
    out = []
    for ch in repo.list_changes(c):
        d = dict(ch)
        d["old_values"], d["new_values"] = json.loads(ch["old_values"]), json.loads(ch["new_values"])
        for key, mid in (("old_message", ch["old_message_id"]), ("new_message", ch["source_message_id"])):
            m = repo.get_message(c, mid) if mid else None
            d[key] = ({"group": m["group_name"], "sender": m["sender"], "timestamp": m["timestamp"],
                       "text": m["text"]} if m else None)
        out.append(d)
    return ok(out)


@app.get("/api/rumors")
@login_required
def rumors(uid):
    c, _ = ctx(uid)
    rs = c.execute(
        """SELECT m.id, m.text, m.sender, m.timestamp, g.name AS group_name, a.trust_label, a.trust_score,
                  a.trust_reasons FROM messages m JOIN groups g ON g.id = m.group_id
           JOIN message_analyses a ON a.message_id = m.id
           WHERE a.is_noise = 0 AND (a.trust_reasons LIKE '%Hearsay%' OR a.trust_label = 'contradicted')
           ORDER BY a.trust_score""").fetchall()
    items = []
    for r in rs:
        d = dict(r)
        d["trust_reasons"] = json.loads(r["trust_reasons"] or "[]")
        ref = next((x for x in d["trust_reasons"] if x.startswith(("Contradicted by", "Confirmed by"))), None)
        d["evidence"] = None
        if ref:
            sender, _, group = ref.split(" by ", 1)[1].rpartition(" in ")
            ev = c.execute(
                """SELECT m.text, m.sender, m.timestamp, g.name AS group_name FROM messages m
                   JOIN groups g ON g.id = m.group_id JOIN message_analyses a ON a.message_id = m.id
                   WHERE m.sender = ? AND g.name = ? AND a.trust_label = 'verified'
                   ORDER BY (m.text LIKE '%rumour%' OR m.text LIKE '%as scheduled%' OR m.text LIKE '%no change%') DESC,
                            m.timestamp DESC LIMIT 1""", (sender, group)).fetchone()
            d["evidence"] = dict(ev) if ev else None
        items.append(d)
    doubts = []
    for q in orchestrator.unanswered_questions(c):
        sol = solve_doubt(c, q)
        doubts.append({"question": q["text"], "group": q["group"], "sender": q["sender"],
                       "timestamp": q["timestamp"], "found": sol["found"], "cross_group": sol["cross_group"],
                       "from": sol["from_groups"], "answer": sol["answer"].answer,
                       "sources": [label(x) for x in sol["answer"].citations[:4]]})
    checked = c.execute("SELECT COUNT(*) FROM message_analyses WHERE is_noise=0").fetchone()[0]
    return ok({"rumors": items, "doubts": doubts, "checked": checked})


@app.get("/api/deadlines")
@login_required
def deadlines(uid):
    c, now = ctx(uid)
    evs = []
    for e in repo.list_events(c):
        if not e["current_at"]:
            continue
        when = datetime.fromisoformat(e["current_at"])
        if when < now or e["status"] == "cancelled":
            continue
        srcs = repo.event_sources(c, e["id"])
        d = dict(e)
        d["when_label"] = fmt_dt(when)
        d["original_label"] = fmt_dt(datetime.fromisoformat(e["original_at"])) if e["original_at"] else None
        d["hours_left"] = round((when - now).total_seconds() / 3600, 1)
        d["groups"] = sorted({s["group_name"] for s in srcs})
        d["source_count"] = len(srcs)
        rel = [c.execute("SELECT relevance FROM message_analyses WHERE message_id = ?", (s["id"],)).fetchone()
               for s in srcs]
        d["for_you"] = not (rel and all(r is not None and r["relevance"] == "not_relevant" for r in rel))
        evs.append(d)
    radar = planner.crunch_radar(c, now)
    radar["series"] = [{**s, "date": s["date"].isoformat()} for s in radar["series"]]
    radar["crunch_days"] = [s["date"] for s in radar["series"] if s["load"] >= 2]
    radar["peak"] = None
    radar["plans"] = [{**p, "due": fmt_dt(p["due"]), "start_by": p["start_by"].strftime("%a %d %b")}
                      for p in radar["plans"]]
    return ok({"events": evs, "radar": radar})


@app.get("/api/calendar.ics")
@login_required
def calendar(uid):
    c, _ = ctx(uid)
    return Response(build_ics(c), mimetype="text/calendar",
                    headers={"Content-Disposition": "attachment; filename=campuspulse.ics"})


@app.get("/api/tasks")
@login_required
def tasks(uid):
    c, now = ctx(uid)
    statuses = {e["id"]: e["status"] for e in repo.list_events(c)}
    out = []
    for t in repo.list_tasks(c):
        d = dict(t)
        d["event_status"] = statuses.get(t["event_id"])
        d["due_label"] = fmt_dt(datetime.fromisoformat(t["deadline"])) if t["deadline"] else None
        d["overdue"] = bool(t["deadline"]) and datetime.fromisoformat(t["deadline"]) < now
        out.append(d)
    return ok(out)


@app.patch("/api/tasks/<int:task_id>")
@login_required
def patch_task(uid, task_id):
    c, _ = ctx(uid)
    status = body().get("status")
    if status not in ("pending", "done"):
        return err("status must be pending or done")
    repo.set_task_status(c, task_id, status)
    return ok()


@app.post("/api/ask")
@login_required
def ask_ai(uid):
    c, _ = ctx(uid)
    q = (body().get("question") or "").strip()[:500]
    a = ask(c, q)
    return ok({"answer": a.answer, "conflicts": a.conflicts, "engine": a.engine,
               "citations": [{"label": label(x), "excerpt": x.excerpt, "kind": x.kind} for x in a.citations]})


@app.post("/api/chat")
@login_required
def chat(uid):
    from backend import chatbot
    c, now = ctx(uid)
    live = live_sync.status(userspace.live_dir(uid))
    return ok(chatbot.reply(c, body().get("message", ""), now, live))


@app.get("/api/groups")
@login_required
def groups(uid):
    c, _ = ctx(uid)
    return ok(rows(repo.list_groups(c)))


@app.delete("/api/groups/<int:group_id>")
@login_required
def delete_group(uid, group_id):
    c, now = ctx(uid)
    repo.delete_group(c, group_id)
    orchestrator.run_pipeline(c, now=now)
    return ok()


@app.get("/api/messages")
@login_required
def messages(uid):
    c, _ = ctx(uid)
    gid = request.args.get("group_id", type=int)
    noise = request.args.get("noise") == "1"
    kind = request.args.get("type") or None
    rs = repo.message_feed(c, gid, request.args.get("category") or None, include_noise=noise)
    out = []
    for r in rs:
        if kind and r["type"] != kind:
            continue
        out.append({"id": r["id"], "group": r["group_name"], "sender": r["sender"], "timestamp": r["timestamp"],
                    "text": r["text"], "type": r["type"], "category": r["category"], "summary": r["summary"],
                    "is_noise": bool(r["is_noise"]), "trust_label": r["trust_label"],
                    "relevance": r["relevance"], "links": json.loads(r["links_json"] or "[]")})
        if len(out) >= 300:
            break
    return ok(out)


@app.get("/api/resources")
@login_required
def resources(uid):
    c, _ = ctx(uid)
    docs = rows(repo.list_documents(c))
    for d in docs:
        d.pop("file_path", None)
    links = c.execute(
        """SELECT m.id, m.text, m.sender, m.timestamp, m.links_json, g.name AS group_name
           FROM messages m JOIN groups g ON g.id = m.group_id JOIN message_analyses a ON a.message_id = m.id
           WHERE a.is_noise = 0 AND (a.type = 'resource' OR m.links_json != '[]') ORDER BY m.timestamp DESC""").fetchall()
    return ok({"documents": docs,
               "links": [{**dict(r), "links": json.loads(r["links_json"] or "[]")} for r in links]})


# ----------------------------------------------------------------- import
@app.post("/api/import/chat")
@login_required
def import_chats(uid):
    c, now = ctx(uid)
    files = request.files.getlist("files")
    if not files:
        return err("Choose at least one .txt chat export.")
    names = request.form.getlist("names")
    cats = request.form.getlist("categories")
    officials = request.form.getlist("officials")
    results = []
    for i, f in enumerate(files):
        try:
            content = decode_upload(f.read(), f.filename or "chat.txt")
            name = (names[i] if i < len(names) and names[i].strip() else guess_group_name(f.filename or "Group"))
            cat = cats[i] if i < len(cats) and cats[i] else "general"
            offs = [s.strip() for s in (officials[i] if i < len(officials) else "").split(",") if s.strip()]
            r = import_chat(c, content, name.strip()[:80], cat, offs)
            results.append({"file": f.filename, "group": r.group_name, "parsed": r.parsed, "new": r.new,
                            "duplicates": r.duplicates})
        except UploadError as e:
            results.append({"file": f.filename, "error": str(e)})
    stats = orchestrator.run_pipeline(c, now=now)
    return ok({"results": results, "stats": stats.__dict__})


@app.post("/api/import/pdf")
@login_required
def import_pdf(uid):
    c, _ = ctx(uid)
    f = request.files.get("file")
    if not f or not (f.filename or "").lower().endswith(".pdf"):
        return err("Choose a PDF file.")
    name = secure_filename(f.filename) or "document.pdf"
    path = userspace.upload_dir(uid) / name
    f.save(path)
    try:
        digest = digest_pdf(path.read_bytes())
    except Exception:
        return err("Could not read that PDF.")
    gid = request.form.get("group_id", type=int)
    repo.add_document(c, name, str(path), digest.summary, digest.pages, gid)
    return ok({"filename": name, "summary": digest.summary, "warnings": digest.warnings, "chunks": len(digest.pages)})


@app.post("/api/import/demo")
@login_required
def import_demo(uid):
    c, _ = ctx(uid)
    from scripts.seed_demo import load_demo
    p = repo.get_profile(c)
    if not p.get("demo_now"):
        p["demo_now"] = "2026-10-10T15:22:00"  # sample chats are dated 5–10 Oct 2026
        repo.save_profile(c, p)
    out = load_demo(c)
    stats = orchestrator.run_pipeline(c, now=userspace.now_for(c))
    return ok({"stats": stats.__dict__, "imports": [r.__dict__ for r in out["imports"]]})


@app.post("/api/reprocess")
@login_required
def reprocess(uid):
    c, now = ctx(uid)
    return ok(orchestrator.run_pipeline(c, now=now).__dict__)


@app.delete("/api/data")
@login_required
def delete_data(uid):
    c, _ = ctx(uid)
    repo.delete_all_data(c)
    for d in repo.list_documents(c):
        repo.delete_document(c, d["id"])
    return ok()


# --------------------------------------------------------------- whatsapp
@app.get("/api/whatsapp/status")
@login_required
def wa_status(uid):
    c, now = ctx(uid)
    live = userspace.live_dir(uid)
    st = live_sync.status(live)
    synced = None
    if st["alive"] and st.get("state") == "ready":
        synced = live_sync.sync_and_process(c, now=now, live_dir=live).__dict__
    return ok({
        "state": st.get("state"), "alive": st["alive"], "detail": st.get("detail"),
        "account": st.get("account"), "simulated": st.get("simulated", False),
        "has_qr": bool(st.get("qr_path")) and st.get("state") == "qr",
        "has_avatar": bool(st.get("avatar_path")),
        "running": bridge_manager.is_running(uid),
        "groups": live_sync.available_groups(live), "selected": live_sync.selected_groups(live),
        "synced": synced, "requirements": bridge_manager.check_requirements(),
        "log": bridge_manager.log_tail(uid, 12) if st.get("state") in ("auth_failure", "stopped", "disconnected") else "",
    })


@app.post("/api/whatsapp/connect")
@login_required
def wa_connect(uid):
    try:
        return ok(bridge_manager.start(uid, simulate=bool(body().get("simulate"))))
    except bridge_manager.BridgeError as e:
        return err(str(e), 409)


@app.get("/api/whatsapp/qr")
@login_required
def wa_qr(uid):
    f = userspace.live_dir(uid) / "qr.png"
    if not f.exists():
        abort(404)
    resp = send_file(f, mimetype="image/png", max_age=0)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/api/whatsapp/avatar")
@login_required
def wa_avatar(uid):
    f = userspace.live_dir(uid) / "profile.jpg"
    if not f.exists():
        abort(404)
    return send_file(f, mimetype="image/jpeg", max_age=60)


@app.put("/api/whatsapp/groups")
@login_required
def wa_groups(uid):
    ids = body().get("group_ids") or []
    if not isinstance(ids, list):
        return err("group_ids must be a list")
    live = userspace.live_dir(uid)
    known = {g["id"] for g in live_sync.available_groups(live)}
    live_sync.save_selected_groups([str(i) for i in ids if str(i) in known], live)
    return ok()


@app.post("/api/whatsapp/sync")
@login_required
def wa_sync(uid):
    c, now = ctx(uid)
    return ok(live_sync.sync_and_process(c, now=now, live_dir=userspace.live_dir(uid)).__dict__)


@app.post("/api/whatsapp/disconnect")
@login_required
def wa_disconnect(uid):
    bridge_manager.stop(uid, logout=bool(body().get("logout")))
    return ok()


@app.errorhandler(413)
def too_large(_e):
    return err(f"File too large (max {config.MAX_UPLOAD_MB:.0f} MB).", 413)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"\n  CampusPulse AI → http://127.0.0.1:{port}\n")
    app.run(host=os.getenv("HOST", "127.0.0.1"), port=port, debug=os.getenv("FLASK_DEBUG") == "1", threaded=True)
