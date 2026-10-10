"""What Changed? — confirmed updates and unresolved conflicts, with sources."""
from __future__ import annotations

import json

import streamlit as st

from database import repository as repo
from frontend.components import badge, empty, esc, fmt_ts, section

FIELD = {"when": "🗓 Date / time", "location": "📌 Venue", "status": "Status"}


def _diff_html(old: dict, new: dict) -> str:
    rows = []
    for key in new:
        rows.append(
            f'<div class="cp-meta" style="margin-top:.4rem">{FIELD.get(key, key)}</div>'
            f'<div class="cp-diff"><div class="cp-old">{esc(str(old.get(key) or "—"))}</div>'
            f'<div class="cp-arrow">→</div><div class="cp-new">{esc(str(new[key]))}</div></div>'
        )
    return "".join(rows)


def _src(conn, mid, label) -> str:
    m = repo.get_message(conn, mid) if mid else None
    if not m:
        return ""
    return (f'<div class="cp-meta" style="margin-top:.4rem"><b>{label}</b> · {esc(m["group_name"])} · '
            f'{esc(m["sender"] or "")} · {esc(fmt_ts(m["timestamp"]))}</div>'
            f'<div class="cp-quote">{esc(m["text"])}</div>')


def render(conn, now) -> None:
    st.title("What Changed?")
    st.caption("A newer message can invalidate an older one. Changes are applied only when the new message "
               "explicitly says so; otherwise both versions are shown as a conflict. The latest message doesn't "
               "automatically win.")
    logs = repo.list_changes(conn)
    changes = [c for c in logs if c["kind"] == "change"]
    conflicts = [c for c in logs if c["kind"] == "conflict"]

    section(f"Conflicts to verify · {len(conflicts)}")
    if not conflicts:
        empty("No conflicting announcements.")
    for c in conflicts:
        html = (f'<div class="cp-card upcoming">{badge("Conflict", "amber")}'
                f'<div class="cp-title">{esc(c["title"])}</div>'
                f'{_diff_html(json.loads(c["old_values"]), json.loads(c["new_values"]))}'
                f'<div class="cp-why">{esc(c["explanation"])}</div>'
                f'{_src(conn, c["old_message_id"], "Earlier")}{_src(conn, c["source_message_id"], "Newer")}</div>')
        st.markdown(html, unsafe_allow_html=True)

    section(f"Confirmed changes · {len(changes)}")
    if not changes:
        empty("No changes detected yet.")
    for c in changes:
        html = (f'<div class="cp-card updated">{badge("Change detected", "blue")}'
                f'<div class="cp-title">{esc(c["title"])}</div>'
                f'{_diff_html(json.loads(c["old_values"]), json.loads(c["new_values"]))}'
                f'<div class="cp-why">{esc(c["explanation"])}</div>'
                f'{_src(conn, c["old_message_id"], "Original")}{_src(conn, c["source_message_id"], "Update")}</div>')
        st.markdown(html, unsafe_allow_html=True)
