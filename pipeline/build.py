"""CivicsWA pipeline: read each public calendar source, normalize the events,
and write the files the site reads.

Outputs (in site/data/):
  events.json   upcoming events, soonest first
  status.json   per-source health, so a quiet or broken source is visible
  thurston.ics  a subscribable calendar of everything in events.json

Run:  python pipeline/build.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data"
UA = "CivicsWA-pilot/0.1 (BarNone nonprofit civic calendar; contact via barnoneinc.org)"
TIMEOUT = 45


# ---------- shared helpers ----------

CATEGORY_RULES = [
    ("hearing", r"\bhearing"),
    ("school", r"\bschool\b"),
    ("library", r"\blibrary\b"),
    ("council", r"council|commission|board|committee|authority|district|work ?session|study session"),
]


def categorize(text: str) -> str:
    low = (text or "").lower()
    for cat, pattern in CATEGORY_RULES:
        if re.search(pattern, low):
            return cat
    return "other"


def is_cancelled(*texts: str) -> bool:
    return any(re.search(r"cancel", t or "", re.I) for t in texts)


def make_event(src, *, title, start, end=None, all_day=False, location="", url="",
               agenda_url="", note="", uid="", category="", area="", cancelled=False):
    key = f"{src['id']}|{uid or title}|{start.isoformat()}"
    cancelled = cancelled or is_cancelled(title, note)
    # Hosts often prefix the title ("Canceled: Board Work Session"); the site
    # shows its own Cancelled tag, so drop the prefix.
    title = re.sub(r"^[\s*]*cancel+ed[\s*]*(?:[:\-–]\s*|\s+(?=\S))", "", title or "", flags=re.I)
    title = re.sub(r"\s*[-–:(]\s*cancel+ed\s*\)?\s*$", "", title, flags=re.I)
    # Some calendars put HTML or stray separators in the location field.
    location = re.sub(r"<[^>]+>", " ", location or "")
    location = re.sub(r"^[\s\-–,]+|[\s\-–,]+$", "", " ".join(location.split()))
    return {
        "id": hashlib.sha1(key.encode()).hexdigest()[:12],
        "title": " ".join((title or "").split()),
        "host": src["name"],
        "source": src["id"],
        "area": area or src["area"],
        "county": src.get("county", "Thurston"),
        "category": category or categorize(title),
        "start": start.isoformat(),
        "end": end.isoformat() if end else None,
        "all_day": all_day,
        "location": " ".join((location or "").split()),
        "url": url or src.get("homepage", ""),
        "agenda_url": agenda_url or "",
        "note": " ".join((note or "").split()),
        "cancelled": cancelled,
    }


def get(url, params=None):
    import requests
    resp = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp


# ---------- connectors ----------

def parse_clock(text: str):
    """'5:30 PM' -> time(17, 30). Returns None when there is no usable time."""
    m = re.match(r"\s*(\d{1,2})(?::(\d{2}))?\s*([AaPp])\.?[Mm]\.?", text or "")
    if not m:
        return None
    hour = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "p" else 0)
    return time(hour, int(m.group(2) or 0))


def normalize_legistar(src, rows, tz):
    events = []
    for r in rows:
        day = datetime.fromisoformat(r["EventDate"]).date()
        clock = parse_clock(r.get("EventTime"))
        start = datetime.combine(day, clock or time(0, 0), tz)
        events.append(make_event(
            src,
            title=r.get("EventBodyName") or "Public meeting",
            start=start,
            all_day=clock is None,
            location=r.get("EventLocation") or "",
            url=r.get("EventInSiteURL") or "",
            agenda_url=r.get("EventAgendaFile") or "",
            note=r.get("EventComment") or "",
            uid=str(r.get("EventId", "")),
        ))
    return events


def fetch_legistar(src, start_day, end_day, tz):
    flt = (f"EventDate ge datetime'{start_day.isoformat()}' and "
           f"EventDate le datetime'{end_day.isoformat()}'")
    rows = get(f"https://webapi.legistar.com/v1/{src['client']}/events",
               {"$filter": flt, "$orderby": "EventDate"}).json()
    return normalize_legistar(src, rows, tz)


def normalize_civicclerk(src, rows, tz):
    events = []
    for r in rows:
        if r.get("isDeleted") or r.get("isPublished") is False:
            continue
        # CivicClerk labels its times "Z" but they are local wall-clock times
        # (Lacey's 6 p.m. council meetings come through as 18:00:00Z).
        raw = (r.get("startDateTime") or "")[:19]
        if not raw:
            continue
        start = datetime.fromisoformat(raw).replace(tzinfo=tz)
        loc = r.get("eventLocation") or {}
        place = ", ".join(p for p in [loc.get("address1"), loc.get("address2"), loc.get("city")]
                          if p) if isinstance(loc, dict) else ""
        tenant = src["tenant"]
        events.append(make_event(
            src,
            title=r.get("eventName") or r.get("categoryName") or "Public meeting",
            start=start,
            location=place,
            url=f"https://{tenant}.portal.civicclerk.com/event/{r['id']}/overview",
            note=r.get("eventDescription") or "",
            uid=str(r["id"]),
        ))
    return events


def fetch_civicclerk(src, start_day, end_day, tz):
    flt = (f"startDateTime ge {start_day.isoformat()}T00:00:00Z and "
           f"startDateTime le {end_day.isoformat()}T23:59:59Z")
    url = f"https://{src['tenant']}.api.civicclerk.com/v1/Events"
    params = {"$filter": flt, "$orderby": "startDateTime asc"}
    rows = []
    for _ in range(20):  # follow paging, with a hard stop
        data = get(url, params).json()
        rows.extend(data.get("value", []))
        url, params = data.get("@odata.nextLink"), None
        if not url:
            break
    return normalize_civicclerk(src, rows, tz)


def normalize_ics(src, ics_text, start_day, end_day, tz):
    import icalendar
    import recurring_ical_events

    cal = icalendar.Calendar.from_ical(ics_text)
    window_start = datetime.combine(start_day, time(0, 0), tz)
    window_end = datetime.combine(end_day, time(23, 59), tz)
    events = []
    for comp in recurring_ical_events.of(cal).between(window_start, window_end):
        raw_start = comp["DTSTART"].dt
        raw_end = comp["DTEND"].dt if comp.get("DTEND") else None
        all_day = not isinstance(raw_start, datetime)

        def local(value):
            if value is None:
                return None
            if not isinstance(value, datetime):
                return datetime.combine(value, time(0, 0), tz)
            return value.astimezone(tz) if value.tzinfo else value.replace(tzinfo=tz)

        title = str(comp.get("SUMMARY", "")).strip()
        if not title or title.lower() in {"busy", "free", "tentative"}:
            continue  # published Outlook calendars can hide titles
        events.append(make_event(
            src,
            title=title,
            start=local(raw_start),
            end=local(raw_end),
            all_day=all_day,
            location=str(comp.get("LOCATION", "")),
            url=str(comp.get("URL", "")) or src.get("homepage", ""),
            uid=str(comp.get("UID", "")),
        ))
    return events


def fetch_ics(src, start_day, end_day, tz):
    return normalize_ics(src, get(src["url"]).content, start_day, end_day, tz)


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def fields(element) -> dict:
    """Child elements of an XML node as {name: text}; repeated names become lists."""
    out: dict = {}
    for child in element:
        name, text = local(child.tag), (child.text or "").strip()
        if name in out:
            out[name] = (out[name] if isinstance(out[name], list) else [out[name]]) + [text]
        else:
            out[name] = text
    return out


def rss_items(xml_text):
    import xml.etree.ElementTree as ET
    return [el for el in ET.fromstring(xml_text).iter() if local(el.tag) == "item"]


# --- BiblioCommons library events (RSS) ---

CIVIC_TITLE = re.compile(
    r"civic|\bvot(e|er|ers|ing)\b|election|ballot|legislat|city council|town hall|candidate|"
    r"citizenship|naturalization|government|public comment|public hearing|budget hearing|"
    r"board of trustees|community forum|listening session|advocacy", re.I)


def library_event_is_civic(title: str, categories: list) -> bool:
    if "Board Meetings" in categories or CIVIC_TITLE.search(title or ""):
        return True
    return "Friends of the Library" in categories and "meeting" in (title or "").lower()


def normalize_bibliocommons(src, xml_text, tz):
    events = []
    areas = src.get("city_areas", {})
    for item in rss_items(xml_text):
        f = fields(item)
        cats = f.get("category", [])
        cats = cats if isinstance(cats, list) else [cats]
        title = f.get("title", "")
        raw = f.get("start_date_local", "")
        if not raw or not library_event_is_civic(title, cats):
            continue
        all_day = "T" not in raw
        start = datetime.fromisoformat(raw if not all_day else raw + "T00:00").replace(tzinfo=tz)
        end_raw = f.get("end_date_local", "")
        end = datetime.fromisoformat(end_raw).replace(tzinfo=tz) if "T" in end_raw else None
        loc_el = next((c for c in item if local(c.tag) == "location"), None)
        loc = fields(loc_el) if loc_el is not None else {}
        virtual = f.get("is_virtual") == "true"
        place = ", ".join(p for p in [
            (loc.get("name", "") + " Timberland Library")
            if len(loc.get("id", "")) == 2 and not re.search(r"library|headquarters|TRL", loc.get("name", ""), re.I)
            else loc.get("name", ""),
            " ".join(p for p in [loc.get("number", ""), loc.get("street", "")] if p),
            loc.get("city", "")] if p)
        board = "Board Meetings" in cats or re.search(r"trustees|budget hearing", title, re.I)
        events.append(make_event(
            src, title=title, start=start, end=end, all_day=all_day,
            location=("Online" + (" and " + place if place else "")) if virtual else place,
            url=f.get("link", ""), uid=f.get("guid", "") or f.get("link", ""),
            category=("hearing" if re.search(r"hearing", title, re.I) else "council") if board else "library",
            area="countywide" if board else areas.get(loc.get("city", ""), loc.get("city", "") or "countywide"),
            cancelled=f.get("is_cancelled") == "true",
        ))
    return events


def fetch_bibliocommons(src, start_day, end_day, tz):
    import time as clock
    base = f"https://gateway.bibliocommons.com/v2/libraries/{src['library']}/rss/events"
    queries = [{"locations": ",".join(src["locations"])}] + [{"q": q} for q in src.get("searches", [])]
    found = {}
    for query in queries:
        for page in range(1, 31):  # 25 events a page, soonest first
            xml_text = get(base, {**query, "page": page}).text
            items = rss_items(xml_text)
            for e in normalize_bibliocommons(src, xml_text, tz):
                found[e["id"]] = e
            starts = [fields(i).get("start_date_local", "")[:10] for i in items]
            if len(items) < 25 or (starts and min(s for s in starts[-5:] if s) > end_day.isoformat()):
                break
            clock.sleep(1)  # be gentle with the library's server
    return list(found.values())


# --- Municode Meetings portal (HTML table of meetings) ---

def normalize_municode(src, html_text, tz):
    import html as htmllib
    events = []
    for row in re.findall(r"<tr\b.*?</tr>", html_text, re.S):
        when = re.search(r'class="date-display-single"[^>]*content="([^"]+)"', row)
        title = re.search(r'views-field-title"[^>]*>(.*?)</td>', row, re.S)
        if not when or not title:
            continue
        start = datetime.fromisoformat(when.group(1)).astimezone(tz)
        agenda = re.search(r'views-field-field-agendas".*?href="([^"]+\.pdf)"', row, re.S)
        detail = re.search(r'views-field-view-node".*?href="([^"]+)"', row, re.S)
        name = htmllib.unescape(re.sub(r"<[^>]+>", " ", title.group(1)))
        url = htmllib.unescape(detail.group(1)) if detail else ""
        events.append(make_event(
            src, title=name, start=start,
            url=(src["url"].rstrip("/") + url) if url.startswith("/") else url,
            agenda_url=htmllib.unescape(agenda.group(1)) if agenda else "",
            uid=url or name,
        ))
    return events


def fetch_municode(src, start_day, end_day, tz):
    return normalize_municode(src, get(src["url"]).text, tz)


# --- WordPress "Modern Events Calendar" RSS (dates in mec:startDate, time in the title) ---

TIME_IN_TITLE = re.compile(r"\b\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?", re.I)
TIME_RANGE = re.compile(r"\b(\d{1,2}(?::\d{2})?)\s*([ap]\.?m\.?)?\s*[–-]\s*\d{1,2}(?::\d{2})?\s*([ap]\.?m\.?)", re.I)
LEADING_DATE = re.compile(r"^[A-Z][a-z]+ \d{1,2}(?:\s*[–-]\s*[A-Z][a-z]+ \d{1,2})?, \d{4}\s*[–-]?\s*")


def normalize_mec_rss(src, xml_text, tz):
    import html as htmllib
    events = []
    for item in rss_items(xml_text):
        f = fields(item)
        day = f.get("startDate", "")
        if not day:
            continue
        raw_title = htmllib.unescape(f.get("title", ""))
        cancelled = bool(re.search(r"cancel", raw_title, re.I))
        title = re.sub(r"^\s*(cancel+ed|updated)\s*:\s*", "", raw_title, flags=re.I)
        title = LEADING_DATE.sub("", title)
        span = TIME_RANGE.search(title)  # "5:00 – 7:00 PM": the start borrows the end's am/pm
        if span:
            clock = parse_clock(f"{span.group(1)} {span.group(2) or span.group(3)}")
        else:
            clock_match = TIME_IN_TITLE.search(title)
            clock = parse_clock(clock_match.group(0)) if clock_match else None
        # drop ": 4:00 PM" or ": 5:00 – 7:00 PM" but keep any trailing note about where it is held
        title = re.sub(r":?\s*\d{1,2}(?::\d{2})?\s*(?:[ap]\.?m\.?)?\s*(?:[–-]\s*\d{1,2}(?::\d{2})?\s*)?[ap]\.?m\.?",
                       "", title, count=1, flags=re.I).strip(" :–-")
        description = htmllib.unescape(f.get("description", ""))
        default_place = src.get("default_location", "")
        events.append(make_event(
            src, title=title or raw_title,
            start=datetime.combine(date.fromisoformat(day), clock or time(0, 0), tz),
            all_day=clock is None,
            location=default_place if default_place and src.get("default_location_marker", "") in description else "",
            url=f.get("link", ""), uid=f.get("guid", "") or f.get("link", ""),
            cancelled=cancelled,
        ))
    return events


def fetch_mec_rss(src, start_day, end_day, tz):
    return normalize_mec_rss(src, get(src["url"]).text, tz)


# --- Granicus govAccess city sites: calendar RSS, with the date and time in the title ---
# e.g. "City Council (11/17/2026 7:00 p.m. - 10:00 p.m.)"

GOVACCESS_TITLE = re.compile(
    r"^(?P<name>.*?)\s*\((?P<day>\d{1,2}/\d{1,2}/\d{4}|[A-Z][a-z]+ \d{1,2}, \d{4})"
    r"(?:\s+(?P<start>\d{1,2}:\d{2}\s*[ap]\.?m\.?)(?:\s*-\s*(?P<end>\d{1,2}:\d{2}\s*[ap]\.?m\.?))?)?"
    r"(?:\s*-\s*[A-Z][a-z]+ \d{1,2}, \d{4})?\)\s*$", re.I)


def govaccess_day(text: str) -> date:
    for fmt in ("%m/%d/%Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(text)


def normalize_govaccess_rss(src, xml_text, tz):
    import html as htmllib
    events = []
    for item in rss_items(xml_text):
        f = fields(item)
        m = GOVACCESS_TITLE.match(htmllib.unescape(f.get("title", "")))
        if not m:
            continue
        day = govaccess_day(m.group("day"))
        start_clock = parse_clock(m.group("start")) if m.group("start") else None
        end_clock = parse_clock(m.group("end")) if m.group("end") else None
        name = m.group("name")
        cancelled = bool(re.search(r"cancel", name, re.I))
        name = re.sub(r"\s*[-–]\s*cancel+ed\s*$", "", name, flags=re.I)
        events.append(make_event(
            src, title=name,
            start=datetime.combine(day, start_clock or time(0, 0), tz),
            end=datetime.combine(day, end_clock, tz) if end_clock else None,
            all_day=start_clock is None,
            url=f.get("link", ""), uid=f.get("link", "") or name,
            cancelled=cancelled,
        ))
    return events


def fetch_govaccess_rss(src, start_day, end_day, tz):
    return normalize_govaccess_rss(src, get(src["url"]).text, tz)


# --- CivicPlus (CivicEngage) county and city sites: one iCal feed per calendar category ---
# Categories are picked by hand in sources.yml; holidays and office closures
# that the sites copy into every category are dropped.

CLOSURE_TITLE = re.compile(r"holiday|clos(ed|ure)|thanksgiving|christmas|new year|day observed|\bday$", re.I)


def fetch_civicplus(src, start_day, end_day, tz):
    site = src["site"].rstrip("/")
    seen, events = set(), []
    for cat in src["categories"]:
        ics = get(f"{site}/common/modules/iCalendar/iCalendar.aspx", {"catID": cat, "feed": "calendar"}).content
        for e in normalize_ics(src, ics, start_day, end_day, tz):
            if e["id"] in seen or CLOSURE_TITLE.search(e["title"]):
                continue
            seen.add(e["id"])
            if not e["url"] or e["url"] == src.get("homepage", ""):
                e["url"] = src.get("homepage", "") or f"{site}/Calendar.aspx"
            events.append(e)
    return events


# --- PrimeGov public portals (upcoming meetings list) ---

def normalize_primegov(src, rows, tz):
    tenant = src["tenant"]
    events = []
    for r in rows:
        raw = (r.get("dateTime") or "")[:19]
        if not raw:
            continue
        start = datetime.fromisoformat(raw).replace(tzinfo=tz)  # local wall-clock time
        agenda = ""
        for d in r.get("documentList") or []:
            if d.get("templateName", "").lower().endswith("agenda") and d.get("templateId"):
                agenda = f"https://{tenant}.primegov.com/Portal/Meeting?meetingTemplateId={d['templateId']}"
                break
        events.append(make_event(
            src, title=(r.get("title") or "Public meeting").strip(), start=start,
            location=r.get("location") or "",
            url=f"https://{tenant}.primegov.com/public/portal",
            agenda_url=agenda, uid=str(r.get("id", "")),
        ))
    return events


def fetch_primegov(src, start_day, end_day, tz):
    rows = get(f"https://{src['tenant']}.primegov.com/api/v2/PublicPortal/ListUpcomingMeetings").json()
    return normalize_primegov(src, rows, tz)


# --- CivicWeb (iCompass) portals: the meeting schedule's JSON service ---

def normalize_civicweb(src, rows, tz):
    tenant = src["tenant"]
    events = []
    for r in rows:
        raw = r.get("MeetingDateTime") or ""
        if not raw:
            continue
        start = datetime.strptime(raw[:16], "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        # Names end with the date ("Planning Commission - Dec 17 2026"); the site shows its own.
        name = re.sub(r"\s*-\s*\d{1,2} [A-Z][a-z]{2} \d{4}$|\s*-\s*[A-Z][a-z]{2} \d{1,2} \d{4}$", "", r.get("Name") or "")
        events.append(make_event(
            src, title=name or "Public meeting", start=start,
            location=r.get("MeetingLocation") or "",
            url=f"https://{tenant}.civicweb.net/Portal/MeetingInformation.aspx?Org=Cal&Id={r.get('Id')}",
            uid=str(r.get("Id", "")),
        ))
    return events


def fetch_civicweb(src, start_day, end_day, tz):
    rows = get(f"https://{src['tenant']}.civicweb.net/Services/MeetingsService.svc/meetings",
               {"from": start_day.isoformat(), "to": end_day.isoformat(), "loadmore": "false"}).json()
    return normalize_civicweb(src, rows, tz)


# --- City of Spokane council meetings (the council's own meetings page) ---
# The page lists the next couple of meetings, each as an <h5> link whose
# address carries the date, followed by "6 p.m. - Council Chambers ...".

SPOKANE_ROW = re.compile(
    r'<h5><a href="(?P<href>/citycouncil/meetings/(?P<y>\d{4})/(?P<m>\d{2})/(?P<d>\d{2})/[^"]+)">'
    r'<span[^>]*>(?P<title>[^<]+)</span></a></h5>\s*<p>(?P<info>[^<]*)</p>')


def normalize_spokane_council(src, page, tz):
    import html as htmllib
    base = "https://my.spokanecity.org"
    events = []
    for m in SPOKANE_ROW.finditer(page):
        info = htmllib.unescape(m.group("info")).strip()
        clock = parse_clock(info.replace("noon", "12 p.m."))
        place = info.split(" - ", 1)[1] if " - " in info else ""
        place = re.sub(r"^Watch [\d:]+ - ", "", place).strip().rstrip(".")
        day = date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
        events.append(make_event(
            src, title=htmllib.unescape(m.group("title")).strip(),
            start=datetime.combine(day, clock or time(0, 0), tz), all_day=clock is None,
            location=place, url=base + m.group("href"), uid=m.group("href"),
        ))
    return events


def fetch_spokane_council(src, start_day, end_day, tz):
    return normalize_spokane_council(src, get(src["url"]).text, tz)


# --- Regular schedules entered by hand ("2nd and 4th Wednesday, 2 p.m.") ---
# For public bodies that publish a standing schedule but no feed. Each event
# says it comes from the regular schedule, so people check before they go.

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
SCHEDULE_NOTE = ("From the regular meeting schedule the host publishes. Meetings can be cancelled "
                 "or moved, so check the host's page before you go.")


def schedule_dates(rule: str, start_day: date, end_day: date):
    """'2nd, 4th Wednesday' or 'last Monday' -> matching dates in the window."""
    m = re.match(r"\s*(?P<nths>[\w ,and]+?)\s+(?P<wd>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*$",
                 rule, re.I)
    if not m:
        raise ValueError(f"bad schedule rule: {rule}")
    weekday = WEEKDAYS.index(m.group("wd").lower())
    wanted = set()
    for word in re.findall(r"1st|2nd|3rd|4th|5th|first|second|third|fourth|fifth|last", m.group("nths").lower()):
        wanted.add({"1st": 1, "first": 1, "2nd": 2, "second": 2, "3rd": 3, "third": 3,
                    "4th": 4, "fourth": 4, "5th": 5, "fifth": 5, "last": -1}[word])
    day = start_day
    while day <= end_day:
        if day.weekday() == weekday:
            nth = (day.day - 1) // 7 + 1
            last = (day + timedelta(days=7)).month != day.month
            if nth in wanted or (-1 in wanted and last):
                yield day
        day += timedelta(days=1)


def fetch_schedule(src, start_day, end_day, tz):
    events = []
    for mtg in src["meetings"]:
        hh, mm = (int(x) for x in mtg["time"].split(":"))
        end = None
        if mtg.get("end"):
            eh, em = (int(x) for x in mtg["end"].split(":"))
        for day in schedule_dates(mtg["when"], start_day, end_day):
            if day.month in mtg.get("skip_months", []):
                continue
            start = datetime.combine(day, time(hh, mm), tz)
            if mtg.get("end"):
                end = datetime.combine(day, time(eh, em), tz)
            events.append(make_event(
                src, title=mtg["title"], start=start, end=end,
                location=mtg.get("location", ""), url=mtg.get("url", ""),
                note=SCHEDULE_NOTE + (" " + mtg["note"] if mtg.get("note") else ""),
                uid=f"{mtg['title']}|{day.isoformat()}", category=mtg.get("category", ""),
            ))
    return events


CONNECTORS = {"legistar": fetch_legistar, "civicclerk": fetch_civicclerk, "ics": fetch_ics,
              "bibliocommons": fetch_bibliocommons, "municode": fetch_municode, "mec_rss": fetch_mec_rss,
              "govaccess_rss": fetch_govaccess_rss, "civicplus": fetch_civicplus,
              "primegov": fetch_primegov, "civicweb": fetch_civicweb,
              "spokane_council": fetch_spokane_council, "schedule": fetch_schedule}


# ---------- outputs ----------

def ics_escape(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def write_ics(events, path: Path, stamp: datetime, name: str = "Washington"):
    utc = ZoneInfo("UTC")
    fmt = "%Y%m%dT%H%M%SZ"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//CivicsWA//Public meetings//EN",
             f"X-WR-CALNAME:CivicsWA {name}"]
    for e in events:
        start = datetime.fromisoformat(e["start"])
        lines += ["BEGIN:VEVENT", f"UID:{e['id']}@civicswa", f"DTSTAMP:{stamp.astimezone(utc).strftime(fmt)}"]
        if e["all_day"]:
            lines += [f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}"]
        else:
            end = datetime.fromisoformat(e["end"]) if e["end"] else start + timedelta(hours=1)
            lines += [f"DTSTART:{start.astimezone(utc).strftime(fmt)}",
                      f"DTEND:{end.astimezone(utc).strftime(fmt)}"]
        summary = ("CANCELLED: " if e["cancelled"] else "") + f"{e['title']} ({e['host']})"
        lines += [f"SUMMARY:{ics_escape(summary)}", f"LOCATION:{ics_escape(e['location'])}",
                  f"URL:{e['url']}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")


def apply_source_rules(src, events):
    """Per-source tidying set in sources.yml.

    drop_uncategorized: leave out anything that doesn't read as a meeting or
      hearing (office closures, conferences, staff events on a shared calendar).
    default_category: for feeds that only carry meetings, file the ones whose
      names don't say so (e.g. "LEOFF 1") under this category.
    """
    if src.get("default_category"):
        for e in events:
            if e["category"] == "other":
                e["category"] = src["default_category"]
    if src.get("drop_uncategorized"):
        events = [e for e in events if e["category"] != "other"]
    return events


def county_slug(county: str) -> str:
    return re.sub(r"[^a-z]+", "-", county.lower()).strip("-")


def load_previous_status() -> dict:
    try:
        return {s["id"]: s for s in json.loads((OUT / "status.json").read_text())["sources"]}
    except Exception:
        return {}


def main() -> int:
    cfg = yaml.safe_load((Path(__file__).parent / "sources.yml").read_text())
    tz = ZoneInfo(cfg["timezone"])
    now = datetime.now(tz)
    start_day, end_day = now.date(), now.date() + timedelta(days=cfg["window_days"])
    previous = load_previous_status()
    try:
        old_events = json.loads((OUT / "events.json").read_text())["events"]
    except Exception:
        old_events = []

    all_events, statuses = [], []
    for src in cfg["sources"]:
        status = {"id": src["id"], "name": src["name"], "homepage": src.get("homepage", ""),
                  "county": src.get("county", "Thurston"),
                  "checked": now.isoformat(timespec="seconds")}
        try:
            found = CONNECTORS[src["type"]](src, start_day, end_day, tz)
            found = [e for e in found if start_day <= datetime.fromisoformat(e["start"]).date() <= end_day]
            found = apply_source_rules(src, found)
            status.update(ok=True, count=len(found), last_success=status["checked"], error="")
            # A source that answers but lists nothing is suspicious, not fine.
            status["state"] = "ok" if found else "quiet"
        except Exception as exc:  # one bad source must not sink the rest
            # Keep showing what we had, so a one-night outage doesn't blank a city.
            found = [e for e in old_events if e["source"] == src["id"]
                     and datetime.fromisoformat(e["start"]).date() >= start_day]
            status.update(ok=False, count=len(found), state="failing",
                          last_success=previous.get(src["id"], {}).get("last_success", ""),
                          error=f"{type(exc).__name__}: {exc}"[:300])
            print(f"[warn] {src['id']}: {status['error']}", file=sys.stderr)
        all_events.extend(found)
        statuses.append(status)

    unique = {e["id"]: e for e in all_events}
    events = sorted(unique.values(), key=lambda e: (e["start"], e["host"], e["title"]))

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = now.isoformat(timespec="seconds")
    (OUT / "events.json").write_text(json.dumps({"generated": stamp, "events": events}, indent=1))
    (OUT / "status.json").write_text(json.dumps({"generated": stamp, "sources": statuses}, indent=1))
    # One subscribable calendar per county, plus a statewide one. The original
    # data/thurston.ics address stays so existing subscriptions keep working.
    (OUT / "ics").mkdir(exist_ok=True)
    write_ics(events, OUT / "ics" / "washington.ics", now, "Washington")
    for county in sorted({e["county"] for e in events} | {s["county"] for s in statuses}):
        mine = [e for e in events if e["county"] == county]
        write_ics(mine, OUT / "ics" / f"{county_slug(county)}.ics", now, f"{county} County")
    write_ics([e for e in events if e["county"] == "Thurston"], OUT / "thurston.ics", now, "Thurston County")

    for s in statuses:
        print(f"{s['state']:8} {s['count']:4}  {s['name']}")
    print(f"total {len(events)} events through {end_day}")
    # Fail the run only when every source failed, so the nightly job goes red.
    return 1 if statuses and not any(s["ok"] for s in statuses) else 0


if __name__ == "__main__":
    sys.exit(main())
