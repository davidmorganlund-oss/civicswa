"""Try candidate sources before they go on the calendar.

python tools/trial.py candidates.yml  ->  one TRIAL line per source with the
number of upcoming events (next 60 days), a few titles, or the error.
"""
import json, sys, collections
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import build  # noqa: E402

TZ = ZoneInfo("America/Los_Angeles")


# Every request a source makes is noted (address, status, size), so a source
# that comes back empty can be told apart: an empty feed, a moved address, or
# meetings that our own include/exclude rules threw away.
import threading
_seen = threading.local()
_real_get = build.get


def _noting_get(url, params=None):
    r = _real_get(url, params)
    getattr(_seen, "log", []).append([r.url[:160], r.status_code, len(r.content)])
    _seen.peek = " ".join(r.text[:700].split())
    return r


build.get = _noting_get


def trial(src):
    today = datetime.now(TZ).date()
    _seen.log, _seen.peek = [], ""
    try:
        raw = build.CONNECTORS[src["type"]](src, today, today + timedelta(days=60), TZ)
        events = build.apply_source_rules(src, raw)
        cats = collections.Counter(e["category"] for e in events)
        dropped = sorted({e["title"] for e in raw} - {e["title"] for e in events})
        return {"id": src["id"], "n": len(events), "raw": len(raw), "cats": cats,
                "titles": sorted({e["title"] for e in events})[:8],
                "dropped": dropped[:8],
                "span": [min((e["start"][:10] for e in events), default=""), max((e["start"][:10] for e in events), default="")],
                "loc": next((e["location"] for e in events if e["location"]), ""),
                "fetched": _seen.log[:4], **({} if raw else {"peek": getattr(_seen, "peek", "")})}
    except Exception as e:  # report and move on
        return {"id": src["id"], "err": f"{type(e).__name__}: {str(e)[:160]}", "fetched": _seen.log[:4]}


if __name__ == "__main__":
    srcs = yaml.safe_load(open(sys.argv[1]))["sources"]
    with ThreadPoolExecutor(int(sys.argv[2]) if len(sys.argv) > 2 else 4) as ex:
        for r in ex.map(trial, srcs):
            print("TRIAL", json.dumps(r))
