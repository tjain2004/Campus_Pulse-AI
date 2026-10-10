"""My Tasks: action items extracted from every group (deadlines follow updates)."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from agent.change_detector import fmt_dt
from database import repository as repo
from frontend.components import empty, esc, relative, section, source_line


def render(conn, now: datetime) -> None:
    st.title("My Tasks")
    st.caption("Generated from deadlines and action items. If a deadline is extended in any group, "
               "the task's due date updates automatically.")
    tasks = repo.list_tasks(conn)
    statuses = {e["id"]: e["status"] for e in repo.list_events(conn)}
    pending = [t for t in tasks if t["status"] == "pending"]
    done = [t for t in tasks if t["status"] == "done"]

    if tasks:
        st.progress(len(done) / len(tasks), text=f"{len(done)} of {len(tasks)} done")
    section(f"To do · {len(pending)}")
    if not pending:
        empty("All caught up! ✅")
    for t in sorted(pending, key=lambda t: t["deadline"] or "9999"):
        due = datetime.fromisoformat(t["deadline"]) if t["deadline"] else None
        overdue = due is not None and due < now
        c1, c2 = st.columns([0.06, 0.94])
        if c1.checkbox("done", key=f"task_{t['id']}", label_visibility="collapsed"):
            repo.set_task_status(conn, t["id"], "done")
            st.rerun()
        label = f"**{t['title']}**"
        if due:
            label += f" — due {fmt_dt(due)} ({'overdue' if overdue else relative(due, now)})"
        c2.markdown(label)
        status = statuses.get(t["event_id"])
        if status == "changed":
            c2.info("Deadline was updated by a newer announcement — the date above is the latest.", icon="🔄")
        elif status == "conflict":
            c2.warning("Groups disagree about this deadline. See What Changed? and confirm.", icon="⚠️")
        c2.markdown(f'<div class="cp-meta">{source_line(t["group_name"], t["source_sender"], t["source_time"])}'
                    f'</div><div class="cp-quote">{esc(t["source_text"])}</div>', unsafe_allow_html=True)

    if done:
        with st.expander(f"Done · {len(done)}"):
            for t in done:
                c1, c2 = st.columns([0.8, 0.2])
                c1.markdown(f"~~{t['title']}~~")
                if c2.button("Undo", key=f"undo_{t['id']}"):
                    repo.set_task_status(conn, t["id"], "pending")
                    st.rerun()
