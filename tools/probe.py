"""Probe public-body websites for the meeting software they use.

Reads a TSV of name, county, homepage; writes probe.json with, for each site,
the platforms it links to and (for CivicPlus sites) its calendar categories.
Run in CI, where the sites are reachable: python tools/probe.py tools/cities.tsv
"""
import json, re, sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse, unquote
import requests

UA = {"User-Agent": "Mozilla/5.0 (CivicsWA meeting finder; +https://civicswa.org)"}
PLATFORMS = {
    "legistar": r"([a-z0-9-]+)\.legistar\.com",
    "civicclerk": r"([a-z0-9-]+)\.portal\.civicclerk\.com",
    "primegov": r"([a-z0-9-]+)\.primegov\.com",
    "civicweb": r"([a-z0-9-]+)\.civicweb\.net",
    "diligent": r"([a-z0-9-]+)\.(?:community\.diligentoneplatform\.com|diligent\.community|community\.highbond\.com)",
    "granicus": r"([a-z0-9-]+)\.granicus\.com",
    "boarddocs": r"boarddocs\.com/wa/([a-z0-9_-]+)",
    "municode": r"([a-z0-9-]+)\.municodemeetings\.com",
    "iqm2": r"([a-z0-9-]+)\.iqm2\.com",
    "novus": r"([a-z0-9-]+)\.novusagenda\.com",
    "agendaquick": r"([a-z0-9-]+)\.agendaquick\.com",
    "simbli": r"simbli\.eboardsolutions\.com/[^\"']*?S=(\d+)",
    "gcal": r"calendar\.google\.com/calendar/(?:u/\d/)?(?:embed|ical)[^\"'\s]*?src=([^&\"'\s]+)",
}
LINK_HINT = re.compile(r"agenda|meeting|council|commission|calendar|minutes", re.I)


def get(url):
    try:
        r = requests.get(url, headers=UA, timeout=20)
        return r.status_code, r.url, r.text if "html" in r.headers.get("content-type", "") or r.text[:200].lstrip().startswith("<") else r.text[:2000]
    except Exception as e:
        return None, url, str(e)[:120]


def links(base, html):
    out = []
    for href, text in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
        text = re.sub(r"<[^>]+>", " ", text)
        if LINK_HINT.search(text + " " + href):
            out.append(urljoin(base, href))
    return out


def probe(row):
    name, county, home = row
    res = {"name": name, "county": county, "home": home, "found": {}, "ics": [], "civicplus": None}
    status, final, html = get(home)
    res["status"], res["final"] = status, final
    if not status or status >= 400:
        return res
    host = urlparse(final).netloc
    pages = [html]
    same = [u for u in dict.fromkeys(links(final, html)) if urlparse(u).netloc == host][:4]
    for u in same:
        s, _, h = get(u)
        if s and s < 400:
            pages.append(h)
    blob = "\n".join(pages)
    for k, pat in PLATFORMS.items():
        hits = sorted({unquote(m).lower() if k != "gcal" else unquote(m) for m in re.findall(pat, blob, re.I)})
        hits = [h for h in hits if h not in ("www", "")]
        if hits:
            res["found"][k] = hits[:4]
    res["ics"] = sorted(set(re.findall(r'(?:href|src)="([^"]+(?:\.ics|ical=1|/ical/|webcal:[^"]+))"', blob, re.I)))[:6]
    res["wordpress"] = "wp-content" in blob
    res["finalsite"] = "fsElement" in blob or "finalsite" in blob.lower()
    if re.search(r"/AgendaCenter|CivicPlus|/Calendar\.aspx|/DocumentCenter", blob, re.I):
        root = f"{urlparse(final).scheme}://{host}"
        s, _, cal = get(root + "/iCalendar.aspx")
        cats = []
        if s and s < 400:
            cats = re.findall(r'catID=(\d+)&(?:amp;)?feed=calendar"[^>]*>\s*([^<]{2,80}?)\s*</a>', cal)
        res["civicplus"] = {"root": root, "cats": cats[:80], "status": s,
                            "peek": "" if cats else re.sub(r"\s+", " ", cal)[:300]}
        res["agendacenter"] = bool(re.search(r"/AgendaCenter", blob, re.I))
    return res


if __name__ == "__main__":
    rows = [l.rstrip("\n").split("\t") for l in open(sys.argv[1]) if l.strip()]
    with ThreadPoolExecutor(12) as ex:
        out = list(ex.map(probe, rows))
    json.dump(out, open(sys.argv[2] if len(sys.argv) > 2 else "probe.json", "w"), indent=1)
    print(sum(1 for r in out if r["found"] or r["civicplus"] or r["ics"]), "of", len(out), "sites matched")
