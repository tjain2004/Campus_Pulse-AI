"""Student profile for the 'Is this for me?' engine."""
from __future__ import annotations

import streamlit as st

from agent.orchestrator import run_pipeline
from database import repository as repo


def _split(text: str):
    return [x.strip() for x in text.split(",") if x.strip()]


def render(conn, now) -> None:
    st.title("Your profile")
    st.caption("Used only to rank and label announcements (e.g. “only for 2nd year”). Items that don't match are "
               "labelled and kept visible — never silently hidden.")
    p = repo.get_profile(conn)
    with st.form("profile"):
        name = st.text_input("Name", p.get("name", ""))
        c1, c2, c3 = st.columns(3)
        branch = c1.text_input("Branch", p.get("branch", ""), help="e.g. CSE - Data Science, ECE, IT")
        year = c2.number_input("Year of study", 1, 6, int(p.get("year") or 1))
        grad = c3.number_input("Graduation year (batch)", 2020, 2040, int(p.get("grad_year") or 2027))
        interests = st.text_input("Interests (comma-separated)", ", ".join(p.get("interests", [])),
                                  help="placements, hackathons, events, academics, AI …")
        skills = st.text_input("Skills", ", ".join(p.get("skills", [])))
        teams = st.text_input("Teams / clubs", ", ".join(p.get("teams", [])), help="e.g. Team Aagaz")
        if st.form_submit_button("Save & re-rank", type="primary"):
            new = {"name": name or "Student", "branch": branch, "year": int(year), "grad_year": int(grad),
                   "interests": _split(interests), "skills": _split(skills), "teams": _split(teams)}
            repo.save_profile(conn, new)
            with st.spinner("Re-ranking your feed…"):
                run_pipeline(conn, profile=new, now=now)
            st.success("Profile saved — your brief is re-ranked.")
