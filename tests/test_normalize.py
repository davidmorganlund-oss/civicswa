"""Checks the three connectors against records shaped like the real feeds."""
import sys
import json
from datetime import date, datetime, timedelta
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
      <Committees><Committee><Name>Appropriations</Name><LongName>House Appropriations</LongName><Agency>House</Agency></Committee></Committees>
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
    got, hearing, bills = build.wsl_items(items)
    assert got == ["Public Hearing: HB 1001 – Concerning library hours", "2027 Session Budget Preview"] and hearing
    assert bills == [{"id": "HB 1001", "about": "Concerning library hours", "kind": "Public Hearing"}]


def test_diligent_school_board_portal():
    src = {"id": "lwsd", "name": "Lake Washington School District", "area": "Redmond", "county": "King",
           "type": "civicweb", "base": "https://lwsd.community.highbond.com", "category": "school",
           "exclude": "quorum"}
    rows = [{"Id": 1008, "Name": "Board Meeting - January 25, 2027", "MeetingDateTime": "2027-01-25 19:00",
             "MeetingLocation": "L. E. Scarr Resource Center; Board Room"},
            {"Id": 9, "Name": "Notice of Potential Quorum  - Nov 05 2026", "MeetingDateTime": "2026-11-05 16:30"},
            {"Id": 10, "Name": "Regular Board of Directors' Meeting - Jan 26, 2027",
             "MeetingDateTime": "2027-01-26 17:30"}]
    events = build.apply_source_rules(src, build.normalize_civicweb(src, rows, TZ))
    assert [e["title"] for e in events] == ["Board Meeting", "Regular Board of Directors' Meeting"]
    assert events[0]["url"] == "https://lwsd.community.highbond.com/Portal/MeetingInformation.aspx?Org=Cal&Id=1008"
    assert {e["category"] for e in events} == {"school"}


def test_schedule_date_list():
    src = {"id": "osd", "name": "Olympia School District", "area": "Olympia",
           "meetings": [{"title": "School Board Regular Meeting", "time": "18:30",
                         "dates": ["2026-11-12", "2026-12-10", "2027-01-14"]}]}
    events = build.fetch_schedule(src, date(2026, 11, 11), date(2026, 12, 31), TZ)
    assert [e["start"][:16] for e in events] == ["2026-11-12T18:30", "2026-12-10T18:30"]


def test_include_keeps_board_meetings_only():
    src = {"id": "everett-sd", "name": "Everett Public Schools", "area": "Everett", "include": r"\bboard\b"}
    rows = [build.make_event(src, title=t, start=build.datetime(2026, 12, 1, 18, 0, tzinfo=TZ))
            for t in ["School board meeting", "Winter break"]]
    assert [e["title"] for e in build.apply_source_rules(src, rows)] == ["School board meeting"]


def test_schedule_moves_holiday_meetings():
    assert build.date(2026, 11, 26) in build.wa_holidays(2026)       # Thanksgiving
    assert build.date(2026, 11, 27) in build.wa_holidays(2026)       # day after
    assert build.date(2027, 1, 18) in build.wa_holidays(2027)        # MLK Day
    src = {"id": "t", "name": "Tacoma Public Schools", "area": "Tacoma",
           "meetings": [{"title": "School Board Meeting", "when": "4th Thursday", "time": "18:00"}]}
    (e,) = build.fetch_schedule(src, date(2026, 11, 1), date(2026, 11, 30), TZ)
    assert e["start"].startswith("2026-11-30T18:00") and "holiday" in e["note"]


def test_granicus_agenda_rss():
    src = {"id": "lynnwood", "name": "City of Lynnwood", "area": "Lynnwood"}
    xml = """<rss><channel>
    <item><title>City Council Business Meeting - Nov 24, 2026</title><link>https://x.granicus.com/AgendaViewer.php?view_id=14&amp;event_id=9</link>
    <pubDate>Tue, 24 Nov 2026 19:00:00 -0800</pubDate><guid>e9</guid></item>
    <item><title>Planning Commission - December 10, 2026</title><link>https://x</link><pubDate>Thu, 10 Dec 2026 00:00:00 -0800</pubDate></item>
    </channel></rss>"""
    a, b = build.normalize_granicus(src, xml, TZ)
    assert a["title"] == "City Council Business Meeting" and a["start"].startswith("2026-11-24T19:00")
    assert b["title"] == "Planning Commission" and b["all_day"]


def test_apptegy_events():
    src = {"id": "sps", "name": "Spokane Public Schools", "area": "Spokane", "include": r"\bboard\b"}
    payload = {"events": [
        {"id": 1, "title": "Board of Directors Regular Meeting", "venue": "Admin Building", "all_day": False,
         "formatted_start": "2026-12-09 18:00:00", "formatted_end": "2026-12-09 20:00:00"},
        {"id": 2, "title": "Late Start Monday", "all_day": True,
         "formatted_start": "2026-11-16 00:00:00", "formatted_end": "2026-11-16 00:00:00"}]}
    events = build.apply_source_rules(src, build.normalize_apptegy(src, payload, TZ))
    assert [e["title"] for e in events] == ["Board of Directors Regular Meeting"]
    assert events[0]["start"].startswith("2026-12-09T18:00") and events[0]["location"] == "Admin Building"


def test_civicclerk_links_posted_agenda():
    src = {"id": "vancouver", "name": "City of Vancouver", "area": "Vancouver", "tenant": "vancouverwa"}
    rows = [{"id": 1573, "eventName": "Civil Service Commission", "startDateTime": "2026-11-18T15:00:00Z",
             "isPublished": "Published", "agendaId": 1235,
             "publishedFiles": [{"fileId": 3221, "type": "Agenda"}, {"fileId": 3222, "type": "Agenda Packet"}]},
            {"id": 1751, "eventName": "Special meeting", "startDateTime": "2026-11-19T15:00:00Z", "publishedFiles": []}]
    a, b = build.normalize_civicclerk(src, rows, TZ)
    assert a["agenda_url"] == "https://vancouverwa.portal.civicclerk.com/event/1573/files/agenda/3221"
    assert b["agenda_url"] == ""


def test_legislature_topics():
    e = build.tag_legislature({"title": "Senate Law & Justice", "highlights": [], "bills": [
        {"id": "SB 5001", "about": "Concerning sentencing review"},
        {"id": "SB 5002", "about": "Concerning agency reports"}]})
    assert e["topics"] == ["justice"]
    assert e["bills"][1]["topics"] == ["justice"]  # falls back to the committee's subject
    f = build.tag_legislature({"title": "House Appropriations", "highlights": [], "bills": [
        {"id": "HB 1100", "about": "Concerning tenant protections"},
        {"id": "HB 1101", "about": "Making supplemental appropriations"}]})
    assert f["bills"][0]["topics"] == ["housing"]
    assert f["bills"][1]["topics"] == ["budget"]  # "supplemental" is not mental health
    g = build.tag_legislature({"title": "Senate State Government, Tribal Affairs & Elections", "highlights": [], "bills": [
        {"id": "SB 5300", "about": "Concerning campaign finance disclosure"}]})
    assert g["bills"][0]["topics"] == ["elections"]
    assert "tribes" in g["topics"]


def test_note_cancels_only_when_it_is_a_notice():
    from datetime import datetime
    src = {"id": "x", "name": "X", "area": "X", "homepage": "https://example.gov"}
    when = datetime(2026, 12, 1, 18, 0, tzinfo=TZ)
    for note in ["Cancellation Notice", "MEETING CANCELED", "CANCELLED", "This meeting has been cancelled.",
                 "Meeting Cancelled due to no pertinent items to discuss.", "SPECIAL EVENT CANCELED - COMMUNITY CONVERSATIONS"]:
        assert build.make_event(src, title="City Council", start=when, note=note)["cancelled"], note
    for note in [build.SCHEDULE_NOTE, "To cancel your registration, call the clerk.",
                 "If the meeting is cancelled, a notice will be posted.", ""]:
        assert not build.make_event(src, title="City Council", start=when, note=note)["cancelled"], note


def test_regular_schedule_meetings_are_not_cancelled():
    sched = {"id": "b", "name": "Boards", "area": "Spokane",
             "meetings": [{"title": "Arts Commission", "when": "4th Tuesday", "time": "16:30"}]}
    got = build.fetch_schedule(sched, date(2026, 11, 1), date(2027, 1, 31), TZ)
    assert got and not any(e["cancelled"] for e in got)


def test_partial_links_fall_back_to_the_host_page(monkeypatch, tmp_path):
    ics = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:1\r\nDTSTART:20261201T180000\r\n"
           b"SUMMARY:Planning Commission\r\nURL:/common/modules/iCalendar/iCalendar.aspx?feed=calendar&catID=24\r\n"
           b"END:VEVENT\r\nEND:VCALENDAR\r\n")

    class Reply:
        content = ics

    monkeypatch.setattr(build, "get", lambda url, params=None: Reply())
    src = {"id": "rainier", "name": "City of Rainier", "area": "Rainier", "site": "https://www.cityofrainierwa.org",
           "categories": [24], "homepage": "https://www.cityofrainierwa.org/calendar"}
    (e,) = build.fetch_civicplus(src, date(2026, 11, 17), date(2027, 1, 16), TZ)
    assert e["url"] == "https://www.cityofrainierwa.org/calendar"
    del src["homepage"]
    (e,) = build.fetch_civicplus(src, date(2026, 11, 17), date(2027, 1, 16), TZ)
    assert e["url"] == "https://www.cityofrainierwa.org/Calendar.aspx"
    # The subscribable feed never carries a link that is not a full web address.
    e["url"] = "/not/a/link"
    from datetime import datetime
    build.write_ics([e], tmp_path / "t.ics", datetime(2026, 11, 17, tzinfo=TZ))
    assert "URL:" not in (tmp_path / "t.ics").read_text()


def test_duplicate_postings_are_merged():
    from datetime import datetime
    src = {"id": "lacey", "name": "City of Lacey", "area": "Lacey", "homepage": "https://cityoflacey.org"}
    when = datetime(2026, 12, 1, 18, 0, tzinfo=TZ)
    bare = build.make_event(src, title="City Council Meeting", start=when, uid="1369")
    full = build.make_event(src, title="City Council  meeting", start=when, uid="1569",
                            agenda_url="https://laceywa.portal.civicclerk.com/event/1569/files/agenda/9",
                            location="Lacey City Hall")
    other = build.make_event(src, title="Planning Commission", start=when, uid="7")
    later = build.make_event(src, title="City Council Meeting", start=datetime(2026, 12, 15, 18, 0, tzinfo=TZ), uid="8")
    got = build.merge_duplicates([bare, other, full, later])
    assert [e["id"] for e in got] == [full["id"], other["id"], later["id"]]


def test_one_site_never_gets_more_than_two_requests_at_once(monkeypatch):
    import sys
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    __import__("requests")  # make sure build.get finds it loaded

    live, peak, guard = {"n": 0}, {"n": 0}, threading.Lock()

    class Reply:
        def raise_for_status(self):
            pass

    def fake_get(url, params=None, headers=None, timeout=None):
        with guard:
            live["n"] += 1
            peak["n"] = max(peak["n"], live["n"])
        time.sleep(0.02)
        with guard:
            live["n"] -= 1
        return Reply()

    monkeypatch.setattr(sys.modules["requests"], "get", fake_get)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: build.get(f"https://same.example.org/feed/{i}"), range(16)))
    assert peak["n"] == build.PER_HOST == 2


def test_sources_are_read_in_parallel_and_kept_in_order(monkeypatch, tmp_path):
    import time
    from datetime import datetime
    cfg = tmp_path / "sources.yml"
    cfg.write_text("window_days: 30\ntimezone: America/Los_Angeles\nsources:\n" + "".join(
        f"  - {{id: s{i}, name: Source {i}, type: fake, county: King, area: Kent}}\n" for i in range(8)))

    def fake(src, start_day, end_day, tz):
        time.sleep(0.3)
        if src["id"] == "s3":
            raise RuntimeError("site is down")
        start = datetime.combine(start_day + timedelta(days=1), datetime.min.time(), tz).replace(hour=18)
        return [build.make_event(src, title="Council", start=start, uid=src["id"])] * 2  # posted twice

    monkeypatch.setitem(build.CONNECTORS, "fake", fake)
    monkeypatch.setattr(build, "CONFIG", cfg)
    monkeypatch.setattr(build, "OUT", tmp_path / "data")
    began = time.monotonic()
    assert build.main() == 0
    assert time.monotonic() - began < 1.5  # eight 0.3 s sources, not 2.4 s one after another
    status = json.loads((tmp_path / "data" / "status.json").read_text())["sources"]
    assert [s["id"] for s in status] == [f"s{i}" for i in range(8)]
    assert status[3]["state"] == "failing" and all(s["state"] == "ok" for s in status if s["id"] != "s3")
    events = json.loads((tmp_path / "data" / "events.json").read_text())["events"]
    assert len(events) == 7  # one per working source, duplicates merged


def test_civicclerk_titles_name_the_body_when_the_event_name_is_only_a_date():
    cases = {
        ("November 17, 2026, Meeting", "City Council"): "City Council Meeting",
        ("November 10, 2026, Special Meeting", "City Council"): "City Council Special Meeting",
        ("Study Session", "City Council"): "City Council Study Session",
        ("City Council Meeting", "City Council"): "City Council Meeting",
        ("Planning Commission", "Boards and Commissions"): "Planning Commission",
        ("", "Parks Board"): "Parks Board",
    }
    for (name, body), want in cases.items():
        assert build.civicclerk_title({"eventName": name, "categoryName": body}) == want


def test_blank_events_calendar_feed_falls_back_to_its_api(monkeypatch):
    calls = []

    class Reply:
        def __init__(self, content=b"", data=None):
            self.content, self._data = content, data

        def json(self):
            return self._data

    page = {"total_pages": 1, "events": [
        {"id": 17412, "title": "City Council Meeting &#8211; Public Hearing", "all_day": False,
         "start_date": "2026-12-01 19:00:00", "utc_start_date": "2026-12-02 03:00:00",
         "end_date": "2026-12-01 21:00:00", "utc_end_date": "2026-12-02 05:00:00",
         "url": "https://cityofgoldbar.us/event/council-meeting/",
         "venue": {"venue": "Gold Bar City Hall", "address": "107 5th St", "city": "Gold Bar"}},
        {"id": 2, "title": "Office Closed", "all_day": True, "start_date": "2026-12-25 00:00:00",
         "utc_start_date": "", "url": "https://cityofgoldbar.us/event/closed/", "venue": []},
    ]}

    def fake_get(url, params=None):
        calls.append(url)
        return Reply(b"") if "ical=1" in url else Reply(data=page)

    monkeypatch.setattr(build, "get", fake_get)
    src = {"id": "gold-bar", "name": "City of Gold Bar", "area": "Gold Bar", "type": "ics",
           "url": "https://cityofgoldbar.us/events/?ical=1", "homepage": "https://cityofgoldbar.us/"}
    got = build.fetch_ics(src, date(2026, 11, 18), date(2027, 1, 17), TZ)
    assert calls == ["https://cityofgoldbar.us/events/?ical=1",
                     "https://cityofgoldbar.us/wp-json/tribe/events/v1/events"]
    council, closed = got
    assert council["title"] == "City Council Meeting – Public Hearing"
    assert council["start"].startswith("2026-12-01T19:00")
    assert council["location"] == "Gold Bar City Hall, 107 5th St, Gold Bar"
    assert council["url"] == "https://cityofgoldbar.us/event/council-meeting/"
    assert closed["all_day"] and closed["start"].startswith("2026-12-25")


def test_blank_feed_from_other_hosts_is_still_an_error(monkeypatch):
    import pytest

    class Reply:
        content = b""

    monkeypatch.setattr(build, "get", lambda url, params=None: Reply())
    src = {"id": "x", "name": "X", "area": "X", "type": "ics", "url": "https://calendar.example.org/basic.ics"}
    with pytest.raises(ValueError):
        build.fetch_ics(src, date(2026, 11, 18), date(2027, 1, 17), TZ)


def test_separate_meetings_sharing_one_uid_are_all_kept():
    def vevent(day, uid="same", extra=""):
        return (f"BEGIN:VEVENT\r\nUID:{uid}\r\nSUMMARY:City Council Meetings\r\n"
                f"DTSTART;TZID=America/Los_Angeles:2026{day}T190000\r\n{extra}END:VEVENT\r\n")
    ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + vevent("0810") + vevent("1207") + vevent("1214")
           + vevent("1201", uid="series", extra="RRULE:FREQ=WEEKLY;COUNT=3\r\n") + "END:VCALENDAR\r\n").encode()
    src = {"id": "bellingham", "name": "City of Bellingham", "area": "Bellingham"}
    got = build.normalize_ics(src, ics, date(2026, 11, 18), date(2027, 1, 17), TZ)
    starts = sorted(e["start"][:10] for e in got)
    assert starts == ["2026-12-01", "2026-12-07", "2026-12-08", "2026-12-14", "2026-12-15"]



def test_granicus_reads_24_hour_parts_not_12_hour_pubdate():
    # Granicus writes a 5:30 p.m. meeting's pubDate as 05:30 with no AM/PM;
    # <gran:pubDateParts> carries the real 24-hour time.
    from zoneinfo import ZoneInfo
    xml = """<?xml version="1.0"?><rss version="2.0" xmlns:gran="https://www.granicus.com/schema/rss-supplements"><channel>
<item><guid>a</guid><title>City Council Meeting - Nov 17, 2026</title><pubDate>Tue, 17 Nov 2026 05:30:00 -0800</pubDate>
<gran:pubDateParts yr='2026' mo='11' day='17' hr='17' min='30' sec='0' tz='8' /><link>https://x.granicus.com/AgendaViewer.php?view_id=3</link></item>
<item><guid>b</guid><title>City Council - Nov 10, 2026</title><pubDate>Mon, 09 Nov 2026 09:15:00 -0800</pubDate>
<gran:pubDateParts yr='2026' mo='11' day='09' hr='21' min='15' sec='0' tz='8' /><link>https://x.granicus.com/AgendaViewer.php?view_id=3</link></item>
</channel></rss>"""
    src = {"id": "t", "name": "Test", "county": "King", "area": "Test", "homepage": ""}
    events = build.normalize_granicus(src, xml, ZoneInfo("America/Los_Angeles"))
    assert events[0]["start"].startswith("2026-11-17T17:30")
    # A publish time on another day than the meeting's isn't used as the meeting time.
    assert events[1]["start"].startswith("2026-11-10T00:00") and events[1]["all_day"]


def test_schedule_skips_holidays_when_asked():
    src = {"id": "t", "name": "Test", "county": "King", "area": "Test", "homepage": "",
           "meetings": [{"title": "Council", "when": "1st, 2nd, 3rd, 4th, 5th Monday", "time": "19:00", "holidays": "skip"}]}
    days = [e["start"][:10] for e in build.fetch_schedule(src, date(2027, 1, 11), date(2027, 1, 25), ZoneInfo("America/Los_Angeles"))]
    assert days == ["2027-01-11", "2027-01-25"]  # MLK Day (Jan 18) is skipped, not moved


def test_schedule_monday_holiday_shift_and_shift_days():
    tz = ZoneInfo("America/Los_Angeles")
    tue = {"id": "t", "name": "Test", "county": "X", "area": "X", "homepage": "",
           "meetings": [{"title": "Board", "when": "3rd Tuesday", "time": "09:30", "monday_holiday_shift": 1}]}
    assert build.fetch_schedule(tue, date(2027, 1, 1), date(2027, 1, 31), tz)[0]["start"][:10] == "2027-01-20"
    ws = {"id": "t", "name": "Test", "county": "X", "area": "X", "homepage": "",
          "meetings": [{"title": "Work session", "when": "2nd Wednesday", "time": "16:00", "shift_days": -2}]}
    assert build.fetch_schedule(ws, date(2027, 2, 1), date(2027, 2, 28), tz)[0]["start"][:10] == "2027-02-08"


# --- BoardDocs snapshot ---

def _bd_snapshot():
    return json.loads((Path(__file__).parent / "fixtures" / "boarddocs.json").read_text())


def _bd_source(slug, meetings):
    return {"id": f"{slug}-schools", "name": slug, "type": "schedule", "boarddocs": slug, "county": "X", "area": "X",
            "category": "school", "default_category": "school", "homepage": "https://example.org", "meetings": meetings}


def test_boarddocs_posted_meetings_then_pattern():
    src = _bd_source("ferndale", [{"title": "School Board Regular Meeting", "when": "last Tuesday", "time": "18:00",
                                   "location": "Board room"}])
    got = build.fetch_schedule(src, date(2026, 11, 23), date(2027, 1, 31), TZ, snapshot=_bd_snapshot())
    first = got[0]
    assert (first["start"], first["title"]) == ("2026-11-24T18:00:00-08:00", "School Board Regular Meeting")
    assert first["location"] == "5780 Hendrickson Ave, Ferndale, WA"
    assert first["url"] == "https://go.boarddocs.com/wa/ferndale/Board.nsf/Public"
    # After the last posted meeting, the pattern carries on.
    assert [e["start"][:10] for e in got[1:]] == ["2026-12-29", "2027-01-26"]


def test_boarddocs_meeting_details():
    src = _bd_source("msdwa", [{"title": "School Board Regular Meeting", "when": "2nd, 4th Wednesday", "time": "17:00"}])
    got = {e["start"][:10]: e for e in build.fetch_schedule(src, date(2026, 11, 23), date(2027, 7, 31), TZ, snapshot=_bd_snapshot())}
    assert got["2027-01-20"]["start"][11:16] == "17:00"          # not the 4:00 executive session
    assert got["2026-12-09"]["location"] == "Meridian Middle School - Library"
    assert "2027-06-04" not in got                                # graduation, not a meeting
    assert got["2027-07-14"]["title"] == "School Board Retreat"
    assert got["2027-07-14"]["location"] == "7 Bellwether Way, Bellingham, WA 98225"
    assert "2027-07-28" in got                                   # pattern after the last posted date


def test_boarddocs_time_location_and_cancelled():
    tenino = _bd_source("tenino", [{"title": "School Board Regular Meeting", "when": "4th Monday", "time": "18:00"}])
    (e,) = build.fetch_schedule(tenino, date(2026, 11, 23), date(2026, 11, 30), TZ, snapshot=_bd_snapshot())
    assert (e["start"][11:16], e["location"]) == ("18:30", "Tenino School District - Boardroom")
    wishkah = _bd_source("wishkah", [{"title": "School Board Regular Meeting", "when": "4th Thursday", "time": "17:00", "holidays": "skip"}])
    (w,) = build.fetch_schedule(wishkah, date(2026, 11, 23), date(2026, 11, 30), TZ, snapshot=_bd_snapshot())
    assert w["cancelled"] and w["title"] == "School Board Regular Meeting" and w["start"][11:16] == "17:00"


def test_boarddocs_falls_back_to_pattern():
    snap = _bd_snapshot()
    for slug in ("selah", "nowhere"):   # a failed board, and one missing from the snapshot
        src = _bd_source(slug, [{"title": "School Board Business Meeting", "when": "4th Thursday", "time": "16:30"}])
        days = [e["start"][:10] for e in build.fetch_schedule(src, date(2026, 12, 1), date(2027, 1, 31), TZ, snapshot=snap)]
        assert days == ["2026-12-24", "2027-01-28"] or days == ["2026-12-28", "2027-01-28"]
    # Nothing posted: the pattern from the snapshot date on.
    yak = _bd_source("yakima", [{"title": "School Board Meeting", "when": "1st Monday", "time": "16:00"}])
    assert [e["start"][:10] for e in build.fetch_schedule(yak, date(2026, 12, 1), date(2027, 1, 31), TZ, snapshot=snap)] == ["2026-12-07", "2027-01-04"]


def test_boarddocs_stale_snapshot_ignored(tmp_path, monkeypatch):
    stale = _bd_snapshot() | {"fetched_at": "2026-10-01T00:00:00+00:00"}
    path = tmp_path / "boarddocs.json"
    path.write_text(json.dumps(stale))
    monkeypatch.setattr(build, "BOARDDOCS_SNAPSHOT", path)
    monkeypatch.setattr(build, "_bd_cache", {})
    assert build.boarddocs_snapshot(now=datetime(2026, 11, 23, tzinfo=TZ)) is None


def test_cancelled_copy_wins_over_its_twin():
    src = {"id": "fh", "name": "Town of Friday Harbor", "area": "Friday Harbor", "homepage": "https://example.org"}
    when = datetime(2026, 12, 10, 17, 30, tzinfo=TZ)
    live = build.make_event(src, title="Planning Commission", start=when, uid="1", location="Town Hall",
                            agenda_url="https://example.org/agenda.pdf")
    gone = build.make_event(src, title="Planning Commission", start=when, uid="2", note="Cancellation Notice")
    (kept,) = build.merge_duplicates([live, gone])
    assert kept["id"] == gone["id"] and kept["cancelled"]


def test_joint_meeting_posted_once_per_body_is_one_meeting():
    src = {"id": "mi", "name": "City of Mercer Island", "area": "Mercer Island", "homepage": "https://example.org"}
    when = datetime(2026, 12, 7, 17, 0, tzinfo=TZ)
    a = build.make_event(src, title="Arts Council, Parks & Rec Commission, and Open Space Conservancy Trust Special Joint Hybrid Meeting", start=when, uid="1")
    b = build.make_event(src, title="Parks & Rec Commission, Open Space Conservancy Trust and Arts Council Special Joint Hybrid Meeting", start=when, uid="2")
    c = build.make_event(src, title="Planning Commission", start=when, uid="3")
    assert len(build.merge_duplicates([a, b, c])) == 2


def test_room_codes_and_placeholder_locations_are_tidied():
    src = {"id": "tc", "name": "Thurston County", "area": "countywide", "homepage": "https://example.org"}
    when = datetime(2026, 12, 1, 9, 0, tzinfo=TZ)
    assert build.make_event(src, title="Board Work Session", start=when, location="ATR_Board_Rm_110")["location"] == "ATR Board Rm 110"
    assert build.make_event(src, title="Board Work Session", start=when, location="TBD")["location"] == ""
    assert build.make_event(src, title="Board Work Session", start=when, location="Room 1_A, City Hall")["location"] == "Room 1_A, City Hall"


def test_civicclerk_event_type_is_not_a_title():
    r = {"eventName": "One Time Event", "categoryName": "Parks Board"}
    assert build.civicclerk_title(r) == "Parks Board"
    assert build.civicclerk_title({"eventName": "One Time Event", "categoryName": "One Time Event"}) == "One Time Event"
    assert build.civicclerk_title({"eventName": "One Time Event", "categoryName": ""}) == "One Time Event"


def test_quiet_sources_are_flagged_after_two_weeks():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
    import alerts
    today = date(2026, 12, 20)
    status = {"sources": [
        {"name": "A", "state": "quiet", "quiet_since": "2026-12-01"},
        {"name": "B", "state": "quiet", "quiet_since": "2026-12-15"},
        {"name": "C", "state": "quiet", "quiet_since": "2026-12-01", "quiet_ok": True},
        {"name": "D", "state": "ok", "quiet_since": ""},
        {"name": "E", "state": "quiet"}]}
    assert [s["name"] for s in alerts.quiet_sources(status, today)] == ["A"]
    assert "nothing listed since 2026-12-01" in alerts.body([], alerts.quiet_sources(status, today))
