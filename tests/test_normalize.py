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


def test_cancelled_prefix_is_dropped():
    src = {"id": "tc", "name": "Thurston County", "area": "countywide"}
    from datetime import datetime
    e = build.make_event(src, title="Canceled: Board Work Session", start=datetime(2026, 11, 17, 9, 0, tzinfo=TZ))
    assert e["cancelled"] and e["title"] == "Board Work Session"


def test_library_feed_keeps_only_civic_events():
    src = {"id": "trl", "name": "Timberland Regional Library", "area": "countywide",
           "city_areas": {"Olympia": "Olympia"}}
    xml = """<rss xmlns:bc="http://bibliocommons.com/rss/1.0/modules/event/" version="2.0"><channel>
    <item><title><![CDATA[TRL Board of Trustees Special Meeting - Budget Committee]]></title>
      <link>https://example.org/e/1</link><guid>https://example.org/e/1</guid>
      <category><![CDATA[Board Meetings]]></category><category><![CDATA[Adults]]></category>
      <bc:start_date_local>2026-11-12T16:30</bc:start_date_local><bc:end_date_local>2026-11-12T17:30</bc:end_date_local>
      <bc:is_cancelled>false</bc:is_cancelled><bc:is_virtual>true</bc:is_virtual></item>
    <item><title>Birth to Five Storytime</title><link>https://example.org/e/2</link>
      <category>Storytime</category><bc:start_date_local>2026-11-12T10:15</bc:start_date_local>
      <bc:location><bc:id>OL</bc:id><bc:name>Olympia</bc:name><bc:number>313</bc:number>
        <bc:street>8th Avenue SE</bc:street><bc:city>Olympia</bc:city></bc:location></item>
    <item><title>Friends of the Library Meeting</title><link>https://example.org/e/3</link>
      <category>Friends of the Library</category><bc:start_date_local>2026-11-14T12:30</bc:start_date_local>
      <bc:location><bc:id>OL</bc:id><bc:name>Olympia</bc:name><bc:number>313</bc:number>
        <bc:street>8th Avenue SE</bc:street><bc:city>Olympia</bc:city></bc:location></item>
    <item><title>Budget Hearing</title><link>https://example.org/e/4</link><category>Board Meetings</category>
      <bc:start_date_local>2026-11-18T16:30</bc:start_date_local></item>
    </channel></rss>"""
    events = build.normalize_bibliocommons(src, xml, TZ)
    assert [e["title"] for e in events] == ["TRL Board of Trustees Special Meeting - Budget Committee",
                                            "Friends of the Library Meeting", "Budget Hearing"]
    board, friends, hearing = events
    assert board["category"] == "council" and board["area"] == "countywide" and board["location"] == "Online"
    assert board["start"] == "2026-11-12T16:30:00-08:00" and board["end"] == "2026-11-12T17:30:00-08:00"
    assert friends["category"] == "library" and friends["area"] == "Olympia"
    assert friends["location"] == "Olympia Timberland Library, 313 8th Avenue SE, Olympia"
    assert hearing["category"] == "hearing"


def test_municode_table():
    src = {"id": "tumwater", "name": "City of Tumwater", "area": "Tumwater",
           "url": "https://tumwater-wa.municodemeetings.com/"}
    html = """<table><tr><th>Date</th></tr>
    <tr class="odd"> <td data-th="Date"> <span class="date-display-single" property="dc:date" datatype="xsd:dateTime" content="2026-11-17T19:00:00-08:00">11/17/2026 7:00 pm</span> </td> <td class="views-field views-field-title" data-th="Meeting"> City Council </td> <td class="views-field views-field-field-agendas" data-th="Agenda"> <a href="https://example.org/MEET-Agenda-4d47.pdf" title="PDF Agenda"></a> <a href="https://meetings.municode.com/adaHtmlDocument/index?cc=TUMWATER&amp;me=4d47&amp;ip=False"></a> </td> <td class="views-field views-field-field-minutes"> </td> <td class="views-field views-field-view-node" data-th="View"> <a href="/bc-cc/page/city-council-102" target="_blank">View Details</a> </td> </tr>
    <tr class="even"> <td data-th="Date"> <span class="date-display-single" content="2026-11-18T11:00:00-08:00">x</span> </td> <td class="views-field views-field-title"> General Government Committee </td> <td class="views-field views-field-field-agendas"> </td> <td class="views-field views-field-view-node"> <a href="/bc-gg/page/general-government-committee-48">View Details</a> </td> </tr></table>"""
    council, committee = build.normalize_municode(src, html, TZ)
    assert council["title"] == "City Council" and council["start"] == "2026-11-17T19:00:00-08:00"
    assert council["agenda_url"] == "https://example.org/MEET-Agenda-4d47.pdf"
    assert council["url"] == "https://tumwater-wa.municodemeetings.com/bc-cc/page/city-council-102"
    assert committee["agenda_url"] == "" and committee["category"] == "council"


def test_port_feed_titles():
    src = {"id": "port", "name": "Port of Olympia", "area": "countywide",
           "default_location": "Percival Plaza", "default_location_marker": "Olympics Room"}
    def item(title, day, desc="Percival Plaza &#8211; Olympics Room626 Columbia"):
        return (f"<item><title>{title}</title><link>https://example.org/{day}</link>"
                f"<description><![CDATA[{desc}]]></description><mec:startDate>{day}</mec:startDate></item>")
    xml = ('<rss xmlns:mec="http://webnus.net/rss/mec/" version="2.0"><channel>'
           + item("November 16, 2026 Commission Work Session:  4:00 PM", "2026-11-16")
           + item("CANCELLED:  September 21, 2026 Commission Work Session:  4:00 PM", "2026-09-21")
           + item("October 6, 2026 Special Meeting Notice &#8211; Port Commission Retreat: 5:00 &#8211; 7:00 PM", "2026-10-06", "Elsewhere")
           + item("September 28, 2026 Commission Meeting:  4:00 PM &#8211; meeting held in City of Bucoda", "2026-09-28", "Bucoda")
           + item("August 18, 2026 &#8211; Commission Notice of Potential Quorum", "2026-08-18", "x")
           + "</channel></rss>")
    a, b, c, d, e = build.normalize_mec_rss(src, xml, TZ)
    assert a["title"] == "Commission Work Session" and a["start"] == "2026-11-16T16:00:00-08:00"
    assert a["location"] == "Percival Plaza" and not a["cancelled"]
    assert b["title"] == "Commission Work Session" and b["cancelled"]
    assert c["title"] == "Special Meeting Notice – Port Commission Retreat" and c["start"].startswith("2026-10-06T17:00")
    assert c["location"] == ""
    assert d["title"] == "Commission Meeting – meeting held in City of Bucoda" and d["start"].startswith("2026-09-28T16:00")
    assert e["title"] == "Commission Notice of Potential Quorum" and e["all_day"]
