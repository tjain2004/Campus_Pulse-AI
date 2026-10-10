"""Load the synthetic demo data (4 groups + 1 PDF) and run the full pipeline.

Run:  python scripts/seed_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from agent.orchestrator import run_pipeline  # noqa: E402
from database import repository as repo  # noqa: E402
from database.connection import get_connection  # noqa: E402
from ingestion.pdf_parser import digest_pdf  # noqa: E402
from ingestion.upload import import_chat  # noqa: E402

DEMO_GROUPS = [
    ("CSE_Final_Year.txt", "CSE Final Year", "academics", []),
    ("Placement_Updates.txt", "Placement Updates", "placements", ["Placement Coordinator", "Placement Cell"]),
    ("Hackathon_Team.txt", "Hackathon Team", "hackathons", []),
    ("Fest_Updates.txt", "Fest Updates", "events", ["Fest Coordinator"]),
]


def load_demo(conn) -> dict:
    results = []
    for filename, name, category, officials in DEMO_GROUPS:
        path = config.SAMPLE_CHATS_DIR / filename
        res = import_chat(conn, path.read_text(encoding="utf-8"), name, category, officials)
        results.append(res)
    pdf = config.SAMPLE_DOCS_DIR / "SIH_Internal_Round_Guidelines.pdf"
    if pdf.exists():
        digest = digest_pdf(pdf.read_bytes())
        hack = [r for r in results if r.group_name == "Hackathon Team"]
        repo.add_document(conn, pdf.name, str(pdf), digest.summary, digest.pages,
                          hack[0].group_id if hack else None)
    stats = run_pipeline(conn)
    return {"imports": results, "stats": stats}


if __name__ == "__main__":
    c = get_connection()
    out = load_demo(c)
    for r in out["imports"]:
        print(f"{r.group_name:20s} parsed={r.parsed:3d} new={r.new:3d} duplicates_skipped={r.duplicates}")
    print(out["stats"])
