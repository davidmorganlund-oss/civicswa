#!/usr/bin/env python3
"""Read each BoardDocs board's posted meetings and write a JSON snapshot.

BoardDocs refuses GitHub's servers, so this runs nightly on a volunteer's
computer (see install.sh) and pushes the result to the boarddocs-data branch,
where the nightly build picks it up. Standard library only, so it runs on the
python3 that ships with macOS.

    python3 tools/boarddocs/snapshot.py pipeline/sources.yml out.json
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

UA = "CivicsWA public meeting calendar (https://civicswa.org)"
BASE = "https://go.boarddocs.com/wa/{slug}/Board.nsf/"
DAYS_AHEAD = 240
PER_BOARD = 40


def request(url, form=None):
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def text_lines(html):
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    return "\n".join(x for x in (" ".join(t.split()) for t in re.sub(r"<[^>]+>", "\n", html).split("\n")) if x)


def board(slug):
    base = BASE.format(slug=slug)
    committee = re.search(r'committeeid="([A-Z0-9]+)"', request(base + "Public")).group(1)
    listing = json.loads(request(base + "BD-GetMeetingsList?open", {"current_committee_id": committee}))
    first, last = (date.today() - timedelta(days=1)).strftime("%Y%m%d"), (date.today() + timedelta(days=DAYS_AHEAD)).strftime("%Y%m%d")
    meetings = []
    for m in sorted((m for m in listing if first <= str(m.get("numberdate", "")) <= last), key=lambda m: m["numberdate"])[:PER_BOARD]:
        time.sleep(0.5)
        header = request(base + "BD-GetMeeting?open", {"id": m["unique"], "current_committee_id": committee})
        meetings.append({"date": m["numberdate"], "name": m.get("name", ""), "unique": m["unique"],
                         "header": text_lines(header)[:2500]})
    return meetings


def main(sources_path, out_path):
    slugs = sorted(set(re.findall(r"^\s+boarddocs:\s*([\w-]+)", open(sources_path).read(), re.M)))
    snap = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "boards": {}}
    for slug in slugs:
        try:
            snap["boards"][slug] = {"ok": True, "meetings": board(slug)}
            print(f"{slug}: {len(snap['boards'][slug]['meetings'])} meetings")
        except Exception as exc:  # one board's trouble shouldn't stop the rest
            snap["boards"][slug] = {"ok": False, "error": str(exc)[:200]}
            print(f"{slug}: FAILED {exc}")
    if not any(b["ok"] for b in snap["boards"].values()):
        sys.exit("No board could be read; not writing a snapshot.")
    with open(out_path, "w") as f:
        json.dump(snap, f, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:3])
