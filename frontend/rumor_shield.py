"""RUMOR SHIELD + Cross-Group Doubt Solver (the innovation)."""
from __future__ import annotations

import json

import streamlit as st

from agent.orchestrator import unanswered_questions
from database import repository as repo
from frontend.components import badge, card, empty, esc, fmt_ts, meter, section, source_line, trust_badge
from rag.answer import solve_doubt
from rag.citations import label


def render(conn, now) -> None:
    st.title("🛡️ Rumor Shield")
    st.caption("“I heard the exam is postponed??” spreads faster than the official notice. Rumor Shield checks "
               "every claim against official senders in **all** your groups, and gives it a verdict with evidence.")

    rows = conn.execute(
        """SELECT m.id, m.text, m.sender, m.timestamp, g.name AS group_name, a.trust_label, a.trust_score,
                  a.trust_reasons, a.type, a.is_noise
           FROM messages m JOIN groups g ON g.id = m.group_id
           JOIN message_analyses a ON a.message_id = m.id WHERE a.is_noise = 0"""
    ).fetchall()
    rumors = [r for r in rows if "Hearsay" in (r["trust_reasons"] or "") or r["trust_label"] == "contradicted"]
    verified = [r for r in rows if r["trust_label"] == "verified"]
    contradicted = [r for r in rumors if r["trust_label"] == "contradicted"]

    c1, c2, c3 = st.columns(3)
    c1.metric("Claims checked", len(rows))
    c2.metric("Rumors detected", len(rumors))
    c3.metric("Busted by official sources", len(contradicted))

    section("Rumor verdicts")
    if not rumors:
        empty("No rumors detected. 🎉")
    for r in sorted(rumors, key=lambda r: r["trust_score"] or 0):
        reasons = json.loads(r["trust_reasons"] or "[]")
        tone = "red" if r["trust_label"] == "contradicted" else "amber"
        verdict = ("CONTRADICTED — an official message says otherwise" if r["trust_label"] == "contradicted"
                   else "UNVERIFIED — no official source confirms this")
        extra = meter(r["trust_score"] or 0, tone)
        extra += '<div class="cp-why"><b>Signals:</b> ' + esc(" · ".join(reasons)) + "</div>"
        ev_msg = _evidence(conn, r["id"], reasons)
        if ev_msg:
            extra += (f'<div class="cp-meta" style="margin-top:.45rem"><b>Official evidence</b> · '
                      f'{source_line(ev_msg["group_name"], ev_msg["sender"], ev_msg["timestamp"])}</div>'
                      f'<div class="cp-quote" style="background:#e6f4ec">{esc(ev_msg["text"])}</div>')
        card(verdict, band="urgent" if tone == "red" else "upcoming",
             badges=trust_badge(r["trust_label"], r["trust_score"]),
             meta=source_line(r["group_name"], r["sender"], r["timestamp"]), quote=r["text"], extra_html=extra)

    # ------------------------------------------------------- doubt solver
    section("Cross-Group Doubt Solver")
    st.caption("Questions nobody answered in their own group — answered from what was posted in your *other* "
               "groups and documents.")
    doubts = unanswered_questions(conn)
    if not doubts:
        empty("Every question got an answer.")
    for q in doubts:
        sol = solve_doubt(conn, q)
        ans = sol["answer"]
        if sol["found"]:
            src = ", ".join(sol["from_groups"]) or "your groups"
            title = f"Answer found in {src}"
            band, b = "ok", badge("Answered by CampusPulse", "green")
            if sol["cross_group"]:
                b += badge("Cross-group", "blue")
        else:
            title = "Not answered anywhere yet"
            band, b = "fyi", badge("Ask the organiser", "grey")
        card(title, band=band, badges=b, meta=source_line(q["group"], q["sender"], q["timestamp"]),
             quote="❓ " + q["text"])
        if sol["found"]:
            with st.expander("See answer with sources", expanded=sol["cross_group"]):
                st.markdown(ans.answer)
                for i, c in enumerate(ans.citations[:4], start=1):
                    st.caption(f"[{i}] {label(c)}")

    with st.expander(f"Verified official announcements · {len(verified)}"):
        for r in verified[:40]:
            st.markdown(f"{trust_badge('verified')} **{esc(r['group_name'])}** · {esc(r['sender'])} · "
                        f"{esc(fmt_ts(r['timestamp']))}<br>{esc(r['text'][:220])}", unsafe_allow_html=True)


def _evidence(conn, message_id: int, reasons):
    """Find the official message referenced by 'Contradicted by …' / 'Confirmed by …'."""
    ref = next((x for x in reasons if x.startswith(("Contradicted by", "Confirmed by"))), None)
    if not ref:
        return None
    sender_group = ref.split(" by ", 1)[1]
    sender, _, group = sender_group.rpartition(" in ")
    row = conn.execute(
        """SELECT m.*, g.name AS group_name FROM messages m JOIN groups g ON g.id = m.group_id
           JOIN message_analyses a ON a.message_id = m.id
           WHERE m.sender = ? AND g.name = ? AND a.trust_label = 'verified'
           ORDER BY m.timestamp DESC""", (sender, group)).fetchall()
    # prefer the one that explicitly denies rumours
    for r in row:
        if any(w in r["text"].lower() for w in ("no change", "as scheduled", "rumour", "rumor", "fake", "not ")):
            return r
    return row[0] if row else None
