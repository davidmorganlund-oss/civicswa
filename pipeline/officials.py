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
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

OUT = Path(__file__).resolve().parent.parent / "site" / "data" / "officials.json"
UA = "CivicsWA-pilot/0.1 (BarNone nonprofit civic calendar; contact via barnoneinc.org)"
WSL = "https://wslwebservices.leg.wa.gov/SponsorService.asmx/GetSponsors"
CONGRESS = "https://raw.githubusercontent.com/unitedstates/congress-legislators/gh-pages/legislators-current.json"
PARTY = {"D": "Democrat", "R": "Republican"}


def biennium_for(day: date) -> str:
    """Washington's legislative biennium starts in odd years: 2025-26, 2027-28."""
    start = day.year if day.year % 2 else day.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def parse_legislators(xml_text: str) -> dict:
    """{district: {"senate": [...], "house": [...]}} from the SponsorService XML."""
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
        found = parse_legislators(get(WSL, {"biennium": biennium}).text)
        if not found:  # a new biennium's roster can be empty until members are sworn in
            biennium = biennium_for(date(now.year - 2, 1, 1))
            found = parse_legislators(get(WSL, {"biennium": biennium}).text)
        if found:
            data["legislators"], data["biennium"] = found, biennium
        print(f"legislators: {sum(len(s['senate']) + len(s['house']) for s in found.values())} "
              f"in {len(found)} districts ({biennium})")
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
