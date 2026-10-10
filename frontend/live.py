"""Live WhatsApp: link your number (QR), pick groups, auto-sync."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from frontend.components import section
from ingestion import live_sync

STATE_TEXT = {
    "not_started": ("⚪", "Bridge not running"),
    "starting": ("🟡", "Starting WhatsApp Web…"),
    "qr": ("🟡", "Waiting for you to scan the QR code"),
    "authenticated": ("🟡", "Logged in — loading your chats"),
    "loading": ("🟡", "Loading chats"),
    "ready": ("🟢", "Connected"),
    "disconnected": ("🔴", "Disconnected"),
    "auth_failure": ("🔴", "Login failed — delete whatsapp_bridge/.wwebjs_auth and scan again"),
    "logged_out": ("⚪", "Unlinked"),
    "stopped": ("⚪", "Bridge stopped"),
}


def _sync_block(conn, now) -> None:
    res = live_sync.sync_and_process(conn, now=now)
    if res.new or res.documents:
        st.success(f"Synced {res.new} new message(s)"
                   + (f" and {res.documents} PDF(s)" if res.documents else "")
                   + f" from {res.groups} group(s). Your brief is updated.")
    else:
        st.caption(f"Up to date · {res.records} messages received so far · last checked {datetime.now():%H:%M:%S}")


def render(conn, now) -> None:
    st.title("📲 Live WhatsApp")
    st.caption("Link your WhatsApp number like WhatsApp Web, choose which groups CampusPulse may read, "
               "and new messages flow into your brief automatically.")

    st.warning(
        "**Read before linking.** This uses an *unofficial* WhatsApp Web connection (whatsapp-web.js). "
        "WhatsApp's official API cannot read existing groups, and automating WhatsApp Web breaks its Terms of "
        "Service — the number could be restricted. For a demo, use a spare number that's in your groups. "
        "The bridge is **read-only**: it never sends messages and only reads the groups you tick below.",
        icon="⚠️",
    )

    stt = live_sync.status()
    state = stt.get("state", "not_started")
    if not stt["alive"] and state not in ("logged_out", "auth_failure"):
        state = "not_started" if state == "not_started" else "stopped"
    icon, text = STATE_TEXT.get(state, ("⚪", state))

    with st.container(border=True):
        section("1 · Start the bridge on your computer")
        c1, c2 = st.columns([3, 2])
        with c1:
            st.markdown(f"### {icon} {text}")
            if stt.get("detail") and stt["alive"]:
                st.caption(stt["detail"])
            acct = stt.get("account") or {}
            if state == "ready" and acct:
                st.markdown(f"Linked as **{acct.get('name') or 'your account'}** · number ending "
                            f"**{(acct.get('number') or '')[-4:]}**")
        with c2:
            st.code("cd whatsapp_bridge\nnpm install      # first time only\nnpm start", language="bash")
            st.caption("Needs Node.js 18+ (nodejs.org). Keep that terminal open while you use CampusPulse.")
        if st.button("↻ Refresh status"):
            st.rerun()

    if state == "qr" and stt.get("qr_path"):
        with st.container(border=True):
            section("2 · Scan to link your number")
            c1, c2 = st.columns([1, 2])
            c1.image(stt["qr_path"], width=260)
            c2.markdown(
                "On your phone open **WhatsApp → Settings (or ⋮) → Linked devices → Link a device**, "
                "then scan this code.\n\nThe same QR is also printed in the bridge terminal. It refreshes every "
                "~20 seconds — press **Refresh status** if it expired."
            )

    if state != "ready":
        st.info("Once connected, your groups will appear here so you can choose which ones to sync.")
        return

    # --------------------------------------------------------- choose groups
    with st.container(border=True):
        section("3 · Choose groups CampusPulse may read")
        groups = live_sync.available_groups()
        if not groups:
            st.caption("Loading your groups…")
            if st.button("Fetch group list"):
                live_sync.send_command("refresh_groups")
            return
        by_id = {g["id"]: g for g in groups}
        current = [g for g in live_sync.selected_groups() if g in by_id]
        picked = st.multiselect(
            "Groups", list(by_id), default=current,
            format_func=lambda gid: f"{by_id[gid]['name']}  ·  {by_id[gid]['participants']} members",
            placeholder="e.g. your class, placement and hackathon groups",
        )
        c1, c2 = st.columns([1, 3])
        if c1.button("Save selection", type="primary"):
            live_sync.save_selected_groups(picked)
            st.success("Saved. The bridge is importing recent history from newly selected groups "
                       "(up to 300 messages each) — sync below in a few seconds.")
        c2.caption("Deselecting a group stops new messages; delete already-imported data from the Import page.")

    # ------------------------------------------------------------------ sync
    with st.container(border=True):
        section("4 · Sync into CampusPulse")
        auto = st.toggle("Auto-sync every 20 seconds", value=True)
        if auto and hasattr(st, "fragment"):
            st.fragment(run_every=20)(lambda: _sync_block(conn, now))()
        else:
            if st.button("Sync now"):
                _sync_block(conn, now)

    with st.expander("Unlink this computer"):
        st.caption("Logs the bridge out of WhatsApp (same as removing it under Linked devices on your phone). "
                   "Imported messages stay until you delete them on the Import page.")
        if st.button("Unlink WhatsApp"):
            live_sync.send_command("logout")
            st.success("Unlink requested — the bridge will log out within a few seconds.")
