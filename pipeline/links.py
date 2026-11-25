"""Weekly link check (.github/workflows/links.yml).

Reads every outside link in the pages, the guides, the reps lookup's checked
council links and the county and city cards (site/data/local.json), and lists
the ones that are clearly broken, so moved pages get fixed.

Only clear failures count as broken: 404 or 410, or a site that doesn't
answer at all. 401, 403, 429 and 5xx usually mean a bot block or a busy
server, so they are not listed. Pages a site's robots.txt asks automated
readers to stay out of are skipped.
"""
from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
UA = "CivicsWA/0.1 (BarNone nonprofit civic calendar; link check; contact admin@barnoneinc.org)"
HREF = re.compile(r'href="(https?://[^"#]+)"')
JS_URL = re.compile(r"url: '(https?://[^']+)'")
SKIP_HOSTS = {"civicswa.org", "www.civicswa.org"}
_robots: dict[str, robotparser.RobotFileParser | None] = {}


def site_links() -> list[str]:
    urls = set()
    for page in sorted(SITE.glob("*.html")) + sorted((SITE / "guides").glob("*.html")) + sorted((SITE / "es").glob("*.html")):
        urls.update(HREF.findall(page.read_text(encoding="utf-8")))
    urls.update(JS_URL.findall((SITE / "reps.js").read_text(encoding="utf-8")))
    local = json.loads((SITE / "data" / "local.json").read_text(encoding="utf-8"))
    for group in ("counties", "cities"):
        for entry in local.get(group, {}).values():
            for key in ("site", "boards", "meetings"):
                if isinstance(entry.get(key), str):
                    urls.add(entry[key])
            for item in entry.get("schools", []) + entry.get("districts", []):
                if isinstance(item.get("site"), str):
                    urls.add(item["site"])
    urls = {u.replace("&amp;", "&") for u in urls if u.startswith(("http://", "https://"))}
    return sorted(u for u in urls if urlsplit(u).hostname not in SKIP_HOSTS)


def allowed(url: str) -> bool:
    """False when the site's robots.txt asks automated readers to stay out."""
    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}"
    if base not in _robots:
        import requests
        parser = robotparser.RobotFileParser()
        try:
            r = requests.get(base + "/robots.txt", headers={"User-Agent": UA}, timeout=15)
            parser.parse(r.text.splitlines() if r.status_code == 200 else [])
        except Exception:
            parser.parse([])
        _robots[base] = parser
    return _robots[base].can_fetch(UA, url)


def check(url: str) -> tuple[str, int, str]:
    import requests
    if not allowed(url):
        return url, -1, "robots"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=20, allow_redirects=True, stream=True)
        r.close()
        return url, r.status_code, ""
    except requests.exceptions.ConnectionError:
        return url, 0, "ConnectionError"
    except Exception as exc:
        return url, 0, type(exc).__name__


def broken(results) -> list[str]:
    bad = [(u, c, e) for u, c, e in results if c in (404, 410) or (c == 0 and e == "ConnectionError")]
    return [f"- Broken ({c or e}): {u}" for u, c, e in bad]


def main() -> int:
    urls = site_links()
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(check, urls))
    lines = broken(results)
    print(f"Checked {len(urls)} outside links.")
    print("\n".join(lines) or "No broken links.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
