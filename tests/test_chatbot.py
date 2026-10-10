from datetime import datetime

NOW = datetime(2026, 10, 10, 15, 22)


def _ask(conn, msg):
    from backend import chatbot
    return chatbot.reply(conn, msg, NOW)


def test_normalise_and_window():
    from backend.chatbot import extract_window, normalise
    assert normalise("Wat's due tmrw?") == "what's due tomorrow?"
    s, e, label = extract_window("due on monday", NOW)
    assert label.startswith("Monday") and s == datetime(2026, 10, 12)


def test_deadline_intents(demo):
    r = _ask(demo, "what's due tmrw?")
    assert r["intent"] == "deadlines" and "SIH" in r["reply"] and "1 deadline**" in r["reply"]
    r = _ask(demo, "placement deadlines")
    assert r["entities"]["category"] == "placements" and "Infosys" in r["reply"]
    assert "Amazon" not in r["reply"]                       # not for a 4th-year student
    assert "Fest briefing" in _ask(demo, "what's on wednesday")["reply"]


def test_changes_rumours_tasks(demo):
    assert "Main Auditorium" in _ask(demo, "any changes?")["reply"]
    assert "conflict" in _ask(demo, "any conflicts").get("reply")
    r = _ask(demo, "any rumours?")
    assert "Contradicted" in r["reply"] and "Prof. Sharma" in r["reply"]
    assert "Submit SIH" in _ask(demo, "my tasks")["reply"]
    r = _ask(demo, "mark sih ppt done")
    assert r["intent"] == "mark_done" and "done" in r["reply"]
    assert "Submit SIH" not in _ask(demo, "my tasks")["reply"]


def test_fallback_search_and_unknown(demo):
    assert "Main Auditorium" in _ask(demo, "where is the fest briefing?")["reply"]
    assert _ask(demo, "qwerty zxcv")["reply"].startswith("I couldn't find")
    assert _ask(demo, "hi")["intent"] == "greet"
