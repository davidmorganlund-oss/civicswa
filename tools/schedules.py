"""Find how each public body announces its meetings.

Reads a TSV of name, county, homepage. For each site it runs the platform
probe from probe.py, then walks board/council/meeting pages (two levels) and
keeps sentences that describe a regular meeting schedule ("second and fourth
Monday ... 6:00 p.m."). Prints one JSON line per site. Run in CI.
"""
import json, re, sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse
sys.path.insert(0, "tools")
import probe as P

HINT = re.compile(r"board|council|commission|meeting|agenda|directors|trustees|govern", re.I)
SKIP = re.compile(r"\.(pdf|docx?|xlsx?|jpg|png|zip)$|facebook|twitter|instagram|youtube|mailto:|tel:", re.I)
DAYS = r"(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)days?"
SCHED = re.compile(
    r"(?:(?:first|second|third|fourth|last|1st|2nd|3rd|4th|every|each|alternate|other)\b[^.]{0,60}?\b" + DAYS +
    r"|" + DAYS + r"\b[^.]{0,40}?\b(?:of each|of every|each month|of the month))[^.]{0,220}", re.I)
TIME = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)|\bnoon\b", re.I)


def text_of(html):
    html = re.sub(r"<(script|style|nav|footer)\b.*?</\1>", " ", html or "", flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).replace("&nbsp;", " ").replace("&amp;", "&")


def board_links(base, html, host):
    out = []
    for href, label in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', html or "", re.S | re.I):
        label = re.sub(r"<[^>]+>", " ", label)
        u = urljoin(base, href)
        if urlparse(u).netloc == host and not SKIP.search(u) and HINT.search(label + " " + href):
            out.append(u)
    return list(dict.fromkeys(out))


def crawl(row):
    name, county, home = row
    res = P.probe(row)
    res.pop("granicus_peek", None)
    status, final, html = P.get(home)
    snippets, seen = [], set()
    if status and status < 400:
        host = urlparse(final).netloc
        level1 = sorted(board_links(final, html, host), key=lambda u: 0 if re.search(r"board|council|commission", u, re.I) else 1)[:10]
        queue = [(u, 1) for u in level1]
        while queue and len(seen) < 22:
            u, depth = queue.pop(0)
            if u in seen:
                continue
            seen.add(u)
            s, f, h = P.get(u)
            if not s or s >= 400:
                continue
            t = text_of(h)
            for m in SCHED.finditer(t):
                snip = m.group(0).strip()
                if TIME.search(snip) or re.search(r"meet", snip, re.I):
                    snippets.append([u, snip[:300]])
            if depth == 1:
                queue += [(x, 2) for x in board_links(f, h, host)[:12] if re.search(r"board|meeting|council|commission|schedule|calendar", x, re.I)]
    res["pages"] = len(seen)
    uniq, keep = set(), []
    for u, s in snippets:
        k = s.lower()[:120]
        if k not in uniq:
            uniq.add(k)
            keep.append([u, s])
    res["schedule"] = keep[:12]
    return res


if __name__ == "__main__":
    rows = [l.rstrip("\n").split("\t") for l in open(sys.argv[1]) if l.strip()]
    with ThreadPoolExecutor(16) as ex:
        for r in ex.map(crawl, rows):
            print("SCHED " + json.dumps(r), flush=True)
