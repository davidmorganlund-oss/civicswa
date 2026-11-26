"""Rebuild site/sitemap.xml from the pages themselves.

Every page that carries a canonical link (and no noindex) goes in, listed at
its canonical address, with its English/Spanish hreflang pairs so search
engines index the two languages as partner pages, not duplicates.
lastmod is the date of the page's last commit (today if it has uncommitted
changes). Run after adding, renaming or editing pages:

    python3 tools/sitemap.py
"""
import datetime
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
TODAY = datetime.date.today().isoformat()


def lastmod(path):
    rel = str(path.relative_to(ROOT))
    dirty = subprocess.run(["git", "status", "--porcelain", "--", rel], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if dirty:
        return TODAY
    day = subprocess.run(["git", "log", "-1", "--format=%cs", "--", rel], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return day or TODAY


entries = []
for page in sorted(SITE.rglob("*.html")):
    html = page.read_text(encoding="utf-8")
    head = html.split("</head>", 1)[0]
    if re.search(r'<meta name="robots" content="[^"]*noindex', head):
        continue
    canon = re.search(r'<link rel="canonical" href="([^"]+)"', head)
    if not canon:
        continue
    url = canon.group(1)
    if url != "https://civicswa.org/" + str(page.relative_to(SITE)).replace("\\", "/").removesuffix("index.html"):
        continue  # a moved page that points elsewhere (playbook.html -> engage.html)
    alts = re.findall(r'<link rel="alternate" hreflang="([^"]+)" href="([^"]+)"', head)
    entries.append((url, lastmod(page), alts))

order = {"en": 0, "es": 1, "x-default": 2}
lines = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">']
for url, day, alts in sorted(entries, key=lambda e: (e[0] != "https://civicswa.org/", e[0])):
    lines.append("  <url>")
    lines.append(f"    <loc>{url}</loc>")
    lines.append(f"    <lastmod>{day}</lastmod>")
    for lang, href in sorted(alts, key=lambda a: order.get(a[0], 9)):
        lines.append(f'    <xhtml:link rel="alternate" hreflang="{lang}" href="{href}"/>')
    lines.append("  </url>")
lines.append("</urlset>")
(SITE / "sitemap.xml").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(len(entries), "pages in site/sitemap.xml")
