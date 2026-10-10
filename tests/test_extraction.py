from datetime import datetime

from agent.classifier import classify_category, is_noise
from agent.extractor import build_title, extract
from agent.personalizer import assess

REF = datetime(2026, 10, 8, 18, 30)  # Thursday


def test_relative_weekday_deadline():
    ex = extract("SIH PPT submission by Sunday 11:59 PM", REF)
    assert ex.primary == datetime(2026, 10, 11, 23, 59)
    assert ex.is_deadline


def test_explicit_dates_and_default_deadline_time():
    assert extract("applications close on October 12, 11:59 PM", REF).primary == datetime(2026, 10, 12, 23, 59)
    assert extract("assignment due 16 Oct", REF).primary == datetime(2026, 10, 16, 23, 59)
    assert extract("submit by tomorrow", REF).primary == datetime(2026, 10, 9, 23, 59)


def test_update_prefers_new_value_and_location():
    ex = extract("Briefing moved from Tuesday to Wednesday 5 PM in the Main Auditorium", REF, prefer_last=True)
    assert ex.primary == datetime(2026, 10, 14, 17, 0)
    assert ex.location == "Main Auditorium"


def test_locations():
    assert extract("Viva in Room 204", REF).location == "Room 204"
    assert extract("Exam at 10 AM in LT-2", REF).location == "LT-2"


def test_noise_filter():
    for t in ["ok", "Thanks!", "👍👍", "really??", "no idea"]:
        assert is_noise(t)
    assert not is_noise("Submit the PPT by Sunday")


def test_category():
    assert classify_category("Infosys internship applications open")[0] == "placements"
    assert classify_category("SIH internal round PPT")[0] == "hackathons"


def test_title():
    assert build_title("📢 Infosys Summer Internship 2027 — applications close soon") == "Infosys Summer Internship 2027"
    assert build_title("There is no change. OS mid-sem will be held as scheduled") == "OS mid-sem"


def test_personalization_three_outcomes():
    p = {"year": 4, "grad_year": 2027, "branch": "CSE - Data Science", "interests": ["placements"]}
    assert assess("Workshop only for 2nd year students", "events", p)[0] == "not_relevant"
    assert assess("Open to 2027 batch, CSE/IT", "placements", p)[0] == "relevant"
    assert assess("Amazon drive for 2028 batch", "placements", p)[0] == "not_relevant"
    assert assess("Library closes early today", "general", p)[0] == "unknown"
