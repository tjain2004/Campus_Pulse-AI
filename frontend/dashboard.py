"""Today's Brief: one ranked feed across every imported group."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from agent import planner
from database import repository as repo
from frontend.components import (CATEGORY_LABEL, badge, card, empty, esc, relative, section,
                                 source_line, trust_badge)


def _card_for(item: dict, now: datetime) -> None:
    band = planner.priority_band(item["priority"])
    if item["status"] in ("changed", "cancelled"):
        band_css, label = "updated", ("Updated" if item["status"] == "changed" else "Cancelled")
    elif item["status"] == "conflict":
        band_css, label = "upcoming", "Conflict"
    else:
        band_css, label = band, {"urgent": "Urgent", "upcoming": "Upcoming", "fyi": "FYI"}[band]
    tone = {"Urgent": "red", "Upcoming": "amber", "Updated": "blue", "Conflict": "amber",
            "Cancelled": "red", "FYI": "grey"}[label]
    badges = badge(label, tone) + badge(CATEGORY_LABEL.get(item["category"], item["category"]), "teal")
    badges += trust_badge(item["trust_label"])
    if item["needs_verification"]:
        badges += badge("Check date", "amber")
    if item["relevance"] == "relevant":
        badges += badge("For you", "green")

    when_bits = []
    if item["when_label"]:
        prefix = "Due " if item["type"] in ("deadline", "task") else ""
        when_bits.append(f"🗓 {prefix}{esc(item['when_label'])} <b>({esc(relative(item['when'], now))})</b>")
    if item["location"]:
        when_bits.append(f"📌 {esc(item['location'])}")
    meta = " &nbsp;·&nbsp; ".join(when_bits)
    meta += ("<br>" if meta else "") + source_line(item["group"], item["sender"], item["timestamp"])
    if item["also_in"]:
        meta += f" &nbsp;·&nbsp; also posted in {esc(', '.join(item['also_in']))}"
    card(item["title"], band=band_css, badges=badges, meta=meta, why=item["reason"], quote=item["text"])


def render(conn, now: datetime) -> None:
    profile = repo.get_profile(conn)
    brief = planner.build_brief(conn, now)
    groups = repo.list_groups(conn)
    total = sum(g["message_count"] for g in groups)
    noise = conn.execute("SELECT COUNT(*) FROM message_analyses WHERE is_noise = 1").fetchone()[0]
    changes = conn.execute("SELECT COUNT(*) FROM change_logs WHERE kind='change'").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='pending'").fetchone()[0]

    st.markdown(f'<div class="cp-hero"><h1>Good {_greeting(now)}, {esc((profile.get("name") or "there").split()[0])}</h1></div>'
                f'<div class="cp-sub">{now.strftime("%A, %d %B %Y")} · {len(groups)} groups, '
                f'{total} messages read so you don\'t have to.</div>', unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Need your attention", len([i for i in brief["top"] if i["priority"] >= 55]))
    c2.metric("Noise filtered", f"{(noise / total * 100) if total else 0:.0f}%", help="ok / thanks / emoji / system messages")
    c3.metric("Changes caught", changes)
    c4.metric("Open tasks", pending)

    if brief["conflicts"]:
        st.warning(f"⚠️ {brief['conflicts']} announcement(s) have conflicting details across messages — "
                   "see **What Changed?**")
    if brief["rumors"]:
        st.info(f"🛡️ Rumor Shield kept {brief['rumors']} unverified/contradicted claim(s) out of your brief — "
                "see **Rumor Shield**.")

    top = brief["top"]
    urgent = [i for i in top if i["priority"] >= 80]
    upcoming = [i for i in top if 55 <= i["priority"] < 80]
    fyi = [i for i in top if i["priority"] < 55]

    section(f"Urgent · {len(urgent)}")
    for item in urgent:
        _card_for(item, now)
    if not urgent:
        empty("Nothing urgent right now. 🎉")
    section(f"Upcoming · {len(upcoming)}")
    for item in upcoming:
        _card_for(item, now)
    if not upcoming:
        empty("No upcoming items.")
    if fyi:
        with st.expander(f"FYI · {len(fyi)} lower-priority updates"):
            for item in fyi:
                _card_for(item, now)
    if brief["not_for_you"]:
        with st.expander(f"Filtered as not for you · {len(brief['not_for_you'])} (never hidden silently)"):
            st.caption("Based on your profile. Wrong? Update your profile.")
            for item in brief["not_for_you"]:
                card(item["title"], band="fyi", badges=badge("Not for you", "grey"),
                     meta=source_line(item["group"], item["sender"], item["timestamp"]),
                     why=item["relevance_reason"], why_label="Why it's filtered", quote=item["text"])


def _greeting(now: datetime) -> str:
    return "morning" if now.hour < 12 else "afternoon" if now.hour < 17 else "evening"
