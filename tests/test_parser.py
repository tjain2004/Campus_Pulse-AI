from datetime import datetime

from ingestion.normalizer import mask_phone, normalize
from ingestion.whatsapp_parser import parse_whatsapp_text

ANDROID = """05/10/26, 9:15 am - Rahul (CR): DBMS viva tomorrow at 2 PM
in Lab 2. Bring records.
05/10/26, 9:16 am - Priya: ok
05/10/26, 9:20 am - Riya added Dev
05/10/26, 9:21 am - Dev: <Media omitted>"""

IOS = "[07/10/26, 10:42:03 PM] Placement Coordinator: Infosys applications close on October 12."


def test_android_multiline_and_system():
    msgs = parse_whatsapp_text(ANDROID)
    assert len(msgs) == 4
    assert msgs[0].sender == "Rahul (CR)"
    assert msgs[0].timestamp == datetime(2026, 10, 5, 9, 15)
    assert "Lab 2" in msgs[0].text                     # continuation line kept
    assert msgs[2].message_type == "system"
    assert msgs[3].message_type == "media"


def test_ios_format_and_pm():
    (m,) = parse_whatsapp_text(IOS)
    assert m.timestamp == datetime(2026, 10, 7, 22, 42, 3)
    assert m.sender == "Placement Coordinator"


def test_24h_and_narrow_nbsp():
    txt = "09/10/26, 13:45 - Dr. Mehta: Moved to Lab 5\n10/10/26, 1:05 pm - A: hi"
    a, b = parse_whatsapp_text(txt)
    assert a.timestamp.hour == 13 and b.timestamp.hour == 13


def test_fingerprint_dedup_and_phone_masking():
    raws = parse_whatsapp_text("07/10/26, 11:05 am - +91 98765 43210: call me on 9876543210")
    (n,) = normalize("G", raws)
    assert "3210" in n.sender and "98765" not in n.sender
    assert "9876543210" not in n.text
    assert normalize("G", raws)[0].fingerprint == n.fingerprint


def test_duplicate_import_is_skipped(conn):
    from ingestion.upload import import_chat
    first = import_chat(conn, ANDROID, "CSE")
    again = import_chat(conn, ANDROID, "CSE")
    assert first.new == 4 and again.new == 0 and again.duplicates == 4


def test_mask_keeps_dates():
    assert mask_phone("due 12/10/2026 at 11:59") == "due 12/10/2026 at 11:59"
