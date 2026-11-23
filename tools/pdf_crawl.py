"""Find each district's board meeting schedule PDF and print its text.

Renders the homepage and board pages (as render_crawl does), collects links to
PDFs whose text or address mentions the board and a schedule or calendar, and
prints the first part of each PDF's text. Input: TSV of name, county, homepage.
"""
import asyncio, io, json, re, sys
from urllib.parse import urlparse
import requests
from pypdf import PdfReader
from playwright.async_api import async_playwright

HINT = re.compile(r"board|meeting|agenda|directors|governance", re.I)
PDFHINT = re.compile(r"(board|meeting).{0,40}(schedule|calendar|dates)|(schedule|calendar|dates).{0,40}(board|meeting)|meeting.dates|board.calendar", re.I)
UA = {"User-Agent": "Mozilla/5.0 (CivicsWA meeting finder; +https://civicswa.org)"}


async def links_of(ctx, url):
    p = await ctx.new_page()
    try:
        await p.goto(url, timeout=25000, wait_until="domcontentloaded")
        try:
            await p.wait_for_load_state("networkidle", timeout=6000)
        except Exception:
            pass
        return p.url, await p.evaluate("[...document.querySelectorAll('a')].map(a=>[a.href,(a.innerText||a.title||'').trim().slice(0,120)])")
    finally:
        await p.close()


def pdf_text(u):
    try:
        r = requests.get(u, headers=UA, timeout=30)
        if r.status_code >= 400 or b"%PDF" not in r.content[:1024]:
            return None
        rd = PdfReader(io.BytesIO(r.content))
        return re.sub(r"[ \t]+", " ", "\n".join((pg.extract_text() or "") for pg in rd.pages[:3]))[:3500]
    except Exception as e:
        return f"ERR {e}"[:100]


async def crawl(sem, browser, row):
    name, county, home = row
    res = {"name": name, "pdfs": []}
    async with sem:
        ctx = await browser.new_context(user_agent=UA["User-Agent"])
        try:
            final, links = await links_of(ctx, home)
            host = urlparse(final).netloc
            pages = [u for u, t in links if urlparse(u).netloc == host and HINT.search(t + " " + u) and not u.lower().endswith(".pdf")]
            pages = sorted(dict.fromkeys(u.split("#")[0] for u in pages), key=lambda u: 0 if "board" in u.lower() else 1)[:8]
            allk = list(links)
            for u in pages:
                try:
                    _, l2 = await links_of(ctx, u)
                    allk += l2
                except Exception:
                    pass
        except Exception as e:
            res["error"] = str(e)[:100]
            await ctx.close()
            return res
        await ctx.close()
    pdfs = [(u, t) for u, t in allk if (".pdf" in u.lower() or "/showpublisheddocument" in u.lower() or "/file/" in u.lower() or "drive.google" in u)
            and PDFHINT.search(t + " " + u.replace("-", " ").replace("_", " ").replace("%20", " "))]
    pdfs = list(dict.fromkeys(pdfs))[:3]
    for u, t in pdfs:
        txt = await asyncio.to_thread(pdf_text, u)
        res["pdfs"].append({"url": u, "label": t, "text": txt})
    return res


async def main(path):
    rows = [l.rstrip("\n").split("\t") for l in open(path) if l.strip()]
    sem = asyncio.Semaphore(8)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        for coro in asyncio.as_completed([crawl(sem, browser, r) for r in rows]):
            print("PDF " + json.dumps(await coro), flush=True)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
