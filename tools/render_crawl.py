"""Render each site in a headless browser and pull out meeting details.

For sites built with JavaScript (Finalsite, Apptegy, Edlio) a plain request
sees an empty page. This opens the homepage and up to 10 board/meeting pages
in Chromium and reports: schedule sentences, Apptegy org ids, Finalsite
calendar ids, iCal and Google Calendar links, and meeting portals.
Input: TSV of name, county, homepage. Prints one RENDER JSON line per site.
"""
import asyncio, json, re, sys
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright

DAYS = r"(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)days?"
SCHED = re.compile(r"(?:(?:first|second|third|fourth|last|1st|2nd|3rd|4th|every|each|alternate|other)\b[^.]{0,70}?\b"
                   + DAYS + r"|" + DAYS + r"\b[^.]{0,50}?\b(?:of each|of every|each month|of the month|monthly))[^.]{0,240}", re.I)
WHEN = re.compile(r"(?:regular(?:ly scheduled)? (?:school )?board meetings?|board (?:of directors )?(?:regularly )?meets|regular meetings? of the board|meetings? (?:are|is) held|board meeting schedule)", re.I)
HINT = re.compile(r"board|meeting|agenda|directors|governance|trustees", re.I)
PLAT = {
    "apptegy_org": r"thrillshare[^\"'\s]*?/(?:o|s)/(\d+)",
    "fs_ids": r"calendar_ids(?:\[\]|%5B%5D)=(\d+)|data-calendar-ids=\"([\d,]+)\"",
    "gcal": r"calendar\.google\.com/calendar/(?:u/\d/?)?(?:embed|ical)[^\"'\s]*?(?:src|cid)=([^&\"'\s]+)|calendar\.google\.com/calendar/ical/([^/\"'\s]+)/",
    "ics": r"(?:href|src)=\"([^\"]+(?:\.ics|webcal:[^\"]+))\"",
    "portal": r"([a-z0-9-]+\.(?:civicweb\.net|community\.diligentoneplatform\.com|diligent\.community|novusagenda\.com|simbli\.eboardsolutions\.com|boarddocs\.com/wa/[a-z0-9_-]+))",
}


async def page_info(ctx, url):
    p = await ctx.new_page()
    try:
        await p.goto(url, timeout=25000, wait_until="domcontentloaded")
        try:
            await p.wait_for_load_state("networkidle", timeout=6000)
        except Exception:
            pass
        html = await p.content()
        text = await p.evaluate("document.body ? document.body.innerText : ''")
        links = await p.evaluate("[...document.querySelectorAll('a')].map(a=>[a.href,(a.innerText||'').trim().slice(0,80)])")
        return p.url, html, re.sub(r"\s+", " ", text), links
    finally:
        await p.close()


async def crawl(sem, browser, row):
    name, county, home = row
    res = {"name": name, "county": county, "home": home, "schedule": [], "pages": 0}
    async with sem:
        ctx = await browser.new_context(user_agent="Mozilla/5.0 (CivicsWA meeting finder; +https://civicswa.org)")
        try:
            final, html, text, links = await page_info(ctx, home)
        except Exception as e:
            res["error"] = str(e)[:120]
            await ctx.close()
            return res
        res["final"] = final
        host = urlparse(final).netloc
        blobs, texts = [html], [(final, text)]
        cand = [u for u, t in links if u.startswith("http") and urlparse(u).netloc == host and HINT.search(t + " " + u)
                and not re.search(r"\.(pdf|docx?|jpg|png)$", u, re.I)]
        cand = sorted(dict.fromkeys(u.split("#")[0] for u in cand), key=lambda u: 0 if re.search(r"board", u, re.I) else 1)[:10]
        res["offsite"] = sorted({u for u, t in links if u.startswith("http") and urlparse(u).netloc != host and HINT.search(t + " " + u)})[:8]
        for u in cand:
            try:
                f, h, t, _ = await page_info(ctx, u)
                blobs.append(h); texts.append((f, t))
            except Exception:
                pass
        await ctx.close()
    res["pages"] = len(texts)
    seen = set()
    for u, t in texts:
        hits = [m.start() for m in SCHED.finditer(t)] + [m.start() for m in WHEN.finditer(t)]
        for i in sorted(hits):
            s = t[max(0, i - 160):i + 420].strip()
            if re.search(r"board|director|regular meeting", s, re.I) and s.lower()[150:260] not in seen:
                seen.add(s.lower()[150:260]); res["schedule"].append([u, s])
    res["schedule"] = res["schedule"][:10]
    blob = "\n".join(blobs)
    for k, pat in PLAT.items():
        hits = set()
        for m in re.findall(pat, blob, re.I):
            hits |= {x for x in (m if isinstance(m, tuple) else (m,)) if x}
        if hits:
            res[k] = sorted(hits)[:8]
    return res


async def main(path):
    rows = [l.rstrip("\n").split("\t") for l in open(path) if l.strip()]
    sem = asyncio.Semaphore(8)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        for coro in asyncio.as_completed([crawl(sem, browser, r) for r in rows]):
            print("RENDER " + json.dumps(await coro), flush=True)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
