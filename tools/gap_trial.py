"""Trial candidate feeds with no title filter; print board-looking events (next 150 days)."""
import json, re, sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import yaml
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import build  # noqa: E402
TZ = ZoneInfo("America/Los_Angeles")
BOARD = re.compile(r"\bboard\b|trustee|directors|work ?session|study session|special meeting|regular meeting", re.I)

def trial(src):
    today = datetime.now(TZ).date()
    try:
        ev = build.CONNECTORS[src["type"]](src, today - timedelta(days=60), today + timedelta(days=150), TZ)
        b = [(e["start"][:16], e["title"]) for e in ev if BOARD.search(e["title"])]
        return {"id": src["id"], "n": len(ev), "board": len(b), "sample": sorted(b)[:10],
                "titles": sorted({e["title"] for e in ev})[:12]}
    except Exception as e:
        return {"id": src["id"], "err": f"{type(e).__name__}: {str(e)[:160]}"}

if __name__ == "__main__":
    srcs = yaml.safe_load(open(sys.argv[1]))["sources"]
    with ThreadPoolExecutor(8) as ex:
        for r in ex.map(trial, srcs):
            print("GAPTRIAL", json.dumps(r), flush=True)
