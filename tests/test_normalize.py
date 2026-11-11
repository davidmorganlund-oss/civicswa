"""Checks the three connectors against records shaped like the real feeds."""
import sys
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import build  # noqa: E402

TZ = ZoneInfo("America/Los_Angeles")


def test_legistar():
    src = {"id": "olympia", "name": "City of Olympia", "area": "Olympia"}
    rows = [{"EventId": 7068, "EventBodyName": "Planning Commission", "EventDate": "2026-11-16T00:00:00",
             "EventTime": "6:30 PM", "EventLocation": "Online Only",
             "EventAgendaFile": "https://example.org/a.pdf", "EventInSiteURL": "https://example.org/m",
             "EventComment": None},
            {"EventId": 1, "EventBodyName": "City Council", "EventDate": "2026-11-17T00:00:00",
             "EventTime": None, "EventLocation": None, "EventComment": "Meeting cancelled"}]
    a, b = build.normalize_legistar(src, rows, TZ)
    assert a["start"] == "2026-11-16T18:30:00-08:00" and a["category"] == "council"
    assert a["agenda_url"].endswith("a.pdf") and not a["cancelled"]
    assert b["all_day"] and b["cancelled"]


def test_civicclerk_times_are_local():
    src = {"id": "lacey", "name": "City of Lacey", "area": "Lacey", "tenant": "laceywa"}
    rows = [{"id": 1580, "eventName": "City Council Meeting ", "startDateTime": "2026-12-01T18:00:00Z",
             "eventLocation": {"address1": "Lacey City Hall Council Chambers", "city": None}},
            {"id": 2, "eventName": "Gone", "startDateTime": "2026-12-01T18:00:00Z", "isDeleted": True}]
    (e,) = build.normalize_civicclerk(src, rows, TZ)
    assert e["start"] == "2026-12-01T18:00:00-08:00"
    assert e["title"] == "City Council Meeting" and e["location"].startswith("Lacey City Hall")


def test_ics_expands_repeats():
    src = {"id": "tc", "name": "Thurston County", "area": "countywide", "homepage": "https://example.org"}
    ics = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:abc
SUMMARY:BoCC Business Meeting
DTSTART;TZID=America/Los_Angeles:20261103T140000
DTEND;TZID=America/Los_Angeles:20261103T160000
RRULE:FREQ=WEEKLY;UNTIL=20261215T220000Z
LOCATION:Atrium Room 110
END:VEVENT
BEGIN:VEVENT
UID:hidden
SUMMARY:Busy
DTSTART:20261118T180000Z
END:VEVENT
BEGIN:VEVENT
UID:hear
SUMMARY:Public Hearing on the 2027 Budget
DTSTART:20261119T020000Z
END:VEVENT
END:VCALENDAR
"""
    events = build.normalize_ics(src, ics, date(2026, 11, 10), date(2026, 11, 30), TZ)
    titles = [e["title"] for e in events]
    assert titles.count("BoCC Business Meeting") == 3  # Nov 10, 17, 24
    assert "Busy" not in titles
    hearing = next(e for e in events if "Hearing" in e["title"])
    assert hearing["category"] == "hearing" and hearing["start"] == "2026-11-18T18:00:00-08:00"
