"""CivicsWA pipeline: read each public calendar source, normalize the events,
and write the files the site reads.

Outputs (in site/data/):
  events.json   upcoming events, soonest first (the full record; the next run reads it)
  calendar.json the same events, trimmed for the calendar pages (see slim_events)
  status.json   per-source health, so a quiet or broken source is visible
  thurston.ics  a subscribable calendar of everything in events.json

Run:  python pipeline/build.py
"""
from __future__ import annotations

import hashlib
import json
import re
from html import unescape as html_unescape
import sys
import threading
import time as stopwatch
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data"
CONFIG = ROOT / "pipeline" / "sources.yml"
UA = "CivicsWA-pilot/0.1 (BarNone nonprofit civic calendar; contact via barnoneinc.org)"
TIMEOUT = 45
# Sources are read in parallel so a few slow websites can't push the nightly
# run past its time limit. No single website gets more than PER_HOST
# requests at once, so shared platforms (dozens of school districts on one
# provider) are not hammered.
WORKERS = 8
PER_HOST = 2


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


# A note cancels a meeting only when it reads as a cancellation notice
# ("Cancellation Notice", "MEETING CANCELED", "This meeting has been
# cancelled"). A note that merely mentions the word ("Meetings can be
# cancelled or moved", "call to cancel your registration") does not.
NOTE_CANCELS = re.compile(
    r"^\W*(?:[\w']+\s+){0,3}cancel+(?:ed|ation)\b"
    r"|\b(?:has|have) been cancel+ed\b"
    r"|\b(?:is|are|was|were|now) cancel+ed\b", re.I)
NOTE_CONDITIONAL = re.compile(r"\bif\b[^.]{0,60}cancel", re.I)


def is_cancelled(title: str, note: str = "") -> bool:
    if re.search(r"cancel", title or "", re.I):
        return True
    note = note or ""
    return bool(NOTE_CANCELS.search(note)) and not NOTE_CONDITIONAL.search(note)


_MON = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
DATE_IN_TITLE = re.compile(
    r"^(?:\d{4}[./-]\d{1,2}[./-]\d{1,2}|" + _MON + r"\s+\d{1,2},?\s+\d{4})\s+"   # leading 2026.11.10 or December 01, 2026
    r"|\s*(?:[-–@]|\bof|\bon|\bfor)?\s*(?:(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,?\s+)?(?:\d{1,2}\s+" + _MON + r"\s+\d{4}|" + _MON + r"\s+\d{1,2},?\s+\d{4})"
    r"(?:\s*@\s*(?:\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?)?)?\s*$"                   # trailing dates, optional time
    r"|\s+\d{1,2}/\d{1,2}/\d{2,4}\s*$", re.I)                              # trailing 11/12/26


def web_url(url) -> str:
    """The address if it is a full web link, otherwise nothing."""
    url = (url or "").strip()
    return url if re.match(r"https?://\S+$", url, re.I) else ""


def make_event(src, *, title, start, end=None, all_day=False, location="", url="",
               agenda_url="", note="", uid="", category="", area="", cancelled=False):
    # A stable ID for the event (not a security use; the same inputs must give the same ID).
    fingerprint = f"{src['id']}|{uid or title}|{start.isoformat()}"
    cancelled = cancelled or is_cancelled(title, note)
    # Hosts often prefix the title ("Canceled: Board Work Session"); the site
    # shows its own Cancelled tag, so drop the prefix.
    title = re.sub(r"^[\s*]*cancel+ed[\s*]*(?:[:\-–]\s*|\s+(?=\S))", "", title or "", flags=re.I)
    title = re.sub(r"\s*[-–:(,]\s*(?:meeting\s+)?cancel+ed\s*\)?\s*$", "", title, flags=re.I)
    # The date and time are shown separately, so drop them from the title:
    # "Council Meeting - 08 Dec 2026 @ 6:00PM", "Workshop of November 16, 2026",
    # "2026.11.10 City Council Meeting", "Civil Service Commission 11/12/26".
    title = DATE_IN_TITLE.sub("", title).strip(" -–,") or title
    # Some calendars put HTML or stray separators in the location field.
    location = re.sub(r"<[^>]+>", " ", location or "")
    location = re.sub(r"^[\s\-–,]+|[\s\-–,]+$", "", " ".join(location.split()))
    # Room-booking codes ("ATR_Board_Rm_110") read better with spaces, and a
    # placeholder ("TBD") is no place at all.
    if "_" in location and " " not in location:
        location = location.replace("_", " ")
    if re.fullmatch(r"t\.?b\.?[da]\.?|to be (?:determined|announced)|n/?a|none", location, re.I):
        location = ""
    # Some feeds give a partial address ("/common/modules/..."), which is not a
    # link anyone can open. Fall back to the host's own page.
    url = web_url(url) or web_url(src.get("homepage", ""))
    agenda_url = web_url(agenda_url)
    return {
        "id": hashlib.sha256(fingerprint.encode()).hexdigest()[:12],
        "title": " ".join(html_unescape(title or "").split()),
        "host": src["name"],
        "source": src["id"],
        "area": area or src["area"],
        "county": src.get("county", "Thurston"),
        "category": category or categorize(title),
        "start": start.isoformat(),
        "end": end.isoformat() if end else None,
        "all_day": all_day,
        "location": " ".join((location or "").split()),
        "url": url,
        "agenda_url": agenda_url,
        "note": " ".join((note or "").split()),
        "cancelled": cancelled,
    }


_host_slots: dict = {}
_host_guard = threading.Lock()


def host_slot(url):
    host = urlsplit(url).netloc.lower()
    with _host_guard:
        return _host_slots.setdefault(host, threading.BoundedSemaphore(PER_HOST))


def get(url, params=None):
    import requests
    with host_slot(url):
        resp = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp


# ---------- agenda highlights ----------
# For systems that publish agenda items, show the few substantive ones so a
# listing says what is being decided, not just that a meeting exists.

PROCEDURAL = re.compile(
    r"^(call(ed)? to order|roll call|pledge|flag salute|land acknowledg|we, the city|approval of (the )?"
    r"(agenda|minutes|.*minutes$)|approve the (agenda|minutes)|adopt(ion of)? (the )?(agenda|minutes)|"
    r"public comment|citizen comment|adjourn|recess|good of the order|executive session|vote requested|"
    r"hybrid meeting|connecting to|webinar|see attached|this meeting (has been|will be)|properly noticed|"
    r"item no|agenda review|adoption of (the )?(introduction|consent|agenda)|join (the )?(meeting|zoom)|"
    r"the .{0,80}meeting scheduled for|the public can (participate|attend|watch)|excused absences|"
    r"confirm(ation of)? (the )?agenda|minutes of|calendar ?/ ?correspondence|page break|reminder|"
    r"record of hearing|approval of (the )?.*(agenda|minutes)$|(city )?council action updates?|"
    r"(intergovernmental|outside|committee|staff|board|member|commissioner)s?(/[a-z ]+)? (committee )?updates?$|"
    r"administrative items|public access time|issue briefing$)", re.I)
TIME_PREFIX = re.compile(r"^\d{1,2}(:\d{2})?\s*[ap]\.?m\.?(\s*[–-]\s*\d{1,2}(:\d{2})?\s*[ap]\.?m\.?)?\s*[–:-]?\s*", re.I)
# Section headings that only count as procedure when they are the whole item.
HEADING = re.compile(
    r"^((regular |special )?minutes|public (comment|testimony)|announcements?|(staff )?reports?|"
    r"(chair|director|commissioners?|council ?members?|mayor|manager|staff|council)('?s)?( (report|comments|update)s?)?|"
    r"other (topics|business|items)|upcoming|consent (agenda|calendar)|introduction and referral( calendar)?|"
    r"items of interest|correspondence|(unfinished|old|new) business|business items|action items|"
    r"discussion items|public hearings?|work session|study session|introductions?( of members)?|committee discussion|wrap[- ]up|next steps|closing remarks|welcome( and introductions)?)$", re.I)
HIGHLIGHT_WINDOW_DAYS = 21
HIGHLIGHT_COUNT = 3


def clean_item(text: str) -> str:
    import html as htmllib
    text = re.split(r"<br\s*/?>|\r|\n", text or "", maxsplit=1)[0]
    text = htmllib.unescape(re.sub(r"<[^>]+>", " ", text))
    text = " ".join(text.replace("*", " ").split()).strip(" :.-")
    text = TIME_PREFIX.sub("", text)
    if len(text) > 140:
        text = text[:140].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return text


def pick_highlights(titles):
    picked = []
    for t in titles:
        t = clean_item(t)
        shouting = t.isupper() and len(t.split()) <= 4 and not re.search(r"\d", t)  # an all-caps heading
        if len(t) < 6 or shouting or PROCEDURAL.match(t) or HEADING.match(t) or t in picked:
            continue
        picked.append(t)
    return picked


def add_highlights(event, titles):
    items = pick_highlights(titles)
    if items:
        event["highlights"] = items[:HIGHLIGHT_COUNT]
        event["highlights_more"] = max(0, len(items) - HIGHLIGHT_COUNT)


def soon(event, start_day):
    return datetime.fromisoformat(event["start"]).date() <= start_day + timedelta(days=HIGHLIGHT_WINDOW_DAYS)


def legistar_highlights(src, events, start_day):
    for e in events:
        if e["cancelled"] or not soon(e, start_day) or not e.get("_eid"):
            continue
        try:
            items = get(f"https://webapi.legistar.com/v1/{src['client']}/events/{e['_eid']}/eventitems",
                        {"AgendaNote": 1, "MinutesNote": 0, "Attachments": 0}).json()
        except Exception as exc:
            print(f"[info] {src['id']}: no agenda items for {e['_eid']}: {exc}", file=sys.stderr)
            continue
        # When an agenda has items tied to legislative files (bills, resolutions,
        # hearings), those are the decisions; the rest are headings and notices.
        filed = [i for i in items if i.get("EventItemMatterFile")]
        items = sorted(filed or items, key=lambda i: i.get("EventItemAgendaSequence") or 0)
        add_highlights(e, [i.get("EventItemTitle") or "" for i in items
                           if (i.get("EventItemMatterType") or "").lower() != "minutes"])


def civicclerk_highlights(src, events, start_day):
    for e in events:
        if e["cancelled"] or not soon(e, start_day) or not e.get("_agenda"):
            continue
        try:
            meeting = get(f"https://{src['tenant']}.api.civicclerk.com/v1/Meetings/{e['_agenda']}").json()
        except Exception as exc:
            print(f"[info] {src['id']}: no agenda for {e['_agenda']}: {exc}", file=sys.stderr)
            continue
        if not meeting.get("agendaIsPublish"):
            continue  # draft agendas are not public yet
        titles = []

        def walk(items, section=""):
            for i in items or []:
                name = i.get("agendaObjectItemName") or ""
                if i.get("isSection"):
                    walk(i.get("childItems"), name)
                    continue
                if re.search(r"report|minutes|consent", section, re.I):
                    continue
                titles.append(name)
                walk(i.get("childItems"), section)

        walk(meeting.get("items"))
        add_highlights(e, titles)


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
        events[-1]["_eid"] = r.get("EventId")
    return events


def fetch_legistar(src, start_day, end_day, tz):
    flt = (f"EventDate ge datetime'{start_day.isoformat()}' and "
           f"EventDate le datetime'{end_day.isoformat()}'")
    rows = get(f"https://webapi.legistar.com/v1/{src['client']}/events",
               {"$filter": flt, "$orderby": "EventDate"}).json()
    events = normalize_legistar(src, rows, tz)
    legistar_highlights(src, events, start_day)
    return events


# Some CivicClerk portals name events only by date and kind ("November 17,
# 2026, Meeting") and keep the body in the category ("City Council").
CIVICCLERK_LEADING_DATE = re.compile(r"^\s*[A-Z][a-z]+\.? \d{1,2},? \d{4},?\s*[-–:]?\s*")
GENERIC_MEETING = re.compile(
    r"^(?:(?:regular|special|study|work|joint|emergency)\s+)*(?:meeting|session|workshop|hearing)s?$", re.I)
# The portal's own event type, left in the name field: it says nothing about the meeting.
CIVICCLERK_EVENT_TYPE = re.compile(r"^(?:(?:one[- ]time|special|recurring)\s+)?event$", re.I)


def civicclerk_title(r) -> str:
    name = (r.get("eventName") or "").strip()
    body = (r.get("categoryName") or "").strip()
    rest = CIVICCLERK_LEADING_DATE.sub("", name).strip()
    if body and CIVICCLERK_EVENT_TYPE.match(rest) and not CIVICCLERK_EVENT_TYPE.match(body):
        return body
    if body and (not rest or GENERIC_MEETING.match(rest)) and body.lower() not in name.lower():
        return f"{body} {rest}".strip()
    return name or body or "Public meeting"


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
        # Link the posted agenda itself when there is one.
        agenda = next((f for f in r.get("publishedFiles") or []
                       if (f.get("type") or "").lower() == "agenda" and f.get("fileId")), None)
        events.append(make_event(
            src,
            agenda_url=f"https://{tenant}.portal.civicclerk.com/event/{r['id']}/files/agenda/{agenda['fileId']}" if agenda else "",
            title=civicclerk_title(r),
            start=start,
            location=place,
            url=f"https://{tenant}.portal.civicclerk.com/event/{r['id']}/overview",
            note=r.get("eventDescription") or "",
            uid=str(r["id"]),
        ))
        events[-1]["_agenda"] = r.get("agendaId")
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
    events = normalize_civicclerk(src, rows, tz)
    civicclerk_highlights(src, events, start_day)
    return events


def separate_shared_uids(cal):
    """Some feeds give many separate meetings one UID (Bellingham's council
    meetings all share one). Calendar readers treat a repeated UID as edits
    of one event and keep a single copy, so give each its own UID. Repeating
    series (RRULE) and their changed dates (RECURRENCE-ID) are left alone."""
    import collections
    singles = [c for c in cal.walk("VEVENT") if not c.get("RRULE") and not c.get("RECURRENCE-ID")]
    counts = collections.Counter(str(c.get("UID", "")) for c in singles)
    for comp in singles:
        uid = str(comp.get("UID", ""))
        if uid and counts[uid] > 1 and comp.get("DTSTART"):
            del comp["UID"]
            comp.add("UID", f"{uid}#{comp['DTSTART'].to_ical().decode()}")


def normalize_ics(src, ics_text, start_day, end_day, tz):
    import icalendar
    import recurring_ical_events

    cal = icalendar.Calendar.from_ical(ics_text)
    separate_shared_uids(cal)
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
    content = get(src["url"]).content
    if not content.strip() and "ical=1" in src["url"]:
        # WordPress sites running The Events Calendar ("?ical=1" feeds) sometimes
        # return a blank page for the iCal export while the plugin's own events
        # API still answers (Gold Bar, Nov 2026). Read that instead.
        return fetch_events_calendar_api(src, start_day, end_day, tz)
    return normalize_ics(src, content, start_day, end_day, tz)


def fetch_events_calendar_api(src, start_day, end_day, tz):
    """Upcoming events from a WordPress site's The Events Calendar REST API."""
    parts = urlsplit(src["url"])
    api = f"{parts.scheme}://{parts.netloc}/wp-json/tribe/events/v1/events"
    events = []
    for page in range(1, 11):  # 50 a page; a city calendar never needs more
        reply = get(api, params={"start_date": f"{start_day.isoformat()} 00:00:00",
                                 "end_date": f"{end_day.isoformat()} 23:59:59",
                                 "per_page": 50, "page": page})
        data = reply.json()
        events += normalize_events_calendar_api(src, data.get("events") or [], tz)
        if page >= int(data.get("total_pages") or 1):
            break
    return events


def normalize_events_calendar_api(src, items, tz):
    def when(item, local_key, utc_key):
        if item.get(utc_key):
            return datetime.fromisoformat(item[utc_key]).replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
        if item.get(local_key):
            return datetime.fromisoformat(item[local_key]).replace(tzinfo=tz)
        return None

    events = []
    for item in items:
        start = when(item, "start_date", "utc_start_date")
        title = re.sub(r"<[^>]+>", " ", item.get("title") or "")
        if not start or not title.strip():
            continue
        all_day = bool(item.get("all_day"))
        venue = item.get("venue") if isinstance(item.get("venue"), dict) else {}
        place = ", ".join(x for x in (venue.get("venue"), venue.get("address"), venue.get("city")) if x)
        events.append(make_event(
            src,
            title=title,
            start=start.replace(hour=0, minute=0, second=0) if all_day else start,
            end=None if all_day else when(item, "end_date", "utc_end_date"),
            all_day=all_day,
            location=html_unescape(place),
            url=item.get("url") or "",
            uid=str(item.get("id") or ""),
        ))
    return events


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
    # Branch events for a county, and/or keyword searches (a library system's
    # board of trustees, which meets across its region).
    queries = ([{"locations": ",".join(src["locations"])}] if src.get("locations") else []) + \
        [{"q": q} for q in src.get("searches", [])]
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

# Names end with the date in one of several forms: "- Dec 17 2026",
# "- 17 Dec 2026", "- Jan 26, 2027", "- November 16, 2026".
CIVICWEB_DATE = re.compile(r"\s*-\s*(?:\d{1,2} [A-Z][a-z]{2} \d{4}|[A-Z][a-z]+\.? \d{1,2},? \d{4})(?=\s*(?:-|$))")


def civicweb_base(src):
    # Diligent Community portals (school boards) run the same software as
    # CivicWeb under their own host names.
    return (src.get("base") or f"https://{src['tenant']}.civicweb.net").rstrip("/")


def normalize_civicweb(src, rows, tz):
    base = civicweb_base(src)
    events = []
    for r in rows:
        raw = r.get("MeetingDateTime") or ""
        if raw:
            start = datetime.strptime(raw[:16], "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        elif r.get("MeetingDate"):
            # Some portals leave the combined field blank and give the day and
            # the clock time separately ("2026-10-29", "01:30 PM").
            clock = parse_clock(r.get("MeetingTime") or "")
            start = datetime.combine(date.fromisoformat(r["MeetingDate"][:10]), clock or time(0, 0), tz)
        else:
            continue
        # Names end with the date ("Planning Commission - Dec 17 2026"); the site shows its own.
        name = CIVICWEB_DATE.sub("", r.get("Name") or "").strip()
        events.append(make_event(
            src, title=name or "Public meeting", start=start,
            location=r.get("MeetingLocation") or "",
            url=f"{base}/Portal/MeetingInformation.aspx?Org=Cal&Id={r.get('Id')}",
            # "Published" means the agenda is posted on the meeting's page.
            agenda_url=f"{base}/Portal/MeetingInformation.aspx?Org=Cal&Id={r.get('Id')}" if r.get("Published") else "",
            uid=str(r.get("Id", "")),
        ))
    return events


def fetch_civicweb(src, start_day, end_day, tz):
    rows = get(f"{civicweb_base(src)}/Services/MeetingsService.svc/meetings",
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
# For public bodies that publish a standing schedule but no feed: either a
# rule ("when") or the adopted list of dates ("dates"). Each event
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


def nth_weekday(year, month, weekday, n):
    """n-th weekday of a month (n = -1 for the last one)."""
    if n > 0:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    last = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1))
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def wa_holidays(year):
    """Washington legal holidays (RCW 1.16.050), with weekend dates observed."""
    fixed = [date(year, 1, 1), date(year, 6, 19), date(year, 7, 4), date(year, 11, 11), date(year, 12, 25)]
    days = set()
    for d in fixed:
        days.add(d - timedelta(days=1) if d.weekday() == 5 else d + timedelta(days=1) if d.weekday() == 6 else d)
    thanksgiving = nth_weekday(year, 11, 3, 4)
    days |= {nth_weekday(year, 1, 0, 3), nth_weekday(year, 2, 0, 3), nth_weekday(year, 5, 0, -1),
             nth_weekday(year, 9, 0, 1), thanksgiving, thanksgiving + timedelta(days=1)}
    return days


def next_business_day(day):
    """RCW 42.30.070: a regular meeting that falls on a holiday is held on the next business day."""
    while day.weekday() >= 5 or day in wa_holidays(day.year):
        day += timedelta(days=1)
    return day


HOLIDAY_NOTE = ("The regular date falls on a holiday, so state law moves the meeting to the next "
                "business day. The host may set a different date.")


def schedule_events(src, start_day, end_day, tz):
    events = []
    for mtg in src["meetings"]:
        hh, mm = (int(x) for x in mtg["time"].split(":"))
        end = None
        if mtg.get("end"):
            eh, em = (int(x) for x in mtg["end"].split(":"))
        if mtg.get("dates"):
            # An adopted list of meeting dates, for bodies whose schedule
            # doesn't follow one rule.
            days = [d if isinstance(d, date) else date.fromisoformat(str(d)) for d in mtg["dates"]]
            days = [d for d in days if start_day <= d <= end_day]
        else:
            days = schedule_dates(mtg["when"], start_day, end_day)
        for day in days:
            if mtg.get("shift_days"):
                # e.g. a work session held the Monday of the week of a
                # 2nd and 4th Wednesday meeting: rule "2nd, 4th Wednesday", shift_days -2.
                day += timedelta(days=int(mtg["shift_days"]))
            if day.month in mtg.get("skip_months", []) or str(day) in [str(d) for d in mtg.get("skip_dates", [])]:
                continue
            moved = False
            if mtg.get("monday_holiday_shift") and day - timedelta(days=day.weekday()) in wa_holidays(day.year):
                # "When a holiday falls on Monday, the meeting is held on Wednesday."
                day, moved = day + timedelta(days=int(mtg["monday_holiday_shift"])), True
            elif not mtg.get("dates") and day in wa_holidays(day.year):
                if mtg.get("holidays") == "skip":  # bodies that don't meet on holidays at all
                    continue
                day, moved = next_business_day(day), True
            start = datetime.combine(day, time(hh, mm), tz)
            if mtg.get("end"):
                end = datetime.combine(day, time(eh, em), tz)
            events.append(make_event(
                src, title=mtg["title"], start=start, end=end,
                location=mtg.get("location", ""), url=mtg.get("url", ""),
                note=SCHEDULE_NOTE + (" " + HOLIDAY_NOTE if moved else "") + (" " + mtg["note"] if mtg.get("note") else ""),
                uid=f"{mtg['title']}|{day.isoformat()}", category=mtg.get("category", ""),
            ))
    return events


# --- BoardDocs snapshot ---
# BoardDocs refuses GitHub's servers, so a small job on a volunteer's computer
# (tools/boarddocs/) reads each board's meeting list nightly and pushes it to
# the boarddocs-data branch; the workflow copies it to pipeline/boarddocs.json.
# A schedule entry with a `boarddocs:` site name uses those posted meetings up
# to the last date posted, and its own pattern after that. With no snapshot, or
# one more than BOARDDOCS_MAX_AGE_DAYS old, the pattern is used alone.

BOARDDOCS_SNAPSHOT = ROOT / "pipeline" / "boarddocs.json"
BOARDDOCS_MAX_AGE_DAYS = 10
BD_KINDS = [(r"retreat", "Retreat"), (r"special", "Special Meeting"), (r"study", "Study Session"),
            (r"work\s*session", "Work Session"), (r"workshop", "Workshop"), (r"business", "Business Meeting"),
            (r"regular|board meeting|board of directors", "Regular Meeting")]
BD_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\b\.?", re.I)
BD_PLACE = re.compile(r"\b\d+\w?\s+.*\b(?:st|street|ave|avenue|rd|road|way|hwy|highway|blvd|dr|drive|ln|lane)\b"
                      r"|librar|board\s*room|\broom\b|cent(?:er|re)|office|\bhall\b|cafeteria|commons|gym", re.I)
BD_NOT_PLACE = re.compile(r"zoom|webinar|passcode|share|agenda|minutes|clipboard|disabilit|livestream|youtube", re.I)
BD_DATE_LINE = re.compile(r"(?:mon|tues|wednes|thurs|fri|satur|sun)day,?\s+\w+\s+\d{1,2},\s+\d{4}", re.I)
_bd_cache: dict = {}


def boarddocs_snapshot(now=None):
    if "snap" not in _bd_cache:
        snap = None
        try:
            snap = json.loads(BOARDDOCS_SNAPSHOT.read_text())
            age = (now or datetime.now(ZoneInfo("UTC"))) - datetime.fromisoformat(snap["fetched_at"])
            if age > timedelta(days=BOARDDOCS_MAX_AGE_DAYS):
                snap = None
        except (OSError, ValueError, KeyError, TypeError):
            snap = None
        _bd_cache["snap"] = snap
    return _bd_cache["snap"]


def boarddocs_meeting(src, m, tz):
    """One posted BoardDocs meeting as an event, or None if it isn't a meeting."""
    slug = src["boarddocs"]
    name = " ".join(html_unescape(m.get("name") or "").split())
    lines = [" ".join(html_unescape(x).split()) for x in (m.get("header") or "").split("\n")]
    lines = [x for x in lines if x]
    day = datetime.strptime(m["date"], "%Y%m%d").date()
    if re.search(r"graduation|diplomas|commencement", " ".join([name] + lines[:12]), re.I):
        return None  # board members handing out diplomas, not a business meeting
    kind = next((label for pat, label in BD_KINDS if re.search(pat, name, re.I)), "")
    if not kind:
        if not re.search(r"meeting|session", name, re.I):
            return None  # graduations, tours and the like
        kind = "Meeting"
    title = f"School Board {kind}" if kind != "Meeting" else name[:90]
    # The time: in the title ("Regular Meeting - 6:00pm"), else in the header.
    clock = BD_TIME.search(name) or next((t for t in map(BD_TIME.search, lines) if t), None)
    pattern = next((mt for mt in src["meetings"] if kind.split()[0].lower() in mt["title"].lower()), src["meetings"][0])
    if clock:
        hh = int(clock.group(1)) % 12 + (12 if clock.group(3).lower() == "p" else 0)
        mm = int(clock.group(2) or 0)
    else:
        hh, mm = (int(x) for x in pattern["time"].split(":"))
    place = next((x for x in lines if BD_PLACE.search(x) and not BD_NOT_PLACE.search(x)
                  and not BD_DATE_LINE.search(x) and x != name and len(x) < 140), "")
    place = re.sub(r"^(?:location(?: of meeting)?|place)\s*:\s*", "", place, flags=re.I)
    # "Ferndale School District No. 502 School Board Regular Meeting, 5780 Hendrickson Ave, ..."
    place = re.sub(r"^\D[^,]*(?:meeting|session)[^,]*,\s*(?=\d)", "", place, flags=re.I)
    if place.isupper():
        place = place.title()
    return make_event(
        src, title=title, start=datetime.combine(day, time(hh, mm), tz),
        location=place or pattern.get("location", ""),
        url=f"https://go.boarddocs.com/wa/{slug}/Board.nsf/Public",
        uid=f"boarddocs-{m.get('unique') or m['date'] + title}",
        cancelled=bool(re.search(r"cancel+ed|postponed", name, re.I)),
    )


def fetch_schedule(src, start_day, end_day, tz, snapshot=None):
    pattern = schedule_events(src, start_day, end_day, tz)
    snap = snapshot if snapshot is not None else (boarddocs_snapshot() if src.get("boarddocs") else None)
    board = (snap or {}).get("boards", {}).get(src.get("boarddocs") or "") or {}
    if not board.get("ok"):
        return pattern
    fetched = datetime.fromisoformat(snap["fetched_at"]).astimezone(tz).date()
    posted = [m for m in board.get("meetings", []) if m.get("date")]
    horizon = max([fetched] + [datetime.strptime(m["date"], "%Y%m%d").date() for m in posted])
    events = [e for m in posted if start_day <= datetime.strptime(m["date"], "%Y%m%d").date() <= end_day
              for e in [boarddocs_meeting(src, m, tz)] if e]
    return events + [e for e in pattern if datetime.fromisoformat(e["start"]).date() > horizon]


# --- Washington State Legislature committee meetings (official web services) ---

WSL = "https://wslwebservices.leg.wa.gov/CommitteeMeetingService.asmx"


def wsl_text(node, name):
    for child in node.iter():
        if local(child.tag) == name:
            return (child.text or "").strip()
    return ""


def normalize_wsl_meetings(src, xml_text, tz):
    import xml.etree.ElementTree as ET
    events = []
    for m in ET.fromstring(xml_text).iter():
        if local(m.tag) != "CommitteeMeeting":
            continue
        names = []
        for c in m.iter():
            if local(c.tag) != "Committee":
                continue
            name, agency = wsl_text(c, "Name"), wsl_text(c, "Agency")
            names.append(f"{agency} {name}" if agency in ("House", "Senate") and not name.startswith(agency) else name)
        raw = wsl_text(m, "Date")
        if not raw:
            continue
        start = datetime.fromisoformat(raw[:19]).replace(tzinfo=tz)
        agenda = wsl_text(m, "AgendaId")
        room, building = wsl_text(m, "Room"), wsl_text(m, "Building")
        # Committees sometimes meet away from the Capitol (a convention center,
        # a community college). Only add "Olympia" for Capitol campus buildings.
        on_campus = not building or re.search(r"cherberg|o'brien|o.brien|legislative building|pritchard|newhouse|capitol", building, re.I)
        place = ", ".join(p for p in [room, building, "Olympia" if on_campus else ""] if p)
        title = " and ".join(n for n in names if n) or "Legislative committee meeting"
        if wsl_text(m, "CommitteeType") and wsl_text(m, "CommitteeType") != "Full Committee":
            title += f" ({wsl_text(m, 'CommitteeType')})"
        e = make_event(
            src, title=title, start=start, location=place,
            url=f"https://app.leg.wa.gov/committeeschedules/Home/Agenda/{agenda}" if agenda else src["homepage"],
            note=wsl_text(m, "Notes"), uid=agenda or title,
            category="legislature", cancelled=wsl_text(m, "Cancelled").lower() == "true",
        )
        e["_agenda"] = agenda
        events.append(e)
    return events


def wsl_items(xml_text):
    """Agenda items as 'Public hearing: HB 1234 – Concerning ...' or plain work-session topics."""
    import xml.etree.ElementTree as ET
    out, hearing, bills = [], False, []
    for i in ET.fromstring(xml_text).iter():
        if local(i.tag) != "CommitteeMeetingItem":
            continue
        desc = wsl_text(i, "ItemDescription").rstrip(".")
        bill = wsl_text(i, "BillId")
        kind = wsl_text(i, "HearingTypeDescription")
        hearing = hearing or kind.lower().startswith("public hearing")
        text = f"{bill} – {desc}" if bill else desc
        if kind and kind.lower() not in ("work session", "agenda", "other"):
            text = f"{kind}: {text}"
        out.append(text)
        if bill and not any(b["id"] == bill for b in bills):
            bills.append({"id": bill, "about": desc[:160], "kind": kind})
    return out, hearing, bills


# Topics for following the Legislature by subject. A committee's name is the
# strongest signal (Law & Justice hears criminal legal bills); a bill's own
# description adds the rest. Matching is by keyword, so it's a guide, not a
# classification: the site says so.
TOPIC_WORDS = [
    ("justice", r"crim|justice|judiciary|public safety|community safety|sentenc|prison|\bjails?\b|correction|police|law enforcement|firearm|weapon|offender|felon|incarcerat|\bcourts?\b|judge|judicial|juvenile|parole|probation|reentry|\bbail\b|prosecut|public defense|victim|impaired driving|controlled substance|restitution|community custody|clemency|pardon|detention|warrant|legal financial obligation"),
    ("housing", r"housing|homeless|tenant|landlord|\brent|evict|zoning|dwelling|mobile home|manufactured home|condominium|residential"),
    ("education", r"school|student|teacher|educat|college|universit|tuition|early learning|child care|childcare|apprentice|higher ed|postsecondary"),
    ("health", r"health|medical|hospital|behavioral|\bmental|substance use|opioid|fentanyl|medicaid|pharma|prescription|nurs|physician|long-term care|long term care|dental|disease|vaccin|overdose"),
    ("elections", r"election|ballot|\bvot|campaign|redistrict|initiative|referend|public records|open public meeting|state government|ethics|lobby|secretary of state|civic"),
    ("environment", r"environment|climate|energy|electric|utilit|carbon|emission|pollut|water|salmon|wildlife|\bfish|forest|wildfire|solar|nuclear|data center|recycl|waste|agricultur|\bfarm|livestock|pesticide|natural resource|orca|shoreline|parks?\b"),
    ("transportation", r"transport|highway|\broads?\b|vehicle|driver|transit|ferr|\brail|bicycl|traffic|\btoll|aviation|airport|freight"),
    ("budget", r"\btax|budget|appropriat|revenue|fiscal|\bbonds?\b|\blevy|levies|capital budget|ways (?:&|and) means|(?<!campaign )finance|pension|retire"),
    ("labor", r"worker|employ|wage|labor|union|collective bargain|paid leave|paid family|unemployment|workplace|overtime"),
    ("families", r"child|famil|foster|human services|food assistance|disabilit|senior|aging|veteran|domestic violence|public assistance|poverty"),
    ("tribes", r"tribe|tribal|\bindian|native american|indigenous"),
    ("business", r"consumer|business|commerce|insurance|\bbank|financial|privacy|artificial intelligence|technology|broadband|cannabis|liquor|gambling|\bdata\b|trade|economic development|small business"),
    ("local", r"\bcount(?:y|ies)\b|\bcit(?:y|ies)\b|municipal|port district|special district|local government|annexation"),
]
TOPIC_RE = [(k, re.compile(r, re.I)) for k, r in TOPIC_WORDS]
# Committees that weigh the cost of nearly everything shouldn't tag every
# bill they hear as a budget bill.
FISCAL_COMMITTEE = re.compile(r"appropriations|ways (?:&|and) means|\bfinance\b|capital budget", re.I)


def topics_for(text):
    return [k for k, r in TOPIC_RE if r.search(text or "")]


def tag_legislature(e):
    """Topic keys on the meeting and on each of its bills."""
    committee = re.sub(r"\(.*?\)", "", e["title"])
    from_committee = topics_for(committee)
    found = list(from_committee)
    for b in e.get("bills", []):
        own = topics_for(b.get("about", ""))
        b["topics"] = own or ([] if FISCAL_COMMITTEE.search(committee) else from_committee)
        found += b["topics"]
    for h in e.get("highlights", []):
        found += topics_for(h)
    keys = [k for k, _ in TOPIC_WORDS]
    e["topics"] = sorted(set(found), key=keys.index)
    return e


def fetch_wsl_committees(src, start_day, end_day, tz):
    xml_text = get(f"{WSL}/GetCommitteeMeetings",
                   {"beginDate": start_day.isoformat(), "endDate": end_day.isoformat()}).text
    events = normalize_wsl_meetings(src, xml_text, tz)
    for e in events:
        if e["cancelled"] or not soon(e, start_day) or not e.get("_agenda"):
            continue
        try:
            items, hearing, bills = wsl_items(get(f"{WSL}/GetCommitteeMeetingItems", {"agendaId": e["_agenda"]}).text)
        except Exception as exc:
            print(f"[info] legislature: no items for {e['_agenda']}: {exc}", file=sys.stderr)
            continue
        add_highlights(e, items)
        if bills:
            # Every bill on the agenda, so people can search for theirs.
            e["bills"] = bills[:40]
        if hearing:
            e["note"] = ("This meeting includes a public hearing. You can sign in, send written "
                         "testimony or sign up to testify remotely through the Legislature's "
                         "Committee Sign-In page.")
    for e in events:
        tag_legislature(e)
    return events


# --- Granicus (ViewPublisher) video and agenda portals ---
# The agendas RSS lists meetings once their agendas are posted, upcoming ones
# included; the meeting date is in the title ("City Council - Nov 24, 2026")
# and pubDate carries the meeting time.

GRANICUS_TITLE = re.compile(r"^(?P<name>.*?)\s*[-–]\s*(?P<date>[A-Z][a-z]{2,8}\.? \d{1,2},? \d{4})(?:\s+(?P<clock>\d{1,2}:\d{2}\s*[AaPp]\.?[Mm]\.?))?\s*$")


def granicus_parts(item, tz):
    """Granicus writes pubDate's hour on a 12-hour clock with no AM or PM
    (a 5:30 p.m. meeting reads 05:30), so prefer <gran:pubDateParts>, whose
    yr/mo/day/hr/min attributes are the meeting's local 24-hour time."""
    for child in item:
        if local(child.tag) == "pubDateParts":
            a = child.attrib
            try:
                return datetime(int(a["yr"]), int(a["mo"]), int(a["day"]),
                                int(a.get("hr", 0)), int(a.get("min", 0)), tzinfo=tz)
            except (KeyError, ValueError):
                return None
    return None


def normalize_granicus(src, xml_text, tz):
    import html as htmllib
    from email.utils import parsedate_to_datetime
    events = []
    for item in rss_items(xml_text):
        f = fields(item)
        title = htmllib.unescape(f.get("title", "")).strip()
        m = GRANICUS_TITLE.match(title)
        when = granicus_parts(item, tz)
        if when is None and f.get("pubDate"):
            try:
                when = parsedate_to_datetime(f["pubDate"]).astimezone(tz)
            except (TypeError, ValueError):
                when = None
        if m:
            day = datetime.strptime(m.group("date").replace(".", "").replace(",", ""), "%b %d %Y" if len(m.group("date").split()[0].rstrip(".")) == 3 else "%B %d %Y").date()
            clock = parse_clock(m.group("clock")) if m.group("clock") else (when.time() if when and when.date() == day and when.time() != time(0, 0) else None)
            name = m.group("name")
        elif when:
            day, clock, name = when.date(), (when.time() if when.time() != time(0, 0) else None), title
        else:
            continue
        events.append(make_event(
            src, title=name, start=datetime.combine(day, clock or time(0, 0), tz), all_day=clock is None,
            url=f.get("link", ""), uid=f.get("guid") or f.get("link") or title,
        ))
    return events


def fetch_granicus(src, start_day, end_day, tz):
    xml_text = get(f"https://{src['tenant']}.granicus.com/ViewPublisherRSS.php",
                   {"view_id": src["view_id"], "mode": "agendas"}).text
    return [e for e in normalize_granicus(src, xml_text, tz)
            if start_day <= datetime.fromisoformat(e["start"]).date() <= end_day]


# --- Apptegy (Thrillshare) school district sites ---
# District calendars mix school events with board meetings, so sources keep
# only the titles their "include" pattern matches.

def normalize_apptegy(src, payload, tz):
    events = []
    for r in payload.get("events") or []:
        try:
            start = datetime.strptime(r["formatted_start"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
            end = datetime.strptime(r["formatted_end"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz) if r.get("formatted_end") else None
        except (KeyError, TypeError, ValueError):
            continue
        all_day = bool(r.get("all_day"))
        events.append(make_event(
            src, title=r.get("title") or "", start=start, end=None if all_day or end == start else end,
            all_day=all_day, location=r.get("venue") or r.get("address") or "",
            url=src.get("homepage", ""), uid=f"apptegy-{r.get('id')}-{r.get('formatted_start')}",
        ))
    return events


def fetch_apptegy(src, start_day, end_day, tz):
    events, seen = [], set()
    for page in range(1, 9):
        payload = get(f"https://thrillshare-cmsv2.services.thrillshare.com/api/v4/o/{src['org']}/cms/events",
                      {"locale": "en", "page_no": page}).json()
        batch = normalize_apptegy(src, payload, tz)
        if not batch:
            break
        for e in batch:
            day = datetime.fromisoformat(e["start"]).date()
            if e["id"] not in seen and start_day <= day <= end_day:
                seen.add(e["id"])
                events.append(e)
        if datetime.fromisoformat(batch[-1]["start"]).date() > end_day:
            break
    return events


CONNECTORS = {"legistar": fetch_legistar, "civicclerk": fetch_civicclerk, "ics": fetch_ics,
              "bibliocommons": fetch_bibliocommons, "municode": fetch_municode, "mec_rss": fetch_mec_rss,
              "govaccess_rss": fetch_govaccess_rss, "civicplus": fetch_civicplus,
              "primegov": fetch_primegov, "civicweb": fetch_civicweb,
              "spokane_council": fetch_spokane_council, "schedule": fetch_schedule,
              "wsl_committees": fetch_wsl_committees, "granicus": fetch_granicus,
              "apptegy": fetch_apptegy}


# ---------- outputs ----------

def ics_escape(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


# Fields the calendar pages fill back in when they are left out (app.js and
# hearings.js, unpack()). Keep the two lists in step.
SLIM_DEFAULTS = {"agenda_url": "", "note": "", "location": "", "url": "", "cancelled": False, "all_day": False}


def slim_events(events: list[dict]) -> list[dict]:
    """The events as the calendar pages need them, for site/data/calendar.json.
    Drops `source` (only the pipeline reads it), fields at their default value,
    and an `end` equal to `start`. The pages restore all of these on load, so
    what visitors see is unchanged."""
    out = []
    for e in events:
        slim = {k: v for k, v in e.items()
                if k != "source" and not (k in SLIM_DEFAULTS and v == SLIM_DEFAULTS[k])}
        if slim.get("end") is not None and slim.get("end") == slim.get("start"):
            del slim["end"]
        out.append(slim)
    return out


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
        lines += [f"SUMMARY:{ics_escape(summary)}", f"LOCATION:{ics_escape(e['location'])}"]
        if web_url(e["url"]):
            lines.append(f"URL:{e['url']}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")


def merge_duplicates(events):
    """Hosts sometimes post the same meeting twice (two calendar entries for
    one council meeting). Keep one per title and start time, preferring a
    cancellation notice, then the copy with an agenda, agenda items and a place."""
    def detail(e):
        # A cancellation is posted on purpose, so when one copy says cancelled
        # and its twin doesn't, the cancelled copy is the one to believe.
        return (e["cancelled"], bool(e.get("agenda_url")), len(e.get("highlights") or []),
                len(e.get("bills") or []), bool(e.get("location")), len(e.get("note") or ""))
    best, order = {}, []
    for e in events:
        # The same words in another order are the same meeting: a joint meeting
        # is often posted once per body ("Arts Council and Parks Commission
        # Joint Meeting", "Parks Commission and Arts Council Joint Meeting").
        words = frozenset(re.findall(r"[a-z0-9]+", e["title"].lower())) - {"and", "the", "of", "a"}
        key = (words or e["title"].lower(), e["start"])
        if key not in best:
            order.append(key)
            best[key] = e
        elif detail(e) > detail(best[key]):
            best[key] = e
    return [best[k] for k in order]


def apply_source_rules(src, events):
    """Per-source tidying set in sources.yml.

    include / exclude: keep only, or drop, events whose titles match a pattern
      (a district calendar that also carries school holidays and concerts).
    category: file everything from this source under one category (a school
      board's "Regular Meeting" doesn't say "school"); hearings stay hearings.
    drop_uncategorized: leave out anything that doesn't read as a meeting or
      hearing (office closures, conferences, staff events on a shared calendar).
    default_category: for feeds that only carry meetings, file the ones whose
      names don't say so (e.g. "LEOFF 1") under this category.
    """
    if src.get("include"):
        keep = re.compile(src["include"], re.I)
        events = [e for e in events if keep.search(e["title"])]
    if src.get("exclude"):
        drop = re.compile(src["exclude"], re.I)
        events = [e for e in events if not drop.search(e["title"])]
    if src.get("category"):
        for e in events:
            if e["category"] != "hearing":
                e["category"] = src["category"]
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
    cfg = yaml.safe_load(CONFIG.read_text())
    tz = ZoneInfo(cfg["timezone"])
    now = datetime.now(tz)
    start_day, end_day = now.date(), now.date() + timedelta(days=cfg["window_days"])
    previous = load_previous_status()
    try:
        old_events = json.loads((OUT / "events.json").read_text())["events"]
    except Exception:
        old_events = []

    def read(src):
        status = {"id": src["id"], "name": src["name"], "homepage": src.get("homepage", ""),
                  "county": src.get("county", "Thurston"),
                  "checked": now.isoformat(timespec="seconds")}
        began = stopwatch.monotonic()
        try:
            found = CONNECTORS[src["type"]](src, start_day, end_day, tz)
            found = [e for e in found if start_day <= datetime.fromisoformat(e["start"]).date() <= end_day]
            found = merge_duplicates(apply_source_rules(src, found))
            status.update(ok=True, count=len(found), last_success=status["checked"], error="", failing_since="")
            # A source that answers but lists nothing is suspicious, not fine.
            status["state"] = "ok" if found else "quiet"
            # Remember when it went quiet and how many meetings it last listed,
            # so a calendar that silently stops listing gets a person's attention
            # (alerts.py) instead of looking healthy forever.
            before = previous.get(src["id"], {})
            status["quiet_since"] = "" if found else (before.get("quiet_since") or now.date().isoformat())
            status["last_listed"] = now.date().isoformat() if found else before.get("last_listed", "")
            if src.get("quiet_ok"):
                status["quiet_ok"] = True
        except Exception as exc:  # one bad source must not sink the rest
            # Keep showing what we had, so a one-night outage doesn't blank a city.
            found = [e for e in old_events if e["source"] == src["id"]
                     and datetime.fromisoformat(e["start"]).date() >= start_day]
            status.update(ok=False, count=len(found), state="failing",
                          quiet_since=previous.get(src["id"], {}).get("quiet_since", ""),
                          last_listed=previous.get(src["id"], {}).get("last_listed", ""),
                          failing_since=previous.get(src["id"], {}).get("failing_since") or now.date().isoformat(),
                          last_success=previous.get(src["id"], {}).get("last_success", ""),
                          error=f"{type(exc).__name__}: {exc}"[:300])
            print(f"[warn] {src['id']}: {status['error']}", file=sys.stderr)
        # How long each source took, so a slow one is easy to spot.
        status["seconds"] = round(stopwatch.monotonic() - began, 1)
        return found, status

    all_events, statuses = [], []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for found, status in pool.map(read, cfg["sources"]):  # results stay in sources.yml order
            all_events.extend(found)
            statuses.append(status)

    for e in all_events:
        for k in [k for k in e if k.startswith("_")]:
            del e[k]
    unique = {e["id"]: e for e in all_events}
    events = sorted(unique.values(), key=lambda e: (e["start"], e["host"], e["title"]))

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = now.isoformat(timespec="seconds")
    (OUT / "events.json").write_text(json.dumps({"generated": stamp, "events": events}, indent=1))
    (OUT / "calendar.json").write_text(json.dumps({"generated": stamp, "events": slim_events(events)},
                                                  separators=(",", ":"), ensure_ascii=False))
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
        print(f"{s['state']:8} {s['count']:4} {s['seconds']:6.1f}s  {s['name']}")
    print(f"total {len(events)} events through {end_day}")
    # Fail the run only when every source failed, so the nightly job goes red.
    return 1 if statuses and not any(s["ok"] for s in statuses) else 0


if __name__ == "__main__":
    sys.exit(main())
