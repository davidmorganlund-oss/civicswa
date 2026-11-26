"""Build site/data/mayors.json: the mayor of each Washington city and town,
for the "Who represents you" lookup.

Source: MRSC Officials Directory (https://mrsc.org/mrsctools/officials-directory/),
the statewide list that MRSC keeps for Washington's cities and towns. It lists
people by last name, one page per letter; a mayor's title reads "Mayor (City)".
Deputy mayors and mayors pro tem are left out.

Never fails the nightly run: if a page can't be read, that letter keeps the
names from the last good run, and if too few mayors come back the whole file
is left as it was.
"""
from __future__ import annotations

import html
import json
import re
import string
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

OUT = Path(__file__).resolve().parent.parent / "site" / "data" / "mayors.json"
UA = "CivicsWA-pilot/0.1 (BarNone nonprofit civic calendar; contact via barnoneinc.org)"
PAGE = "https://mrsc.org/mrsctools/officials-directory/officials.aspx?of={}"
HOME = "https://mrsc.org/mrsctools/officials-directory/"
# Washington has about 280 cities and towns. Fewer than this means the
# directory changed shape, so keep the last good file instead.
MIN_MAYORS = 200

ITEM = re.compile(r"<li\b[^>]*>(.*?)</li>", re.S | re.I)
STRONG = re.compile(r"<strong\b[^>]*>(.*?)</strong>", re.S | re.I)
TAG = re.compile(r"<[^>]+>")
TITLE = re.compile(r"^Mayor \(([^()]+)\)")


def text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG.sub(" ", fragment))).strip()


def parse(page: str) -> list[tuple[str, str]]:
    """(city, name) for every "Mayor (City)" entry on one directory page."""
    found = []
    for item in ITEM.findall(page):
        m = STRONG.search(item)
        if not m:
            continue
        name = text(m.group(1))
        rest = text(item[m.end():])
        t = TITLE.match(rest)
        if name and t:
            found.append((t.group(1).strip(), name))
    return found


def fetch(letter: str):
    import requests
    url = PAGE.format(letter)
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=60)
        r.raise_for_status()
        return letter, url, parse(r.text)
    except Exception as e:  # one page down shouldn't stop the others
        print(f"  {letter}: could not read ({e.__class__.__name__})", file=sys.stderr)
        return letter, url, None


def main() -> int:
    old = {}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text())["mayors"]
        except Exception:
            old = {}
    mayors: dict[str, dict] = {}
    failed = []
    with ThreadPoolExecutor(4) as pool:
        for letter, url, rows in pool.map(fetch, string.ascii_lowercase):
            if rows is None:
                failed.append(letter)
                for city, m in old.items():
                    if m.get("letter") == letter:
                        mayors.setdefault(city, m)
                continue
            for city, name in rows:
                if city in mayors and mayors[city]["name"] != name:
                    print(f"  {city}: two mayors listed ({mayors[city]['name']}, {name}); keeping the first")
                    continue
                mayors[city] = {"name": name, "source": url, "letter": letter}
    print(f"Mayors: {len(mayors)} cities and towns" + (f"; kept last run's names for letters {', '.join(failed)}" if failed else ""))
    if len(mayors) < MIN_MAYORS:
        print(f"Only {len(mayors)} mayors found, fewer than {MIN_MAYORS}; keeping the last good file.")
        return 0
    data = {
        "source": "MRSC Officials Directory",
        "source_url": HOME,
        "as_of": datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat(),
        "mayors": dict(sorted(mayors.items())),
    }
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
