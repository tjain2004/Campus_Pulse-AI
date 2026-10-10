"""Generate data/sample_docs/SIH_Internal_Round_Guidelines.pdf (synthetic demo PDF).

Run:  python scripts/make_sample_pdf.py     (needs: pip install reportlab)
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import getSampleStyleSheet  # noqa: E402
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer  # noqa: E402

import config  # noqa: E402

PAGES = [
    ("SIH Internal Round 2026 - Guidelines", [
        "These guidelines apply to all teams taking part in the institute-level internal round of the "
        "Smart India Hackathon 2026 (synthetic document for the CampusPulse AI demo).",
        "The internal round selects the teams that will be nominated to the national round.",
    ]),
    ("1. Team composition", [
        "Each team must have exactly 6 members, including at least one female member.",
        "All members must be from the same institute. Inter-college teams are not allowed.",
        "Every team must have one faculty mentor registered on the portal.",
    ]),
    ("2. Idea presentation (PPT)", [
        "The PPT must follow the official SIH template. Submissions in any other format will be disqualified.",
        "The deck should have a maximum of 6 slides: problem, solution, architecture, tech stack, impact, team.",
        "Submit the PPT as a PDF file through the internal round form before the deadline announced by the SPOC.",
    ]),
    ("3. Demo round and evaluation", [
        "Shortlisted teams present a working prototype in the offline demo round.",
        "Teams must carry their own laptops and chargers to the demo venue.",
        "Evaluation criteria: novelty 30%, feasibility 25%, technical depth 25%, presentation 20%.",
    ]),
]


def main() -> None:
    out = config.SAMPLE_DOCS_DIR / "SIH_Internal_Round_Guidelines.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    story = []
    for i, (heading, paras) in enumerate(PAGES):
        story.append(Paragraph(heading, styles["Title"] if i == 0 else styles["Heading1"]))
        story.append(Spacer(1, 12))
        for p in paras:
            story.append(Paragraph(p, styles["BodyText"]))
            story.append(Spacer(1, 8))
        if i < len(PAGES) - 1:
            story.append(PageBreak())
    SimpleDocTemplate(str(out), pagesize=A4, title="SIH Internal Round Guidelines").build(story)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
