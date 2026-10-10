"""Ask Campus AI: chat over all groups + documents, answers with citations."""
from __future__ import annotations

import streamlit as st

from agent import llm
from rag.answer import ask
from rag.citations import label

EXAMPLES = [
    "What do we need to submit for SIH, and when is it due?",
    "Where is the fest briefing?",
    "When is the DBMS assignment due?",
    "Is the OS mid-sem postponed?",
    "How many members are allowed in an SIH team?",
]


def _render_answer(ans) -> None:
    st.markdown(ans.answer)
    for c in ans.conflicts:
        st.warning(c, icon="⚠️")
    if ans.citations:
        with st.expander(f"Sources ({len(ans.citations)})"):
            for i, c in enumerate(ans.citations, start=1):
                st.markdown(f"**[{i}] {label(c)}**")
                st.caption(c.excerpt)


def render(conn, now) -> None:
    st.title("Ask Campus AI")
    engine = "LLM + retrieval" if llm.available() else "retrieval (no API key — add one in .env for richer answers)"
    st.caption(f"Answers come only from your imported messages and documents, with sources. Engine: {engine}.")

    st.session_state.setdefault("chat", [])
    cols = st.columns(len(EXAMPLES))
    clicked = None
    for col, ex in zip(cols, EXAMPLES):
        if col.button(ex, use_container_width=True):
            clicked = ex

    for turn in st.session_state["chat"]:
        with st.chat_message(turn["role"]):
            if turn["role"] == "user":
                st.markdown(turn["content"])
            else:
                _render_answer(turn["content"])

    question = st.chat_input("Ask about deadlines, venues, requirements…") or clicked
    if question:
        st.session_state["chat"].append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Searching your groups…"):
                ans = ask(conn, question)
            _render_answer(ans)
        st.session_state["chat"].append({"role": "assistant", "content": ans})
    if st.session_state["chat"] and st.button("Clear chat"):
        st.session_state["chat"] = []
        st.rerun()
