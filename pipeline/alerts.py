"""Open (or update, or close) one GitHub issue listing calendar sources that
have failed for three days or more. GitHub emails the repository owner when
the issue opens, so a broken city calendar doesn't go unnoticed.

Runs after build.py in the nightly workflow; needs the gh CLI and GH_TOKEN.
"""
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

TITLE = "Calendar sources need attention"
STATUS = Path(__file__).resolve().parent.parent / "site" / "data" / "status.json"
DAYS = 3


def gh(*args):
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def stuck_sources(status, today):
    cutoff = (today - timedelta(days=DAYS - 1)).isoformat()
    return [s for s in status["sources"]
            if s.get("state") == "failing" and s.get("failing_since") and s["failing_since"] <= cutoff]


def body(stuck):
    lines = ["These calendars have not answered for three days or more. CivicsWA keeps showing the "
             "last meetings it read from them, so their listings are going stale.", ""]
    for s in stuck:
        lines.append(f"- **{s['name']}** ({s.get('county', '')} County), failing since {s['failing_since']}. "
                     f"Last good read: {s.get('last_success') or 'never'}. Error: `{s.get('error', '')[:200]}`")
    lines += ["", "If a site now refuses automated readers, remove it from `pipeline/sources.yml` "
              "rather than working around the block. This issue closes itself when every source answers again."]
    return "\n".join(lines)


def main():
    stuck = stuck_sources(json.loads(STATUS.read_text()), date.today())
    found = json.loads(gh("issue", "list", "--state", "open", "--search", f'"{TITLE}" in:title',
                          "--json", "number,title"))
    issue = next((i["number"] for i in found if i["title"] == TITLE), None)
    if stuck and issue is None:
        gh("issue", "create", "--title", TITLE, "--body", body(stuck))
        print(f"opened an issue for {len(stuck)} source(s)")
    elif stuck:
        gh("issue", "edit", str(issue), "--body", body(stuck))
        print(f"updated issue #{issue}: {len(stuck)} source(s)")
    elif issue is not None:
        gh("issue", "close", str(issue), "--comment", "Every calendar source is answering again.")
        print(f"closed issue #{issue}")
    else:
        print("all sources healthy or failing for less than three days")
    return 0


if __name__ == "__main__":
    sys.exit(main())
