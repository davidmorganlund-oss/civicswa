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


def trial(src):
    today = datetime.now(TZ).date()
    try:
        events = build.CONNECTORS[src["type"]](src, today, today + timedelta(days=60), TZ)
        events = build.apply_source_rules(src, events)
        cats = collections.Counter(e["category"] for e in events)
        return {"id": src["id"], "n": len(events), "cats": cats,
                "titles": sorted({e["title"] for e in events})[:8],
                "loc": next((e["location"] for e in events if e["location"]), "")}
    except Exception as e:  # report and move on
        return {"id": src["id"], "err": f"{type(e).__name__}: {str(e)[:160]}"}


if __name__ == "__main__":
    srcs = yaml.safe_load(open(sys.argv[1]))["sources"]
    with ThreadPoolExecutor(10) as ex:
        for r in ex.map(trial, srcs):
            print("TRIAL", json.dumps(r))
