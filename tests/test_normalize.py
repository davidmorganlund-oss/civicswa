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


def test_city_calendar_feed_titles():
    src = {"id": "tumwater", "name": "City of Tumwater", "area": "Tumwater"}
    def item(title, n):
        return f"<item><title>{title}</title><link>https://example.org/Event/{n}/</link></item>"
    xml = ('<rss version="2.0"><channel><title>Calendar RSS Feed</title>'
           + item("City Council (11/17/2026 7:00 p.m. - 10:00 p.m.)", 1)
           + item("LEOFF 1 - CANCELLED (11/12/2026 11:00 a.m. - 12:00 p.m.)", 2)
           + item("Veterans' Day - city offices closed (11/11/2026)", 3)
           + item("Something with no date", 4) + "</channel></rss>")
    council, leoff, holiday = build.normalize_govaccess_rss(src, xml, TZ)
    assert council["title"] == "City Council" and council["start"] == "2026-11-17T19:00:00-08:00"
    assert council["end"] == "2026-11-17T22:00:00-08:00" and council["category"] == "council"
    assert leoff["title"] == "LEOFF 1" and leoff["cancelled"] and leoff["start"].startswith("2026-11-12T11:00")
    assert holiday["all_day"] and holiday["title"] == "Veterans' Day - city offices closed"


def test_officials_parsers():
    import officials
    from datetime import date as d
    assert officials.biennium_for(d(2026, 11, 11)) == "2025-26"
    assert officials.biennium_for(d(2027, 1, 12)) == "2027-28"
    xml = """<ArrayOfMember xmlns="http://WSLWebServices.leg.wa.gov/">
      <Member><Id>1</Id><Name>Pat Example</Name><Agency>House</Agency><Party>R</Party><District>20</District>
        <Phone>(360) 555-0100</Phone><Email>pat@example.org</Email></Member>
      <Member><Id>2</Id><Name>Sam Sample</Name><Agency>Senate</Agency><Party>D</Party><District>20</District></Member>
    </ArrayOfMember>"""
    leg = officials.parse_legislators(xml)
    assert leg["20"]["house"][0] == {"name": "Pat Example", "party": "Republican",
                                     "phone": "(360) 555-0100", "email": "pat@example.org"}
    assert leg["20"]["senate"][0]["party"] == "Democrat"
    rows = [{"name": {"official_full": "A Senator"}, "terms": [{"type": "sen", "state": "WA", "party": "Democrat"}]},
            {"name": {"first": "B", "last": "Rep"}, "terms": [{"type": "rep", "state": "WA", "district": 10}]},
            {"name": {"official_full": "Other"}, "terms": [{"type": "rep", "state": "OR", "district": 1}]}]
    c = officials.parse_congress(rows)
    assert c["senators"][0]["name"] == "A Senator" and c["house"]["10"]["name"] == "B Rep" and len(c["house"]) == 1


def test_source_rules():
    def ev(cat):
        return {"category": cat, "title": cat}
    kept = build.apply_source_rules({"drop_uncategorized": True}, [ev("council"), ev("other"), ev("hearing")])
    assert [e["category"] for e in kept] == ["council", "hearing"]
    filed = build.apply_source_rules({"default_category": "council"}, [ev("other"), ev("hearing")])
    assert [e["category"] for e in filed] == ["council", "hearing"]
    assert len(build.apply_source_rules({}, [ev("other")])) == 1


def test_govaccess_long_dates():
    src = {"id": "shoreline", "name": "City of Shoreline", "area": "Shoreline", "county": "King"}
    xml = """<rss><channel><title>Calendar RSS Feed</title>
    <item><title>November 16, 2026 City Council Regular Meeting (November 16, 2026 7:00 pm - 10:00 pm)</title><link>https://example.org/1</link></item>
    <item><title>Greenhouse Winter Market (November 14, 2026 - November 15, 2026)</title><link>https://example.org/2</link></item>
    </channel></rss>"""
    council, market = build.normalize_govaccess_rss(src, xml, TZ)
    assert council["start"] == "2026-11-16T19:00:00-08:00" and council["county"] == "King"
    assert market["all_day"] and market["start"].startswith("2026-11-14")


def test_civicplus_closures_and_primegov():
    assert build.CLOSURE_TITLE.search("Thanksgiving Day") and build.CLOSURE_TITLE.search("City Hall closed")
    assert not build.CLOSURE_TITLE.search("Board of County Commissioners Meeting")
    src = {"id": "renton", "name": "City of Renton", "area": "Renton", "county": "King", "tenant": "renton"}
    rows = [{"id": 483, "dateTime": "2026-11-17T16:00:00", "title": "Special Civil Service Commission Meeting ",
             "location": "", "documentList": [{"templateId": 2234, "templateName": "HTML Agenda"}]}]
    (e,) = build.normalize_primegov(src, rows, TZ)
    assert e["start"] == "2026-11-17T16:00:00-08:00" and e["title"].endswith("Meeting")
    assert e["agenda_url"].endswith("meetingTemplateId=2234") and e["category"] == "council"


def test_civicweb():
    src = {"id": "sammamish", "name": "City of Sammamish", "area": "Sammamish", "county": "King", "tenant": "sammamishwa"}
    rows = [{"Id": 4840, "MeetingDateTime": "2026-12-17 18:30", "MeetingLocation": "City Hall",
             "Name": "Planning Commission - Dec 17 2026"},
            {"Id": 1, "MeetingDateTime": "2026-12-21 17:30", "MeetingLocation": "",
             "Name": "CANCELLED- City Council Regular Meeting - 21 Dec 2026"}]
    a, b = build.normalize_civicweb(src, rows, TZ)
    assert a["title"] == "Planning Commission" and a["start"] == "2026-12-17T18:30:00-08:00"
    assert b["cancelled"] and b["title"] == "City Council Regular Meeting"


def test_spokane_council_and_schedule():
    src = {"id": "spokane", "name": "City of Spokane", "area": "Spokane", "county": "Spokane"}
    page = ('<h5><a href="/citycouncil/meetings/2026/11/18/legislative-meeting/"><span class="">City Council Legislative Meeting</span></a></h5>\n'
            '<p>6 p.m. - Council Chambers Lower Level of City Hall.</p>'
            '<h5><a href="/citycouncil/meetings/2026/11/10/agenda-review-meeting/"><span class="">City Council Agenda Review Meeting</span></a></h5>\n'
            '<p>11 a.m. - Watch 10:11 - Council Chambers Lower Level of City Hall - No Public Testimony Taken.</p>')
    leg, review = build.normalize_spokane_council(src, page, TZ)
    assert leg["start"] == "2026-11-18T18:00:00-08:00" and leg["location"] == "Council Chambers Lower Level of City Hall"
    assert review["start"] == "2026-11-10T11:00:00-08:00" and review["url"].endswith("agenda-review-meeting/")
    sched = {"id": "b", "name": "Boards", "area": "Spokane",
             "meetings": [{"title": "Arts Commission", "when": "4th Tuesday", "time": "16:30", "skip_months": [12]}]}
    got = build.fetch_schedule(sched, date(2026, 11, 1), date(2027, 1, 31), TZ)
    assert [e["start"][:10] for e in got] == ["2026-11-24", "2027-01-26"]
    assert "regular meeting schedule" in got[0]["note"]


def test_highlights_skip_procedure():
    olympia = ["CALL TO ORDER", "ROLL CALL", "APPROVAL OF AGENDA", "APPROVAL OF MINUTES",
               "Approval of the October 28, 2026 Heritage Commission Meeting Minutes", "PUBLIC COMMENT",
               "ANNOUNCEMENTS", "BUSINESS ITEMS", "Recommend Approval for Evergreen Inn Special Tax Valuation",
               "Public Hearing and Decision- Evergreen Inn Heritage Register Listing", "REPORTS", "ADJOURNMENT", "Upcoming"]
    assert build.pick_highlights(olympia) == ["Recommend Approval for Evergreen Inn Special Tax Valuation",
                                              "Public Hearing and Decision- Evergreen Inn Heritage Register Listing"]
    lacey = ["<strong>Transportation Benefit District Presentation</strong><br>Shannon Kelley-Fong",
             "<strong>Recent Acquisitions*</strong><br>Erin Quinn Valcho, Museum Curator", "Approval of the Agenda*"]
    assert build.pick_highlights(lacey) == ["Transportation Benefit District Presentation", "Recent Acquisitions"]
    e = {}
    build.add_highlights(e, ["One item here", "Two item here", "Three item here", "Four item here"])
    assert len(e["highlights"]) == 3 and e["highlights_more"] == 1


def test_alerts_pick_long_failures():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
    import alerts
    status = {"sources": [
        {"name": "A", "state": "failing", "failing_since": "2026-11-08"},
        {"name": "B", "state": "failing", "failing_since": "2026-11-10"},
        {"name": "C", "state": "ok", "failing_since": ""}]}
    assert [s["name"] for s in alerts.stuck_sources(status, date(2026, 11, 11))] == ["A"]


def test_legislature_committees():
    src = {"id": "legislature", "name": "Washington State Legislature", "area": "statewide",
           "county": "Statewide", "homepage": "https://app.leg.wa.gov/committeeschedules/"}
    ns = 'xmlns="http://WSLWebServices.leg.wa.gov/"'
    meetings = f"""<ArrayOfCommitteeMeeting {ns}><CommitteeMeeting><AgendaId>34269</AgendaId>
      <Committees><Committee><LongName>House Appropriations</LongName></Committee></Committees>
      <Room>House JPB 102 and Virtual</Room><Building>Joel Pritchard Building</Building>
      <Date>2026-12-10T16:00:00</Date><Cancelled>false</Cancelled><CommitteeType>Full Committee</CommitteeType><Notes/>
      </CommitteeMeeting></ArrayOfCommitteeMeeting>"""
    (e,) = build.normalize_wsl_meetings(src, meetings, TZ)
    assert e["title"] == "House Appropriations" and e["start"] == "2026-12-10T16:00:00-08:00"
    assert e["category"] == "legislature" and e["url"].endswith("/Agenda/34269")
    items = f"""<ArrayOfCommitteeMeetingItem {ns}>
      <CommitteeMeetingItem><HearingTypeDescription>Public Hearing</HearingTypeDescription><BillId>HB 1001</BillId>
      <ItemDescription>Concerning library hours.</ItemDescription></CommitteeMeetingItem>
      <CommitteeMeetingItem><HearingTypeDescription>Work Session</HearingTypeDescription><BillId/>
      <ItemDescription>2027 Session Budget Preview.</ItemDescription></CommitteeMeetingItem></ArrayOfCommitteeMeetingItem>"""
    got, hearing = build.wsl_items(items)
    assert got == ["Public Hearing: HB 1001 – Concerning library hours", "2027 Session Budget Preview"] and hearing
