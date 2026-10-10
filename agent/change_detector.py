"""THE "WHAT CHANGED?" ENGINE.

A newer message can invalidate an older announcement. For each meaningful
message we:
  1. match it to an existing event (topic tokens + strong entity overlap),
  2. build a field-level diff (date/time, venue, cancellation),
  3. apply the change ONLY if the new message is an explicit update,
  4. otherwise record a CONFLICT and show both sources (latest != truth),
  5. keep original and current values plus an audit trail.

Questions and hearsay never modify events.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

from agent.textutils import jaccard
from database import repository as repo

CANCEL_RE = re.compile(r"\b(cancel+ed|called off|will not be held|stands cancel+ed)\b", re.I)


def fmt_dt(dt: Optional[datetime]) -> str:
    if not dt:
        return "—"
    return dt.strftime("%a %d %b, %I:%M %p").replace(" 0", " ")


def same_topic(a: Dict, b: Dict) -> float:
    """Return a match score (0 = no match)."""
    shared = a["strong"] & b["strong"]
    jac = jaccard(a["topic"], b["topic"])
    if len(shared) >= 2:
        return 1.0 + jac
    if shared and jac >= 0.3:
        return 0.5 + jac
    return 0.0


def _loc_key(loc: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]", "", (loc or "").lower())


def detect_changes(conn: sqlite3.Connection, items: List[Dict]) -> Dict[int, int]:
    """Create events/changes from analysed items. Returns {message_id: event_id}."""
    events: List[Dict] = []
    links: Dict[int, int] = {}

    for item in sorted(items, key=lambda i: (i["timestamp"] or datetime.min, i["id"])):
        if item["is_noise"] or item["type"] in ("chatter", "question", "resource"):
            continue
        if item["trust"]["is_rumor"]:
            continue  # hearsay is judged by Rumor Shield, never applied
        if not item["primary"] and not (item["type"] == "update" and (item["location"] or CANCEL_RE.search(item["text"]))):
            continue

        best, best_score = None, 0.0
        for ev in events:
            score = same_topic(item, ev)
            if score > best_score:
                best, best_score = ev, score

        if best is None:
            if not item["primary"]:
                continue
            kind = "deadline" if item["type"] in ("deadline", "task") else "event"
            ev_id = repo.create_event(
                conn, title=item["title"], kind=kind, category=item["category"],
                original_at=item["primary"], current_at=item["primary"],
                original_location=item["location"], current_location=item["location"],
                status="active", signature=" ".join(sorted(item["strong"])),
            )
            ev = {"id": ev_id, "title": item["title"], "topic": set(item["topic"]),
                  "strong": set(item["strong"]), "current_at": item["primary"],
                  "current_location": item["location"], "status": "active",
                  "last_message_id": item["id"], "cluster_id": item["cluster_id"], "kind": kind}
            events.append(ev)
            repo.add_event_source(conn, ev_id, item["id"], "origin")
            links[item["id"]] = ev_id
            continue

        ev = best
        links[item["id"]] = ev["id"]
        old = {"when": ev["current_at"], "location": ev["current_location"]}
        new = {}
        if item["primary"] and ev["current_at"] and item["primary"] != ev["current_at"]:
            new["when"] = item["primary"]
        if item["location"] and ev["current_location"] and _loc_key(item["location"]) != _loc_key(ev["current_location"]):
            new["location"] = item["location"]
        if item["location"] and not ev["current_location"] and item["type"] == "update":
            new["location"] = item["location"]
        cancelled = bool(CANCEL_RE.search(item["text"])) and item["type"] == "update"

        if not new and not cancelled:
            relation = "duplicate" if item["cluster_id"] == ev["cluster_id"] else "corroborates"
            repo.add_event_source(conn, ev["id"], item["id"], relation)
            continue

        old_vals = {k: (fmt_dt(old["when"]) if k == "when" else old["location"]) for k in (new or {"status": 1})}
        new_vals = {k: (fmt_dt(v) if k == "when" else v) for k, v in new.items()}
        if cancelled:
            old_vals["status"], new_vals["status"] = "scheduled", "cancelled"

        if item["type"] == "update":
            fields = []
            if "when" in new:
                ev["current_at"] = new["when"]
                fields.append("date/time")
            if "location" in new:
                ev["current_location"] = new["location"]
                fields.append("venue")
            ev["status"] = "cancelled" if cancelled else "changed"
            if cancelled:
                fields.append("status")
            explanation = (f"{item['sender'] or 'Someone'} in {item['group']} explicitly updated the "
                           f"{' and '.join(fields)} of an earlier announcement.")
            repo.update_event(conn, ev["id"], current_at=ev["current_at"],
                              current_location=ev["current_location"], status=ev["status"])
            repo.add_change_log(conn, ev["id"], "change", old_vals, new_vals,
                                ev["last_message_id"], item["id"], explanation)
            repo.add_event_source(conn, ev["id"], item["id"], "updates")
            ev["last_message_id"] = item["id"]
        else:
            explanation = ("Two messages give different details but the newer one does not say it is a "
                           "change. Both are shown — please verify with the organiser.")
            ev["status"] = "conflict"
            repo.update_event(conn, ev["id"], status="conflict")
            repo.add_change_log(conn, ev["id"], "conflict", old_vals, new_vals,
                                ev["last_message_id"], item["id"], explanation)
            repo.add_event_source(conn, ev["id"], item["id"], "conflicts")
    conn.commit()
    return links
