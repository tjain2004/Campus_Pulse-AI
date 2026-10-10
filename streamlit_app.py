"""CampusPulse AI — one reliable feed from all your college WhatsApp groups.

Run:  streamlit run streamlit_app.py   (the main web app is now: python app.py)
"""
from __future__ import annotations

from datetime import datetime, time

import streamlit as st

import config
from agent import llm
from agent.orchestrator import run_pipeline
from database import repository as repo
from database.connection import get_connection
from frontend import (ask_ai, changes, dashboard, deadlines, groups, live, profile, resources, rumor_shield,
                      tasks, upload)
from ingestion import live_sync
from frontend.components import inject_css

st.set_page_config(page_title="CampusPulse AI", page_icon="📡", layout="wide")
inject_css()


@st.cache_resource
def _conn():
    return get_connection()


conn = _conn()

PAGES = {
    "🏠 Today's Brief": dashboard,
    "🔄 What Changed?": changes,
    "🛡️ Rumor Shield": rumor_shield,
    "🗓 Deadlines & Crunch Radar": deadlines,
    "✅ My Tasks": tasks,
    "💬 Ask Campus AI": ask_ai,
    "👥 Groups": groups,
    "📚 Resources": resources,
    "📲 Live WhatsApp": live,
    "📥 Import": upload,
    "🙋 Profile": profile,
}

with st.sidebar:
    st.markdown("## 📡 CampusPulse AI")
    st.caption("All your WhatsApp groups → one trustworthy feed")
    page = st.radio("Navigate", list(PAGES), label_visibility="collapsed")
    st.divider()
    ref = config.reference_now()
    demo_date = st.date_input("“Today” (for demos)", ref.date(),
                              help="Pin the date so the sample chats' deadlines stay in the future.")
    now = datetime.combine(demo_date, ref.time() if demo_date == ref.date() else time(15, 0))
    if st.session_state.get("_last_now") != now.date():
        st.session_state["_last_now"] = now.date()
        if repo.list_groups(conn):
            run_pipeline(conn, now=now)
    wa = live_sync.status()
    if wa["alive"] and wa.get("state") == "ready":
        # pull in anything new from the WhatsApp bridge on every page load
        live_sync.sync_and_process(conn, now=now)
        st.caption("📲 WhatsApp: 🟢 live")
    st.caption(f"AI engine: {'🧠 LLM (' + llm.provider() + ')' if llm.available() else '⚙️ rule engine (offline)'}")
    p = repo.get_profile(conn)
    st.caption(f"Profile: {p.get('branch', '—')} · year {p.get('year', '—')} · {p.get('grad_year', '—')} batch")

if not repo.list_groups(conn) and page not in ("📥 Import", "🙋 Profile", "📲 Live WhatsApp"):
    st.markdown("# 📡 CampusPulse AI")
    st.markdown("#### Twelve WhatsApp groups. One feed you can trust.")
    st.write(
        "Import your class, placement, hackathon and club group exports. CampusPulse filters the noise, "
        "pulls out deadlines and tasks, catches when an announcement changes, busts rumors with official "
        "sources, and answers your questions with citations."
    )
    c1, c2 = st.columns(2)
    if c1.button("▶ Load demo data (4 groups + 1 PDF)", type="primary"):
        from scripts.seed_demo import load_demo
        with st.spinner("Importing and analysing…"):
            load_demo(conn)
            run_pipeline(conn, now=now)
        st.rerun()
    c2.write("or go to **📲 Live WhatsApp** to link your number, or **📥 Import** to upload chat exports.")
    st.stop()

PAGES[page].render(conn, now)
