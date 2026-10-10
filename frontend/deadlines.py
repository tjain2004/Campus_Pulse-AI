"""Deadline timeline + Crunch Radar (workload forecast with Smart Start dates)."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from agent import planner
from agent.change_detector import fmt_dt
from database import repository as repo
from frontend.components import badge, card, empty, esc, relative, section
from utils.calendar_export import build_ics


def render(conn, now: datetime) -> None:
    st.title("Deadlines & Crunch Radar")
    events = [e for e in repo.list_events(conn) if e["current_at"]]
    upcoming = [e for e in events if datetime.fromisoformat(e["current_at"]) >= now and e["status"] != "cancelled"]

    st.download_button("📅 Add all to my calendar (.ics)", build_ics(conn), file_name="campuspulse.ics",
                       mime="text/calendar", help="Works with Google Calendar, Outlook and Apple Calendar")

    # ---------------------------------------------------------------- radar
    radar = planner.crunch_radar(conn, now)
    section("Crunch Radar · next 14 days")
    try:
        import pandas as pd
        df = pd.DataFrame([{"day": s["date"].strftime("%a %d"), "workload": s["load"]} for s in radar["series"]])
        st.bar_chart(df, x="day", y="workload", height=220, color="#0f766e")
    except Exception:  # pandas missing or old Streamlit
        for s in radar["series"]:
            st.write(f"{s['date']:%a %d %b}: {'█' * int(s['load'] * 4)} {s['load']}")
    if radar["crunch_days"]:
        days = ", ".join(f"**{s['date']:%a %d %b}**" for s in radar["crunch_days"])
        st.warning(f"🔥 Crunch ahead on {days} — several deadlines stack up. Start early using the plan below.")
    elif radar["peak"] and radar["peak"]["load"] > 0:
        st.success(f"Workload looks manageable. Busiest day: {radar['peak']['date']:%a %d %b}.")
    if radar["plans"]:
        st.markdown("**Smart Start plan** — when to begin each task so nothing collides:")
        for p in radar["plans"]:
            st.markdown(f"- Start **{esc(p['task'])}** by **{p['start_by']:%a %d %b}** "
                        f"(≈{p['effort_days']} day{'s' if p['effort_days'] > 1 else ''} of work, due {fmt_dt(p['due'])})")

    # ------------------------------------------------------------- timeline
    section(f"Timeline · {len(upcoming)} upcoming")
    if not upcoming:
        empty("No upcoming deadlines or events.")
    for e in upcoming:
        when = datetime.fromisoformat(e["current_at"])
        hours = (when - now).total_seconds() / 3600
        band = "urgent" if hours <= 48 else "upcoming" if hours <= 24 * 7 else "fyi"
        badges = badge("Deadline" if e["kind"] == "deadline" else "Event", "red" if e["kind"] == "deadline" else "teal")
        if e["status"] == "changed":
            badges += badge("Updated", "blue")
            band = "updated"
        if e["status"] == "conflict":
            badges += badge("Conflict — verify", "amber")
        meta = f"🗓 {esc(fmt_dt(when))} <b>({esc(relative(when, now))})</b>"
        if e["current_location"]:
            meta += f" &nbsp;·&nbsp; 📌 {esc(e['current_location'])}"
        srcs = repo.event_sources(conn, e["id"])
        groups = sorted({s["group_name"] for s in srcs})
        meta += f"<br>Sources: {esc(', '.join(groups))} ({len(srcs)} message{'s' if len(srcs) != 1 else ''})"
        extra = ""
        if e["status"] == "changed" and e["original_at"]:
            extra = (f'<div class="cp-meta" style="margin-top:.3rem">Originally: '
                     f'<s>{esc(fmt_dt(datetime.fromisoformat(e["original_at"])))}'
                     f'{", " + esc(e["original_location"]) if e["original_location"] else ""}</s></div>')
        card(e["title"], band=band, badges=badges, meta=meta, extra_html=extra)
