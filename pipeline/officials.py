"""Build site/data/officials.json: who holds each Washington legislative and
congressional seat, for the "Who represents you" lookup.

Sources (both public and meant for reuse):
  - Washington State Legislature web services (SponsorService)
  - unitedstates/congress-legislators (public-domain roster of Congress)

Never fails the nightly run: if a source is down, the last good file is kept.
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

OUT = Path(__file__).resolve().parent.parent / "site" / "data" / "officials.json"
UA = "CivicsWA-pilot/0.1 (BarNone nonprofit civic calendar; contact via barnoneinc.org)"
WSL = "https://wslwebservices.leg.wa.gov/SponsorService.asmx/GetSponsors"
CONGRESS = "https://raw.githubusercontent.com/unitedstates/congress-legislators/gh-pages/legislators-current.json"
PARTY = {"D": "Democrat", "R": "Republican"}

# SponsorService lists everyone who served at any point in the biennium, so a
# member who resigned, died or moved to the other chamber stays in the feed.
# Keep their old seat here, by biennium, so the lookup shows only the people who
# hold the seat now. Check against https://leg.wa.gov/legislators/ when a seat
# changes. Entries are (chamber, district, name as the feed spells it).
DEPARTED = {
    "2025-26": {
        ("senate", "5", "Bill Ramos"),        # died April 2025; Victoria Hunt appointed
        ("house", "5", "Victoria Hunt"),      # moved to the Senate June 2025; Zach Hall appointed
        ("house", "28", "Chris Kilduff"),     # not on the Legislature's member list (Nov 2026)
        ("senate", "34", "Joe Nguyen"),       # left January 2025; Emily Alvarado appointed
        ("house", "34", "Emily Alvarado"),    # moved to the Senate January 2025; Brianna Thomas appointed
        ("house", "41", "Tana Senn"),         # left January 2025; Janice Zahn appointed
    },
}
SEATS = {"senate": 1, "house": 2}


def term_start(year: int) -> date:
    """New legislative terms start on the second Monday in January of odd years."""
    first = date(year, 1, 1)
    first_monday = first + timedelta(days=(7 - first.weekday()) % 7)
    return first_monday + timedelta(days=7)


def biennium_for(day: date) -> str:
    """Washington's legislative biennium starts in odd years (2025-26, 2027-28), on the
    day new members are sworn in. Before that day the old biennium still holds."""
    start = day.year if day.year % 2 else day.year - 1
    if day < term_start(start):
        start -= 2
    return f"{start}-{str(start + 1)[-2:]}"


def previous_biennium(biennium: str) -> str:
    start = int(biennium[:4]) - 2
    return f"{start}-{str(start + 1)[-2:]}"


def parse_legislators(xml_text: str, departed=frozenset()) -> dict:
    """{district: {"senate": [...], "house": [...]}} from the SponsorService XML.
    Members listed in `departed` as (chamber, district, name) are left out."""
    root = ET.fromstring(xml_text)
    districts: dict[str, dict] = {}
    for member in root.iter():
        if member.tag.rsplit("}", 1)[-1] != "Member":
            continue
        f = {child.tag.rsplit("}", 1)[-1]: (child.text or "").strip() for child in member}
        chamber = f.get("Agency", "").lower()
        district = f.get("District", "").lstrip("0")
        if chamber not in ("house", "senate") or not district or not f.get("Name"):
            continue
        if (chamber, district, f["Name"]) in departed:
            continue
        districts.setdefault(district, {"senate": [], "house": []})[chamber].append({
            "name": f["Name"],
            "party": PARTY.get(f.get("Party", ""), f.get("Party", "")),
            "phone": f.get("Phone", ""),
            "email": f.get("Email", ""),
        })
    for seats in districts.values():
        for chamber in seats.values():
            chamber.sort(key=lambda m: m["name"])
    return districts


def extra_members(districts: dict) -> list[str]:
    """Districts that still list more members than seats, for the run log."""
    out = []
    for district, seats in sorted(districts.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
        for chamber, limit in SEATS.items():
            if len(seats.get(chamber, [])) > limit:
                names = ", ".join(m["name"] for m in seats[chamber])
                out.append(f"LD {district} {chamber}: {names}")
    return out


def parse_congress(rows: list, state: str = "WA") -> dict:
    out = {"senators": [], "house": {}}
    for person in rows:
        term = person["terms"][-1]
        if term.get("state") != state:
            continue
        entry = {
            "name": person["name"].get("official_full")
                    or f"{person['name'].get('first', '')} {person['name'].get('last', '')}".strip(),
            "party": term.get("party", ""),
            "phone": term.get("phone", ""),
            "url": term.get("url", ""),
        }
        if term["type"] == "sen":
            out["senators"].append(entry)
        else:
            out["house"][str(term.get("district"))] = entry
    out["senators"].sort(key=lambda m: m["name"])
    return out


def get(url, params=None):
    import requests
    resp = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=45)
    resp.raise_for_status()
    return resp


def main() -> int:
    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    try:
        previous = json.loads(OUT.read_text())
    except Exception:
        previous = {}
    data = {"generated": now.isoformat(timespec="seconds"),
            "biennium": previous.get("biennium", ""),
            "legislators": previous.get("legislators", {}),
            "congress": previous.get("congress", {"senators": [], "house": {}})}

    try:
        biennium = biennium_for(now.date())
        found = parse_legislators(get(WSL, {"biennium": biennium}).text, DEPARTED.get(biennium, frozenset()))
        if not found:  # a new biennium's roster can be empty until members are sworn in
            biennium = previous_biennium(biennium)
            found = parse_legislators(get(WSL, {"biennium": biennium}).text, DEPARTED.get(biennium, frozenset()))
        if found:
            data["legislators"], data["biennium"] = found, biennium
        print(f"legislators: {sum(len(s['senate']) + len(s['house']) for s in found.values())} "
              f"in {len(found)} districts ({biennium})")
        for line in extra_members(found):
            print(f"[warn] more members than seats, add the one who left to DEPARTED: {line}", file=sys.stderr)
    except Exception as exc:
        print(f"[warn] legislators: {type(exc).__name__}: {exc}"[:300], file=sys.stderr)

    try:
        data["congress"] = parse_congress(get(CONGRESS).json())
        print(f"congress: {len(data['congress']['senators'])} senators, "
              f"{len(data['congress']['house'])} representatives")
    except Exception as exc:
        print(f"[warn] congress: {type(exc).__name__}: {exc}"[:300], file=sys.stderr)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
