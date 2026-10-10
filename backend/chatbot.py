"""Pulse — the rule-based campus chatbot (no API key needed).

How it works:
  1. normalise the message ("tmrw" → "tomorrow", "plcmnt" → "placement")
  2. extract entities: time window (today / tomorrow / this week / a weekday / a date),
     category (placements, hackathons, academics, events), group name, task name
  3. match an intent with keyword rules (first match wins, ordered by specificity)
  4. answer from the user's own data (events, tasks, changes, rumours)
  5. anything else → the retrieval engine (rag/answer.py) with sources

Each reply is {"reply": markdown-lite text, "chips": follow-up suggestions, "link": optional page}.
"""
from __future__ import annotations

import json
import random
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from agent.change_detector import fmt_dt
from database import repository as repo

# ------------------------------------------------------------------ normalise
SLANG = {
    r"\btmrw\b|\btmr\b|\btomo\b|\b2morrow\b": "tomorrow",
    r"\btdy\b|\b2day\b": "today",
    r"\bwk\b": "week",
    r"\bplcmnt\b|\bplacment\b|\bplacemnt\b": "placement",
    r"\bhackthon\b|\bhackaton\b": "hackathon",
    r"\bassgn\b|\bassignmnt\b|\bassn\b": "assignment",
    r"\bmidsem\b|\bmid sem\b": "mid-sem",
    r"\bpls\b|\bplz\b": "please",
    r"\bu\b": "you",
    r"\br\b": "are",
    r"\bwat\b|\bwht\b": "what",
    r"\bwen\b": "when",
}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
CATEGORIES = {
    "placements": r"\b(placements?|internships?|intern|jobs?|company|companies|drives?|resume|interviews?|tpo)\b",
    "hackathons": r"\b(hackathons?|sih|hack|ppt|team)\b",
    "academics": r"\b(assignments?|exams?|mid-sem|quiz|viva|lab|class|lectures?|academics?|dbms|os|cn)\b",
    "events": r"\b(fest|events?|workshops?|seminars?|briefing|clubs?|volunteers?)\b",
}


def normalise(text: str) -> str:
    t = " " + text.lower().strip() + " "
    for pattern, repl in SLANG.items():
        t = re.sub(pattern, repl, t)
    return re.sub(r"\s+", " ", t).strip()


# ------------------------------------------------------------------ entities
@dataclass
class Entities:
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    window_label: str = ""
    category: Optional[str] = None
    group: Optional[str] = None
    rest: str = ""
    extras: Dict = field(default_factory=dict)


def extract_window(t: str, now: datetime) -> Tuple[Optional[datetime], Optional[datetime], str]:
    day = datetime(now.year, now.month, now.day)
    if "day after tomorrow" in t:
        s = day + timedelta(days=2)
        return s, s + timedelta(days=1), "the day after tomorrow"
    if re.search(r"\btoday\b|\btonight\b", t):
        return now, day + timedelta(days=1), "today"
    if "tomorrow" in t:
        s = day + timedelta(days=1)
        return s, s + timedelta(days=1), "tomorrow"
    if re.search(r"\bnext week\b", t):
        s = day + timedelta(days=7 - day.weekday())
        return s, s + timedelta(days=7), "next week"
    if re.search(r"\b(this|the) week(end)?\b|\bweek\b|\b7 days\b", t):
        if "weekend" in t:
            s = day + timedelta(days=(5 - day.weekday()) % 7)
            return s, s + timedelta(days=2), "this weekend"
        return now, day + timedelta(days=7), "the next 7 days"
    if re.search(r"\b(this|next) month\b|\bmonth\b", t):
        return now, day + timedelta(days=30), "the next 30 days"
    for i, wd in enumerate(WEEKDAYS):
        if re.search(rf"\b{wd}\b", t):
            delta = (i - day.weekday()) % 7 or 7
            s = day + timedelta(days=delta)
            return s, s + timedelta(days=1), s.strftime("%A %d %b")
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)? (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", t)
    if m:
        months = "jan feb mar apr may jun jul aug sep oct nov dec".split()
        try:
            s = datetime(now.year, months.index(m.group(2)) + 1, int(m.group(1)))
            if s < day - timedelta(days=60):
                s = s.replace(year=now.year + 1)
            return s, s + timedelta(days=1), s.strftime("%d %b")
        except ValueError:
            pass
    return None, None, ""


def extract(t: str, now: datetime, group_names: List[str]) -> Entities:
    e = Entities()
    e.start, e.end, e.window_label = extract_window(t, now)
    for cat, pattern in CATEGORIES.items():
        if re.search(pattern, t):
            e.category = cat
            break
    for g in sorted(group_names, key=len, reverse=True):
        if g.lower() in t:
            e.group = g
            break
    return e


# ------------------------------------------------------------------ intents
INTENTS: List[Tuple[str, str]] = [
    ("greet", r"^(hi+|hello|hey+|hii+|yo|namaste|good (morning|afternoon|evening))\b"),
    ("thanks", r"\b(thanks|thank you|thx|ty|great|awesome|cool)\b"),
    ("help", r"\b(help|what can you do|commands|how to use|options)\b"),
    ("mark_done", r"\b(mark|set)\b.*\b(done|complete|completed|finished)\b|^(done|finished|completed)\b"),
    ("rumor", r"\b(rumou?rs?|fake|true or false|is it true|real or fake|confirm(ed)?|verified)\b"),
    ("changes", r"\b(chang|moved|postpon|resched|extend|shift|updat|new venue|conflict)\w*"),
    ("whatsapp", r"\b(whatsapp|linked|connection|connected|sync)\b"),
    ("free", r"\b(free|nothing due|relax|chill|any break)\b"),
    ("crunch", r"\b(busy|busiest|crunch|workload|stress|overload|plan my|when should i start)\b"),
    ("tasks", r"\b(my tasks?|to ?do|pending|what should i do|action items?)\b"),
    ("brief", r"\b(summary|summari[sz]e|brief|overview|what'?s new|updates|catch me up|what did i miss)\b"),
    ("deadlines", r"\b(due|deadlines?|submit|submission|last date|closes?|what'?s (up|coming)|schedule|upcoming|events?)\b"),
    ("profile", r"\b(who am i|my profile|my details|my year|my branch)\b"),
    ("groups", r"\b(my groups|which groups|list groups|groups)\b"),
]


def detect_intent(t: str) -> str:
    for name, pattern in INTENTS:
        if re.search(pattern, t):
            return name
    return "search"


# ------------------------------------------------------------------ data helpers
def _upcoming(conn: sqlite3.Connection, now: datetime, e: Entities, kinds=("deadline", "event")) -> List[sqlite3.Row]:
    start = e.start or now
    end = e.end or (now + timedelta(days=14))
    out = []
    for ev in repo.list_events(conn):
        if not ev["current_at"] or ev["status"] == "cancelled" or ev["kind"] not in kinds:
            continue
        when = datetime.fromisoformat(ev["current_at"])
        if not (start <= when < end) or when < now:
            continue
        if e.category and ev["category"] != e.category:
            continue
        srcs = repo.event_sources(conn, ev["id"])
        if e.group and e.group not in {s["group_name"] for s in srcs}:
            continue
        rel = [conn.execute("SELECT relevance FROM message_analyses WHERE message_id = ?", (s["id"],)).fetchone()
               for s in srcs]
        if rel and all(r is not None and r["relevance"] == "not_relevant" for r in rel):
            continue  # clearly not for this student (shown on Today under "filtered")
        out.append(ev)
    return out


def _event_line(ev, now: datetime) -> str:
    when = datetime.fromisoformat(ev["current_at"])
    hours = (when - now).total_seconds() / 3600
    days = max(1, round(hours / 24))
    rel = f"in {int(hours)}h" if hours < 24 else f"in {days} day{'s' if days != 1 else ''}"
    loc = f", {ev['current_location']}" if ev["current_location"] else ""
    flag = " _(updated)_" if ev["status"] == "changed" else " _(conflicting info, verify)_" if ev["status"] == "conflict" else ""
    verb = "due" if ev["kind"] == "deadline" else ""
    return f"- **{ev['title']}**, {verb} {fmt_dt(when)}{loc} ({rel}){flag}".replace(",  ", ", ")


def _first_name(conn) -> str:
    return (repo.get_profile(conn).get("name") or "there").split()[0]


# ------------------------------------------------------------------ handlers
def reply(conn: sqlite3.Connection, message: str, now: datetime, live_status: Optional[Dict] = None) -> Dict:
    raw = (message or "").strip()[:400]
    if not raw:
        return {"reply": "Type a question, like **what's due this week?**", "chips": _chips()}
    t = normalise(raw)
    groups = [g["name"] for g in repo.list_groups(conn)]
    e = extract(t, now, groups)
    intent = detect_intent(t)
    if intent == "search" and e.window_label and not re.search(r"\b(where|who|how)\b", t):
        intent = "deadlines"  # "what's on saturday?" is a schedule question
    handler = HANDLERS.get(intent, h_search)
    out = handler(conn, t, raw, e, now, live_status or {})
    out.setdefault("chips", _chips(intent))
    out["intent"] = intent
    out["entities"] = {"window": e.window_label or None, "category": e.category, "group": e.group}
    return out


def _chips(intent: str = "") -> List[str]:
    base = ["What's due this week?", "Any changes?", "Is anything a rumour?", "My tasks", "Summarise today"]
    return [c for c in base if not c.lower().startswith(intent[:4])][:4]


def h_greet(conn, t, raw, e, now, live):
    hour = now.hour
    part = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
    due = _upcoming(conn, now, Entities(end=now + timedelta(hours=48)), kinds=("deadline",))
    tail = (f" You have **{len(due)} deadline{'s' if len(due) != 1 else ''}** in the next 48 hours."
            if due else " Nothing is due in the next 48 hours.")
    return {"reply": f"Good {part}, {_first_name(conn)}! I'm Pulse.{tail} What would you like to know?"}


def h_thanks(conn, t, raw, e, now, live):
    return {"reply": random.choice(["Happy to help!", "Anytime. Good luck with the deadlines!", "You're welcome!"])}


def h_help(conn, t, raw, e, now, live):
    return {"reply": "\n".join([
        "I read your groups so you don't have to. Try:",
        "- **What's due tomorrow?** or **deadlines this week**",
        "- **Placement updates** or **hackathon deadlines**",
        "- **Did anything change?** or **any conflicts?**",
        "- **Is the mid-sem postponed?** (I check rumours against official messages)",
        "- **My tasks**, then **mark SIH done**",
        "- **When should I start?** for a workload plan",
        "- Or ask anything: **where is the fest briefing?**",
    ])}


def h_deadlines(conn, t, raw, e, now, live):
    # "when/where is X" questions about a specific thing go to search
    if re.search(r"\b(where|venue|which room)\b", t) or (re.search(r"\bwhen is\b", t) and not e.window_label):
        return h_search(conn, t, raw, e, now, live)
    kinds = ("deadline",) if re.search(r"\b(due|deadline|submit|submission|last date|close)", t) else ("deadline", "event")
    evs = _upcoming(conn, now, e, kinds)
    scope = e.window_label or "the next 14 days"
    what = (CAT_LABEL.get(e.category, "") + " ").lstrip() if e.category else ""
    noun = "deadline" if kinds == ("deadline",) else "deadline and event"
    noun = noun + "s" if len(evs) != 1 else noun.replace(" and event", "/event")
    if e.group:
        what += f"from {e.group} "
    if not evs:
        return {"reply": f"No {what}{'deadlines' if kinds == ('deadline',) else 'deadlines or events'} for {scope}. 🎉",
                "link": "deadlines"}
    lines = [f"**{len(evs)} {what}{noun}** for {scope}:"] + [_event_line(ev, now) for ev in evs[:8]]
    if len(evs) > 8:
        lines.append(f"…and {len(evs) - 8} more on the Deadlines page.")
    return {"reply": "\n".join(lines), "link": "deadlines"}


CAT_LABEL = {"placements": "placement", "hackathons": "hackathon", "academics": "academic", "events": "event"}


def h_tasks(conn, t, raw, e, now, live):
    tasks = [x for x in repo.list_tasks(conn) if x["status"] == "pending"]
    if e.start:
        tasks = [x for x in tasks if x["deadline"] and e.start <= datetime.fromisoformat(x["deadline"]) < e.end]
    if not tasks:
        return {"reply": f"No open tasks{' for ' + e.window_label if e.window_label else ''}. You're all caught up ✅",
                "link": "tasks"}
    lines = [f"You have **{len(tasks)} open task{'s' if len(tasks) != 1 else ''}**:"]
    for x in tasks[:8]:
        due = fmt_dt(datetime.fromisoformat(x["deadline"])) if x["deadline"] else "no date"
        overdue = x["deadline"] and datetime.fromisoformat(x["deadline"]) < now
        lines.append(f"- **{x['title']}**, due {due}{' _(overdue)_' if overdue else ''}")
    lines.append("Say **mark <task> done** when you finish one.")
    return {"reply": "\n".join(lines), "link": "tasks", "chips": ["When should I start?", "What's due tomorrow?"]}


def h_mark_done(conn, t, raw, e, now, live):
    words = re.sub(r"\b(mark|set|as|the|task|done|complete|completed|finished|please|it)\b", " ", t)
    words = [w for w in re.findall(r"[a-z0-9]+", words) if len(w) > 1]
    tasks = [x for x in repo.list_tasks(conn) if x["status"] == "pending"]
    if not words:
        return {"reply": "Which task? For example: **mark SIH PPT done**."}
    best, score = None, 0
    for x in tasks:
        title = x["title"].lower()
        s = sum(1 for w in words if w in title)
        if s > score:
            best, score = x, s
    if not best:
        return {"reply": "I couldn't find an open task matching that. Say **my tasks** to see the list."}
    repo.set_task_status(conn, best["id"], "done")
    left = len(tasks) - 1
    return {"reply": f"Marked **{best['title']}** as done ✅ {left} task{'s' if left != 1 else ''} left.",
            "link": "tasks", "refresh": True}


def _specific_question(t: str) -> bool:
    """'is the OS mid-sem postponed?' asks about one thing; 'any changes?' asks for a list."""
    from agent.textutils import topic_signature
    topic, _ = topic_signature(t)
    topic -= {"any", "anything", "changes", "updates", "conflicts", "today", "week", "new"}
    return bool(re.match(r"^(is|was|has|did|are|will|does|when|where)\b", t)) and bool(topic)


def h_changes(conn, t, raw, e, now, live):
    if _specific_question(t):
        return h_search(conn, t, raw, e, now, live)
    logs = repo.list_changes(conn)
    if "conflict" in t:
        logs = [c for c in logs if c["kind"] == "conflict"]
    if e.category:
        cats = {ev["id"]: ev["category"] for ev in repo.list_events(conn)}
        logs = [c for c in logs if cats.get(c["event_id"]) == e.category]
    if not logs:
        return {"reply": "No changes detected. Everything is as first announced.", "link": "changes"}
    lines = [f"**{len(logs)} update{'s' if len(logs) != 1 else ''}** across your groups:"]
    for c in logs[:6]:
        old, new = json.loads(c["old_values"]), json.loads(c["new_values"])
        diff = "; ".join(f"{old.get(k) or '—'} → **{v}**" for k, v in new.items())
        tag = "⚠️ conflict" if c["kind"] == "conflict" else "changed"
        lines.append(f"- **{c['title']}** ({tag}): {diff}")
    return {"reply": "\n".join(lines), "link": "changes"}


def h_rumor(conn, t, raw, e, now, live):
    # a specific claim ("is the mid-sem postponed?") → search, but show the rumour verdict first
    rows = conn.execute(
        """SELECT m.text, m.sender, g.name AS group_name, a.trust_label, a.trust_reasons
           FROM messages m JOIN groups g ON g.id = m.group_id JOIN message_analyses a ON a.message_id = m.id
           WHERE a.trust_reasons LIKE '%Hearsay%' OR a.trust_label = 'contradicted'""").fetchall()
    from agent.textutils import topic_signature
    q_topic, _ = topic_signature(t)
    q_topic -= {"rumour", "rumor", "fake", "true", "real", "confirm", "confirmed", "verified"}
    matches = [r for r in rows if q_topic & topic_signature(r["text"])[0]] if q_topic else rows
    if not matches:
        if q_topic:
            return h_search(conn, t, raw, e, now, live)
        return {"reply": "No rumours spotted in your groups right now. 👍", "link": "rumors"}
    lines = []
    for r in matches[:4]:
        reasons = json.loads(r["trust_reasons"] or "[]")
        verdict = ("❌ **Contradicted**" if r["trust_label"] == "contradicted" else "⚠️ **Unverified**")
        evidence = next((x for x in reasons if x.startswith(("Contradicted by", "No official"))), "")
        lines.append(f"- {verdict}: “{r['text'][:90]}” ({r['sender']}, {r['group_name']}). {evidence}.")
    return {"reply": "Here's what Rumor Shield found:\n" + "\n".join(lines), "link": "rumors"}


def h_brief(conn, t, raw, e, now, live):
    from agent import planner
    b = planner.build_brief(conn, now)
    top = [i for i in b["top"] if i["priority"] >= 55][:5]
    if not top:
        return {"reply": "Nothing needs your attention right now.", "link": "today"}
    lines = [f"Here's your brief, {_first_name(conn)}:"]
    for i in top:
        when = f", {i['when_label']}" if i.get("when_label") else ""
        status = " _(updated)_" if i.get("status") == "changed" else " _(conflict)_" if i.get("status") == "conflict" else ""
        lines.append(f"- **{i['title']}**{when}{status}")
    extra = []
    if b["conflicts"]:
        extra.append(f"{b['conflicts']} conflict{'s' if b['conflicts'] > 1 else ''} to verify")
    if b["rumors"]:
        extra.append(f"{b['rumors']} rumour{'s' if b['rumors'] > 1 else ''} filtered")
    if extra:
        lines.append("Also: " + ", ".join(extra) + ".")
    return {"reply": "\n".join(lines), "link": "today"}


def h_crunch(conn, t, raw, e, now, live):
    from agent import planner
    r = planner.crunch_radar(conn, now)
    lines = []
    if r["crunch_days"]:
        days = ", ".join(s["date"].strftime("%a %d %b") for s in r["crunch_days"])
        lines.append(f"Your busiest day{'s are' if len(r['crunch_days']) > 1 else ' is'} **{days}**.")
    elif r["peak"] and r["peak"]["load"]:
        lines.append(f"No crunch ahead. Busiest day: **{r['peak']['date']:%a %d %b}**.")
    if r["plans"]:
        lines.append("Start in this order:")
        lines += [f"- **{p['task']}** by {p['start_by']:%a %d %b} (≈{p['effort_days']} day{'s' if p['effort_days'] > 1 else ''})"
                  for p in r["plans"][:6]]
    return {"reply": "\n".join(lines) or "No deadlines in the next two weeks. Enjoy!", "link": "deadlines"}


def h_free(conn, t, raw, e, now, live):
    if not e.start:
        e.start, e.end, e.window_label = extract_window("tomorrow", now)
    evs = _upcoming(conn, now, e)
    if not evs:
        return {"reply": f"Yes! Nothing scheduled for {e.window_label}. 😌"}
    return {"reply": f"Not quite. {e.window_label.capitalize()} has:\n" + "\n".join(_event_line(x, now) for x in evs)}


def h_whatsapp(conn, t, raw, e, now, live):
    if live.get("alive") and live.get("state") == "ready":
        acct = live.get("account") or {}
        return {"reply": f"WhatsApp is **connected** as {acct.get('name') or 'your account'} "
                         f"(number ending {(acct.get('number') or '')[-4:]}). New messages sync every 20 seconds.",
                "link": "whatsapp"}
    return {"reply": "WhatsApp isn't connected. Open the WhatsApp page and click **Show QR code** to link your number.",
            "link": "whatsapp"}


def h_profile(conn, t, raw, e, now, live):
    p = repo.get_profile(conn)
    return {"reply": f"You're **{p.get('name')}**, {p.get('branch') or 'branch not set'}, year {p.get('year') or '?'}, "
                     f"{p.get('grad_year') or '?'} batch. Interests: {', '.join(p.get('interests', [])) or 'none set'}.",
            "link": "profile"}


def h_groups(conn, t, raw, e, now, live):
    gs = repo.list_groups(conn)
    if not gs:
        return {"reply": "No groups yet. Link WhatsApp or import a chat export.", "link": "whatsapp"}
    return {"reply": "Your groups:\n" + "\n".join(f"- **{g['name']}** ({g['message_count']} messages)" for g in gs),
            "link": "groups"}


def h_search(conn, t, raw, e, now, live):
    from rag.answer import ask
    from rag.citations import label
    a = ask(conn, raw)
    text = a.answer
    if a.conflicts:
        text += "\n\n⚠️ " + a.conflicts[0]
    if a.citations:
        text += "\n\nSources: " + "; ".join(label(c) for c in a.citations[:2])
    if text.startswith("I couldn't find"):
        text += " Try **help** to see what I can do."
    return {"reply": text}


HANDLERS = {
    "greet": h_greet, "thanks": h_thanks, "help": h_help, "deadlines": h_deadlines, "tasks": h_tasks,
    "mark_done": h_mark_done, "changes": h_changes, "rumor": h_rumor, "brief": h_brief, "crunch": h_crunch,
    "free": h_free, "whatsapp": h_whatsapp, "profile": h_profile, "groups": h_groups, "search": h_search,
}
