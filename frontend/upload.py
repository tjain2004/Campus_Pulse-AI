"""Import page: WhatsApp exports, PDFs, demo data, privacy controls."""
from __future__ import annotations

import streamlit as st

import config
from agent.orchestrator import run_pipeline
from database import repository as repo
from frontend.components import section
from ingestion.pdf_parser import digest_pdf
from ingestion.upload import UploadError, decode_upload, guess_group_name, import_chat

CATEGORIES = ["academics", "placements", "hackathons", "events", "resources", "faculty", "general"]


def _show_stats(stats) -> None:
    st.success(
        f"AI pipeline done — {stats.messages} messages · {stats.noise} noise filtered · "
        f"{stats.events} events · {stats.changes} changes · {stats.conflicts} conflicts · "
        f"{stats.rumors} rumors checked · {stats.tasks} tasks"
        + (f" · {stats.llm_used} analysed by LLM" if stats.llm_used else "")
    )


def render(conn, now) -> None:
    st.title("Import your groups")
    st.caption("In WhatsApp: open the group → ⋮ → More → **Export chat** → *Without media*. "
               "Upload the .txt here. Only upload chats you're allowed to process.")

    with st.container(border=True):
        section("1 · WhatsApp chat exports")
        files = st.file_uploader("Chat exports (.txt) — you can select several", type=["txt"],
                                 accept_multiple_files=True)
        redact = st.checkbox("Mask phone numbers (recommended)", value=True)
        configs = []
        for i, f in enumerate(files or []):
            c1, c2, c3 = st.columns([2, 1, 2])
            name = c1.text_input("Group name", value=guess_group_name(f.name), key=f"name_{i}")
            cat = c2.selectbox("Type", CATEGORIES, index=6, key=f"cat_{i}")
            off = c3.text_input("Official senders (comma-separated, optional)", key=f"off_{i}",
                                placeholder="e.g. Placement Coordinator, Prof. Rao")
            configs.append((f, name, cat, off))
        if configs and st.button("Import & analyse", type="primary"):
            for f, name, cat, off in configs:
                try:
                    content = decode_upload(f.getvalue(), f.name)
                    officials = [s.strip() for s in off.split(",") if s.strip()]
                    res = import_chat(conn, content, name.strip() or guess_group_name(f.name), cat,
                                      officials, redact_phones=redact)
                    st.write(f"✅ **{res.group_name}** — {res.parsed} parsed, {res.new} new, "
                             f"{res.duplicates} already imported (skipped)")
                except UploadError as exc:
                    st.error(f"{f.name}: {exc}")
            with st.spinner("Running the AI pipeline…"):
                _show_stats(run_pipeline(conn, now=now))

    with st.container(border=True):
        section("2 · PDFs & circulars (optional)")
        pdf = st.file_uploader("Guidelines, circulars, brochures (.pdf)", type=["pdf"])
        groups = repo.list_groups(conn)
        gopts = {"(none)": None, **{g["name"]: g["id"] for g in groups}}
        gsel = st.selectbox("Shared in group", list(gopts))
        if pdf and st.button("Import PDF"):
            data = pdf.getvalue()
            if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
                st.error("PDF is too large.")
            else:
                path = config.UPLOAD_DIR / pdf.name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                digest = digest_pdf(data)
                repo.add_document(conn, pdf.name, str(path), digest.summary, digest.pages, gopts[gsel])
                st.success(f"Imported {pdf.name} — {len(digest.pages)} searchable chunks.")
                st.markdown("**Key points**\n\n" + digest.summary)
                for w in digest.warnings:
                    st.warning(w)

    with st.container(border=True):
        section("3 · Demo & privacy")
        c1, c2, c3 = st.columns(3)
        if c1.button("Load demo data (4 groups + PDF)"):
            from scripts.seed_demo import load_demo
            with st.spinner("Importing demo groups and running the pipeline…"):
                out = load_demo(conn)
            _show_stats(out["stats"])
        if c2.button("Re-run AI pipeline"):
            with st.spinner("Re-analysing all messages…"):
                _show_stats(run_pipeline(conn, now=now))
        if c3.button("🗑 Delete ALL imported data"):
            st.session_state["confirm_delete"] = True
        if st.session_state.get("confirm_delete"):
            st.warning("This permanently deletes all groups, messages, documents and tasks.")
            a, b = st.columns(2)
            if a.button("Yes, delete everything", type="primary"):
                repo.delete_all_data(conn)
                for d in repo.list_documents(conn):
                    repo.delete_document(conn, d["id"])
                st.session_state["confirm_delete"] = False
                st.success("All data deleted.")
                st.rerun()
            if b.button("Cancel"):
                st.session_state["confirm_delete"] = False
                st.rerun()

    if groups:
        section("Imported groups")
        for g in groups:
            c1, c2, c3 = st.columns([3, 1, 1])
            c1.write(f"**{g['name']}** · {g['category']}")
            c2.write(f"{g['message_count']} messages")
            if c3.button("Delete", key=f"del_{g['id']}"):
                repo.delete_group(conn, g["id"])
                run_pipeline(conn, now=now)
                st.rerun()
