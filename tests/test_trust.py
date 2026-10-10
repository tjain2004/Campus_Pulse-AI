from agent.trust_engine import initial_trust, sender_authority


def test_sender_authority():
    assert sender_authority("Prof. Sharma") == "official"
    assert sender_authority("Placement Coordinator") == "official"
    assert sender_authority("Rahul (CR)") == "semi"
    assert sender_authority("Aditya") == "member"
    assert sender_authority("Neha", ["neha"]) == "official"


def test_hedges_lower_trust():
    t = initial_trust("I heard the exam is postponed, not sure", "member")
    assert t["is_rumor"] and t["label"] == "unverified" and t["score"] < 30


def test_official_denial_is_not_a_rumor():
    t = initial_trust("No change. Exam as scheduled. Please ignore rumours.", "official")
    assert not t["is_rumor"] and t["label"] == "verified"


def test_forwarded_is_weak_signal_not_hearsay():
    t = initial_trust("Forwarded\nInfosys applications close Oct 12", "member")
    assert not t["is_rumor"]
