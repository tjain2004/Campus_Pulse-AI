import json
import time
from datetime import datetime, timezone


def _setup(tmp, monkeypatch):
    from ingestion import live_sync
    monkeypatch.setattr(live_sync, "LIVE_DIR", tmp)
    (tmp / "messages").mkdir(parents=True, exist_ok=True)
    return live_sync


def _rec(i, text, sender="Prof. Rao", group="CSE Live"):
    return {"id": f"false_123@g.us_{i}", "group_id": "123@g.us", "group_name": group,
            "timestamp": int(datetime(2026, 10, 9, 10, i).timestamp()), "sender": sender,
            "text": text, "wa_type": "chat", "kind": "text", "file": None}


def test_sync_imports_once_and_runs_pipeline(conn, monkeypatch, tmp_path):
    ls = _setup(tmp_path, monkeypatch)
    f = tmp_path / "messages" / "cse.jsonl"
    lines = [_rec(1, "DBMS quiz on Monday 10 AM in Room 101"),
             _rec(2, "ok", sender="Priya"),
             _rec(3, "Update: DBMS quiz moved to Tuesday 11 AM in Room 105")]
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\n{partial", encoding="utf-8")

    res = ls.sync_and_process(conn, now=datetime(2026, 10, 10, 15, 0))
    assert res.new == 3 and res.records == 3            # partial last line ignored
    again = ls.sync(conn)
    assert again.new == 0 and again.duplicates == 3     # WhatsApp IDs dedupe re-syncs

    ev = conn.execute("SELECT * FROM events").fetchone()
    assert ev["status"] == "changed" and ev["current_location"] == "Room 105"
    g = conn.execute("SELECT category FROM groups WHERE name='CSE Live'").fetchone()
    assert g["category"] == "academics"


def test_phone_numbers_masked(conn, monkeypatch, tmp_path):
    ls = _setup(tmp_path, monkeypatch)
    (tmp_path / "messages" / "g.jsonl").write_text(
        json.dumps(_rec(1, "call 9876543210", sender="+91 98765 43210")) + "\n", encoding="utf-8")
    ls.sync(conn)
    row = conn.execute("SELECT sender, text FROM messages").fetchone()
    assert "98765" not in row["sender"] and "9876543210" not in row["text"]


def test_status_heartbeat_and_selection(monkeypatch, tmp_path):
    ls = _setup(tmp_path, monkeypatch)
    assert ls.status()["state"] == "not_started" and not ls.status()["alive"]
    (tmp_path / "status.json").write_text(json.dumps(
        {"state": "ready", "updated": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    assert ls.status()["alive"]
    ls.save_selected_groups(["b@g.us", "a@g.us", "a@g.us"])
    assert ls.selected_groups() == ["a@g.us", "b@g.us"]
    ls.send_command("logout")
    assert json.loads((tmp_path / "command.json").read_text())["action"] == "logout"


def test_category_guess():
    from ingestion.live_sync import guess_category
    assert guess_category("TPO Placement Updates 2027") == "placements"
    assert guess_category("Team Aagaz SIH") == "hackathons"
    assert guess_category("Pulse Fest Volunteers") == "events"
    assert guess_category("Random friends") == "general"
