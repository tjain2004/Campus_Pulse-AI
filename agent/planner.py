"""Priority engine, Today's Brief and Crunch Radar.

    P = 0.35*U + 0.30*D + 0.20*R + 0.15*C      (each factor 0-100)

U urgency (time to a verified deadline), D importance of the action,
R relevance to the profile, C confidence of extraction. A hard rule keeps
verified deadlines within 48h at the top even if the profile is incomplete.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import config
from agent.change_detector import fmt_dt
from database import repository as repo

TYPE_IMPORTANCE = {"deadline": 90, "task": 80, "update": 78, "announcement": 55,
                   "resource": 40, "question": 25, "chatter": 0}
RELEVANCE_SCORE = {"relevant": 100, "unknown": 60, "not_relevant": 10}
# rough effort estimates (days) for Smart Start dates
EFFORT_DAYS = {"ppt": 3, "presentation": 3, "project": 4, "report": 3, "assignment": 2, "resume": 1,
               "application": 1, "apply": 1, "registration": 1, "register": 1, "midsem": 4, "exam": 4,
               "quiz": 1, "viva": 2, "submission": 2}


def urgency(when: Optional[datetime], now: datetime, mtype: str) -> float:
    if when is None:
        return 60 if mtype == "update" else 10
    hours = (when - now).total_seconds() / 3600
    if hours < 0:
        return 0
    if hours <= 24:
        return 100
    if hours <= 48:
        return 85
    if hours <= 72:
        return 70
    if hours <= 24 * 7:
        return 50
    return 20


def score(item: Dict, now: datetime) -> Dict:
    when = item.get("event_current_at") or item.get("primary")
    w = config.PRIORITY_WEIGHTS
    U = urgency(when, now, item["type"])
    D = TYPE_IMPORTANCE.get(item["type"], 40)
    R = RELEVANCE_SCORE.get(item.get("relevance", "unknown"), 60)
    C = 100 * float(item.get("confidence", 0.5))
    P = w["U"] * U + w["D"] * D + w["R"] * R + w["C"] * C
    reasons = []
    hard = (item["type"] in ("deadline", "task") and when and 0 <= (when - now).total_seconds() <= 48 * 3600
            and item.get("relevance") != "not_relevant" and not item.get("needs_verification"))
    if hard:
        P = max(P, 90)
        reasons.append("verified deadline within 48 hours")
    elif U >= 70:
        reasons.append("coming up soon")
    if item["type"] == "update":
        reasons.append("a newer message changes an earlier announcement")
    if item.get("relevance") == "relevant":
        reasons.append(item.get("relevance_reason", "matches your profile").lower())
    if item.get("trust", {}).get("label") == "verified":
        reasons.append("from an official source")
    if item["is_noise"]:
        P = 0
    if item.get("trust", {}).get("is_rumor"):
        P = min(P, 30)
    return {"priority": round(P, 1), "priority_reason": "; ".join(reasons) or "general update"}


def _parse(ts: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(ts) if ts else None


def build_brief(conn: sqlite3.Connection, now: Optional[datetime] = None, lookback_days: int = 7) -> Dict[str, List[Dict]]:
    """Return {'top': [...], 'not_for_you': [...], 'rumors': n, 'conflicts': n}."""
    now = now or config.reference_now()
    rows = sorted(repo.analyzed_feed(conn), key=lambda r: (-r["priority"], -(r["trust_score"] or 0)))
    events = {e["id"]: e for e in repo.list_events(conn)}
    msg_event = {r["message_id"]: r["event_id"] for r in conn.execute("SELECT * FROM event_sources")}

    seen_clusters, seen_events = set(), set()
    top, filtered = [], []
    rumors = 0
    for r in rows:
        if r["is_noise"] or r["type"] in ("chatter", "question", "resource"):
            continue
        if r["trust_label"] == "contradicted" or (
                r["trust_label"] == "unverified" and "Hearsay" in (r["trust_reasons"] or "")):
            rumors += 1
            continue
        ts = _parse(r["timestamp"])
        ev = events.get(msg_event.get(r["id"])) if msg_event.get(r["id"]) else None
        when = _parse(ev["current_at"]) if ev else _parse(r["deadline"] or r["event_at"])
        if when and when < now - timedelta(hours=2):
            continue  # already over
        if not when and ts and ts < now - timedelta(days=lookback_days):
            continue
        if not when and not ev and (r["trust_score"] or 0) < 65:
            continue  # undated chatter from members stays in the group view
        if ev:
            if ev["id"] in seen_events:
                continue
            seen_events.add(ev["id"])
        if r["cluster_id"] in seen_clusters:
            continue
        seen_clusters.add(r["cluster_id"])

        src = r
        if ev:
            # show the newest authoritative source of the event (e.g. the update, not the old post)
            srcs = repo.event_sources(conn, ev["id"])
            pick = [s for s in srcs if s["relation_type"] == "updates"] or \
                   [s for s in srcs if s["relation_type"] == "origin"]
            if pick:
                src = pick[-1]
        card = {
            "message_id": src["id"],
            "title": ev["title"] if ev else (r["topic"] or r["summary"]),
            "summary": r["summary"],
            "text": src["text"],
            "group": src["group_name"],
            "also_in": [g for g in repo.cluster_groups(conn, r["cluster_id"]) if g != src["group_name"]],
            "sender": src["sender"],
            "timestamp": src["timestamp"],
            "category": r["category"],
            "type": r["type"],
            "when": when,
            "when_label": fmt_dt(when) if when else None,
            "location": (ev["current_location"] if ev else r["location"]),
            "status": ev["status"] if ev else None,
            "relevance": r["relevance"],
            "relevance_reason": r["relevance_reason"],
            "trust_label": r["trust_label"],
            "trust_score": r["trust_score"],
            "priority": r["priority"],
            "reason": r["priority_reason"],
            "needs_verification": bool(r["needs_verification"]),
        }
        if ev and ev["status"] in ("changed", "conflict", "cancelled"):
            card["priority"] = max(card["priority"], 80)
            card["reason"] = ("details changed — see What Changed?" if ev["status"] == "changed"
                              else "conflicting information — verify" if ev["status"] == "conflict"
                              else "event cancelled")
        (filtered if r["relevance"] == "not_relevant" else top).append(card)

    top.sort(key=lambda c: (-c["priority"], c["when"] or datetime.max))
    conflicts = sum(1 for e in events.values() if e["status"] == "conflict")
    return {"top": top, "not_for_you": filtered, "rumors": rumors, "conflicts": conflicts}


def priority_band(p: float) -> str:
    return "urgent" if p >= 80 else "upcoming" if p >= 55 else "fyi"


def crunch_radar(conn: sqlite3.Connection, now: Optional[datetime] = None, days: int = 14) -> Dict:
    """Workload forecast per day + Smart Start dates for each pending deadline."""
    now = now or config.reference_now()
    start = datetime(now.year, now.month, now.day)
    load = defaultdict(float)
    items = defaultdict(list)
    plans = []
    for t in repo.list_tasks(conn):
        if t["status"] == "done" or not t["deadline"]:
            continue
        due = datetime.fromisoformat(t["deadline"])
        if due < now or due > start + timedelta(days=days):
            continue
        low = t["title"].lower()
        effort = max([d for k, d in EFFORT_DAYS.items() if k in low] or [1])
        # spread effort across the days before the deadline
        for d in range(effort):
            day = (due - timedelta(days=d)).date()
            if day >= start.date():
                load[day] += 1.0 / effort * (1.5 if d == 0 else 1.0)
        items[due.date()].append(t["title"])
        plans.append({"task": t["title"], "due": due, "effort_days": effort,
                      "start_by": max(start, due - timedelta(days=effort)), "group": t["group_name"]})
    for e in repo.list_events(conn):
        if e["kind"] != "event" or not e["current_at"] or e["status"] == "cancelled":
            continue
        when = datetime.fromisoformat(e["current_at"])
        if start <= when <= start + timedelta(days=days):
            load[when.date()] += 0.5
            items[when.date()].append(e["title"])
    series = []
    for i in range(days):
        d = (start + timedelta(days=i)).date()
        series.append({"date": d, "load": round(load.get(d, 0), 2), "items": items.get(d, [])})
    peak = max(series, key=lambda s: s["load"]) if series else None
    crunch_days = [s for s in series if s["load"] >= 2]
    plans.sort(key=lambda p: p["start_by"])
    return {"series": series, "peak": peak, "crunch_days": crunch_days, "plans": plans}


def trust_reasons(row) -> List[str]:
    try:
        return json.loads(row["trust_reasons"] or "[]")
    except (TypeError, ValueError):
        return []
