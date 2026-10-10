"""Resources: shared links/notes from every group + PDF digests."""
from __future__ import annotations

import json

import streamlit as st

from database import repository as repo
from frontend.components import card, empty, esc, section, source_line


def render(conn, now) -> None:
    st.title("Resources & documents")
    docs = repo.list_documents(conn)
    section(f"PDF digests · {len(docs)}")
    if not docs:
        empty("No PDFs imported yet — add guidelines or circulars on the Import page.")
    for d in docs:
        with st.container(border=True):
            st.markdown(f"**📄 {esc(d['filename'])}** · {d['chunk_count']} searchable chunks"
                        + (f" · shared in {esc(d['group_name'])}" if d["group_name"] else ""))
            st.markdown(d["summary"] or "_No summary_")
            st.caption("Every key point keeps its page number so Ask Campus AI can cite it.")

    rows = conn.execute(
        """SELECT m.*, g.name AS group_name FROM messages m JOIN groups g ON g.id = m.group_id
           JOIN message_analyses a ON a.message_id = m.id
           WHERE a.is_noise = 0 AND (a.type = 'resource' OR m.links_json != '[]')
           ORDER BY m.timestamp DESC"""
    ).fetchall()
    section(f"Links & notes shared in groups · {len(rows)}")
    if not rows:
        empty("No shared resources yet.")
    for r in rows:
        links = json.loads(r["links_json"] or "[]")
        link_html = " ".join(f'<a href="{esc(u)}" target="_blank">🔗 {esc(u[:60])}</a>' for u in links)
        card(r["text"].split("\n")[0][:90], band="ok", meta=source_line(r["group_name"], r["sender"], r["timestamp"]),
             extra_html=f'<div class="cp-meta" style="margin-top:.3rem">{link_html}</div>' if link_html else "")
