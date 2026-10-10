"""Shared UI pieces: theme CSS, badges, cards, source references."""
from __future__ import annotations

import html
from datetime import datetime
from typing import Optional

import streamlit as st

CSS = """
<style>
:root {
  --cp-ink: #17211f; --cp-muted: #5d6965; --cp-line: #e2e4dc; --cp-card: #ffffff;
  --cp-teal: #0f766e; --cp-teal-soft: #e3f2ef; --cp-red: #b42318; --cp-red-soft: #fdecea;
  --cp-amber: #b54708; --cp-amber-soft: #fef3e2; --cp-blue: #1d4ed8; --cp-blue-soft: #e8eefc;
  --cp-green: #067647; --cp-green-soft: #e6f4ec; --cp-grey-soft: #f0f1ec;
}
.block-container { padding-top: 1.6rem; max-width: 1250px; }
h1, h2, h3 { letter-spacing: -0.01em; }
.cp-hero { display:flex; align-items:baseline; gap:.6rem; margin-bottom:.2rem; }
.cp-hero h1 { margin:0; font-size:1.9rem; }
.cp-sub { color: var(--cp-muted); margin-bottom: 1.1rem; }
.cp-card { background: var(--cp-card); border:1px solid var(--cp-line); border-left:5px solid var(--cp-line);
  border-radius: 12px; padding: .85rem 1rem .75rem; margin-bottom: .7rem; }
.cp-card.urgent { border-left-color: var(--cp-red); }
.cp-card.upcoming { border-left-color: var(--cp-amber); }
.cp-card.updated { border-left-color: var(--cp-blue); }
.cp-card.fyi { border-left-color: #a3aca8; }
.cp-card.ok { border-left-color: var(--cp-green); }
.cp-title { font-weight: 650; font-size: 1.02rem; color: var(--cp-ink); margin-bottom: .15rem; }
.cp-meta { color: var(--cp-muted); font-size: .84rem; }
.cp-why { font-size: .84rem; color: var(--cp-ink); margin-top: .35rem; }
.cp-why b { color: var(--cp-muted); font-weight: 600; }
.cp-quote { background: var(--cp-grey-soft); border-radius: 8px; padding: .45rem .65rem; margin-top: .45rem;
  font-size: .86rem; color: #2f3a37; white-space: pre-wrap; }
.cp-badge { display:inline-block; font-size:.72rem; font-weight:650; padding:.1rem .5rem; border-radius:999px;
  margin-right:.3rem; vertical-align: middle; letter-spacing: .01em; }
.b-red { background: var(--cp-red-soft); color: var(--cp-red); }
.b-amber { background: var(--cp-amber-soft); color: var(--cp-amber); }
.b-blue { background: var(--cp-blue-soft); color: var(--cp-blue); }
.b-green { background: var(--cp-green-soft); color: var(--cp-green); }
.b-teal { background: var(--cp-teal-soft); color: var(--cp-teal); }
.b-grey { background: var(--cp-grey-soft); color: var(--cp-muted); }
.cp-diff { display:grid; grid-template-columns: 1fr auto 1fr; gap:.6rem; align-items:center; margin:.5rem 0; }
.cp-old { background: var(--cp-grey-soft); border-radius:8px; padding:.5rem .7rem; color: var(--cp-muted);
  text-decoration: line-through; text-decoration-color: rgba(180,35,24,.5); }
.cp-new { background: var(--cp-blue-soft); border-radius:8px; padding:.5rem .7rem; color: var(--cp-blue); font-weight:600; }
.cp-arrow { color: var(--cp-muted); font-size: 1.2rem; }
.cp-section { font-size:.78rem; font-weight:700; letter-spacing:.08em; text-transform:uppercase;
  color: var(--cp-muted); margin: 1.1rem 0 .5rem; }
.cp-meter { height: 8px; border-radius: 999px; background: var(--cp-grey-soft); overflow:hidden; margin-top:.4rem; }
.cp-meter > div { height:100%; border-radius:999px; }
.cp-empty { color: var(--cp-muted); padding: .8rem 0; }
@media (max-width: 640px) { .cp-diff { grid-template-columns: 1fr; } .cp-arrow { display:none; } }
</style>
"""

CATEGORY_LABEL = {"academics": "Academics", "placements": "Placements", "hackathons": "Hackathons",
                  "events": "Events", "resources": "Resources", "faculty": "Faculty", "general": "General"}


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def esc(text: Optional[str]) -> str:
    return html.escape(text or "")


def badge(text: str, tone: str = "grey") -> str:
    return f'<span class="cp-badge b-{tone}">{esc(text)}</span>'


def trust_badge(label: Optional[str], score: Optional[int] = None) -> str:
    if not label:
        return ""
    tone, text = {
        "verified": ("green", "✓ Verified"),
        "unconfirmed": ("grey", "Unconfirmed"),
        "unverified": ("amber", "Unverified"),
        "contradicted": ("red", "✕ Contradicted"),
    }.get(label, ("grey", label))
    return badge(f"{text}{f' · {score}' if score is not None else ''}", tone)


def fmt_ts(ts) -> str:
    if not ts:
        return "time unknown"
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except ValueError:
            return ts
    return ts.strftime("%d %b, %I:%M %p").lstrip("0")


def relative(when: Optional[datetime], now: datetime) -> str:
    if not when:
        return ""
    delta = when - now
    hours = delta.total_seconds() / 3600
    if hours < 0:
        return "passed"
    if hours < 1:
        return "within the hour"
    if hours < 24:
        return f"in {int(hours)}h"
    days = (when.date() - now.date()).days
    return "tomorrow" if days == 1 else f"in {days} days"


def card(title: str, *, band: str = "fyi", badges: str = "", meta: str = "", why: str = "",
         quote: str = "", extra_html: str = "", why_label: str = "Why it matters") -> None:
    parts = [f'<div class="cp-card {band}">',
             f'<div>{badges}</div>' if badges else "",
             f'<div class="cp-title">{esc(title)}</div>',
             f'<div class="cp-meta">{meta}</div>' if meta else "",
             f'<div class="cp-why"><b>{esc(why_label)}:</b> {esc(why)}</div>' if why else "",
             f'<div class="cp-quote">{esc(quote)}</div>' if quote else "",
             extra_html, "</div>"]
    st.markdown("".join(parts), unsafe_allow_html=True)


def source_line(group: Optional[str], sender: Optional[str], ts) -> str:
    return f"📍 {esc(group)} · {esc(sender or 'unknown sender')} · {esc(fmt_ts(ts))}"


def section(label: str) -> None:
    st.markdown(f'<div class="cp-section">{esc(label)}</div>', unsafe_allow_html=True)


def empty(text: str) -> None:
    st.markdown(f'<div class="cp-empty">{esc(text)}</div>', unsafe_allow_html=True)


def meter(score: int, tone: str) -> str:
    color = {"green": "#067647", "amber": "#b54708", "red": "#b42318", "grey": "#8a948f"}[tone]
    return f'<div class="cp-meter"><div style="width:{max(4, min(100, score))}%;background:{color}"></div></div>'
