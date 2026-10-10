"""Group views: the original messages of one group, with AI labels."""
from __future__ import annotations

import json
from collections import Counter

import streamlit as st

from database import repository as repo
from frontend.components import CATEGORY_LABEL, badge, card, empty, esc, fmt_ts, trust_badge

TYPE_TONE = {"deadline": "red", "task": "amber", "update": "blue", "announcement": "teal",
             "question": "grey", "resource": "green", "chatter": "grey"}


def render(conn, now) -> None:
    groups = repo.list_groups(conn)
    if not groups:
        empty("No groups imported yet.")
        return
    st.title("Your groups")
    names = ["All groups"] + [g["name"] for g in groups]
    choice = st.radio("Group", names, horizontal=True, label_visibility="collapsed")
    gid = None if choice == "All groups" else next(g["id"] for g in groups if g["name"] == choice)

    c1, c2, c3 = st.columns([2, 2, 1])
    cat = c1.selectbox("Category", ["all"] + list(CATEGORY_LABEL), format_func=lambda c: "All categories" if c == "all" else CATEGORY_LABEL[c])
    kind = c2.selectbox("Type", ["all", "deadline", "task", "update", "announcement", "question", "resource", "chatter"])
    show_noise = c3.toggle("Show noise", value=False)

    rows = repo.message_feed(conn, gid, None if cat == "all" else cat, include_noise=show_noise)
    if kind != "all":
        rows = [r for r in rows if r["type"] == kind]

    counts = Counter(r["type"] for r in repo.message_feed(conn, gid, include_noise=True))
    total = sum(counts.values())
    st.caption(f"{total} messages · {counts.get('deadline', 0)} deadlines · {counts.get('task', 0)} tasks · "
               f"{counts.get('update', 0)} updates · {counts.get('question', 0)} questions · "
               f"{counts.get('chatter', 0)} chatter")

    for r in rows[:200]:
        if r["type"] is None:
            badges = badge("not analysed", "grey")
        else:
            badges = badge(r["type"], TYPE_TONE.get(r["type"], "grey"))
            badges += badge(CATEGORY_LABEL.get(r["category"], r["category"] or ""), "teal")
            badges += trust_badge(r["trust_label"])
            if r["is_noise"]:
                badges += badge("noise", "grey")
            if r["relevance"] == "not_relevant":
                badges += badge("not for you", "grey")
        links = json.loads(r["links_json"] or "[]")
        meta = f"📍 {esc(r['group_name'])} · {esc(r['sender'] or 'system')} · {esc(fmt_ts(r['timestamp']))}"
        if links:
            meta += " · " + " ".join(f'<a href="{esc(u)}" target="_blank">🔗 link</a>' for u in links[:3])
        band = {"deadline": "urgent", "task": "upcoming", "update": "updated"}.get(r["type"] or "", "fyi")
        card(r["summary"] or r["text"][:80], band=band, badges=badges, meta=meta, quote=r["text"])
    if not rows:
        empty("No messages match these filters.")
