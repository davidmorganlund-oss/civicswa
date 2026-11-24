"""Open (or update, or close) one GitHub issue listing calendar sources that
have failed for three days or more, or that have answered with no meetings
at all for two weeks. GitHub emails the repository owner when the issue
opens, so a broken city calendar doesn't go unnoticed.

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
# A calendar that answers but lists nothing for this long has probably changed
# its layout or address. A source that is expected to sit empty (a board that
# posts only days ahead) can set "quiet_ok: true" in sources.yml.
QUIET_DAYS = 14


def gh(*args):
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def stuck_sources(status, today):
    cutoff = (today - timedelta(days=DAYS - 1)).isoformat()
    return [s for s in status["sources"]
            if s.get("state") == "failing" and s.get("failing_since") and s["failing_since"] <= cutoff]


def quiet_sources(status, today):
    cutoff = (today - timedelta(days=QUIET_DAYS - 1)).isoformat()
    return [s for s in status["sources"]
            if s.get("state") == "quiet" and not s.get("quiet_ok")
            and s.get("quiet_since") and s["quiet_since"] <= cutoff]


def body(stuck, quiet=()):
    lines = []
    if stuck:
        lines += ["These calendars have not answered for three days or more. CivicsWA keeps showing the "
                  "last meetings it read from them, so their listings are going stale.", ""]
        for s in stuck:
            lines.append(f"- **{s['name']}** ({s.get('county', '')} County), failing since {s['failing_since']}. "
                         f"Last good read: {s.get('last_success') or 'never'}. Error: `{s.get('error', '')[:200]}`")
        lines += ["", "If a site now refuses automated readers, remove it from `pipeline/sources.yml` "
                  "rather than working around the block.", ""]
    if quiet:
        lines += [f"These calendars answer but have listed no meetings for {QUIET_DAYS} days or more. "
                  "The site may have changed its layout or moved its calendar. Open each one and compare; "
                  "run it through the \"Trial sources\" action after a fix. If it is truly empty, "
                  "add `quiet_ok: true` to its entry in `pipeline/sources.yml`.", ""]
        for s in quiet:
            lines.append(f"- **{s['name']}** ({s.get('county', '')} County), nothing listed since {s['quiet_since']}. "
                         f"Last listed meetings: {s.get('last_listed') or 'never'}. {s.get('homepage', '')}")
        lines.append("")
    lines.append("This issue closes itself when every source answers and lists meetings again.")
    return "\n".join(lines)


def main():
    status = json.loads(STATUS.read_text())
    stuck = stuck_sources(status, date.today())
    quiet = quiet_sources(status, date.today())
    found = json.loads(gh("issue", "list", "--state", "open", "--search", f'"{TITLE}" in:title',
                          "--json", "number,title"))
    issue = next((i["number"] for i in found if i["title"] == TITLE), None)
    flagged = len(stuck) + len(quiet)
    if flagged and issue is None:
        gh("issue", "create", "--title", TITLE, "--body", body(stuck, quiet))
        print(f"opened an issue for {flagged} source(s)")
    elif flagged:
        gh("issue", "edit", str(issue), "--body", body(stuck, quiet))
        print(f"updated issue #{issue}: {flagged} source(s)")
    elif issue is not None:
        gh("issue", "close", str(issue), "--comment", "Every calendar source is answering and listing meetings again.")
        print(f"closed issue #{issue}")
    else:
        print("all sources healthy, or failing or quiet for less than the alert window")
    return 0


if __name__ == "__main__":
    sys.exit(main())
