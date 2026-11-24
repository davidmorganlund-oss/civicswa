"""Scratch link checker for the coverage expansion. Reads probe/in/*.json, writes probe/out/."""
import gzip, hashlib, html as H, io, json, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib import robotparser
import requests

UA = "Mozilla/5.0 (CivicsWA link check; +https://civicswa.org)"
HDR = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
IN, OUT = Path("probe/in"), Path("probe/out")
OUT.mkdir(exist_ok=True)
_robots = {}

def robots_ok(url):
    p = urlparse(url); root = f"{p.scheme}://{p.netloc}"
    if root not in _robots:
        rp = robotparser.RobotFileParser()
        try:
            r = requests.get(root + "/robots.txt", headers=HDR, timeout=12)
            rp.parse(r.text.splitlines() if r.status_code == 200 and "html" not in r.headers.get("content-type", "") else [])
        except Exception:
            rp.parse([])
        _robots[root] = rp
    return _robots[root].can_fetch(UA, url)

def text(h):
    h = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", h)
    return " ".join(H.unescape(re.sub(r"<[^>]+>", " ", h)).split())

def fetch(url, timeout=25):
    try:
        if not robots_ok(url):
            return {"status": "robots"}
        r = requests.get(url, headers=HDR, timeout=timeout, allow_redirects=True)
        return {"status": r.status_code, "final": r.url, "ctype": r.headers.get("content-type", ""), "body": r.text if "pdf" not in r.headers.get("content-type", "") else "", "raw": r.content if "pdf" in r.headers.get("content-type", "") else b""}
    except Exception as e:
        return {"status": None, "error": type(e).__name__ + ": " + str(e)[:140]}

BOARD = re.compile(r"board|commission|council|agenda|meeting|minutes|trustee|calendar|govern", re.I)

def norm_tokens(name):
    stop = {"of","the","city","town","village","school","district","no","sd","public","library","port","county","joint","consolidated","and","schools","isd","community","memorial","regional","service","esd","educational","unified","elementary","high","union","r","c","j"}
    return [t for t in re.findall(r"[a-z]+", name.lower().replace("'", "")) if t not in stop and len(t) > 2]

def check(item):
    url = item["url"]
    r = fetch(url, timeout=item.get("t", 25))
    res = {k: item[k] for k in item if k != "t"}
    res["status"] = r.get("status"); res["final"] = r.get("final"); res["error"] = r.get("error")
    body = r.get("body") or ""
    if body:
        t = text(body)
        m = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
        res["title"] = " ".join(H.unescape(m.group(1)).split())[:160] if m else ""
        toks = norm_tokens(item.get("name", ""))
        low = t.lower().replace("'", "")
        res["name_hits"] = [x for x in toks if x in low]
        res["name_toks"] = toks
        st = item.get("state", "")
        full = {"WA": "Washington", "ID": "Idaho", "OR": "Oregon"}.get(st, st)
        res["state_hit"] = bool(re.search(rf"\b{full}\b|\b{st}\s+9\d{{4}}|\b{st}\s+8\d{{4}}|, {st}\b", t))
        res["parked"] = bool(re.search(r"domain (is )?for sale|buy this domain|parked free|godaddy\.com/domainsearch|this domain may be for sale|sedo", t, re.I))
        res["words"] = len(t.split())
        links = []
        for href, lt in re.findall(r'<a\b[^>]*href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', body, re.S | re.I):
            lt = text(lt)[:80]
            if BOARD.search(lt) or BOARD.search(href):
                links.append([urljoin(res["final"] or url, H.unescape(href)), lt])
        res["links"] = links[:40]
    return res

def guess(item):
    """Try candidate domains in order; keep the first that loads and names the place and state."""
    for u in item["cands"]:
        r = check({"url": u, "name": item["name"], "state": item["state"], "t": 10})
        if r["status"] == 200 and not r.get("parked") and r.get("state_hit") and r.get("name_toks") and len(r.get("name_hits", [])) == len(r["name_toks"]):
            out = dict(item); out.pop("cands"); out.update(r); out["url"] = u
            return out
    out = dict(item); out.pop("cands"); out["status"] = "notfound"
    return out

def save_page(item):
    url = item["url"]
    r = fetch(url, timeout=60)
    key = item.get("key") or hashlib.md5(url.encode()).hexdigest()[:10]
    data = r.get("body") or ""
    if r.get("raw"):
        try:
            import pypdf
            data = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(r["raw"])).pages)
        except Exception as e:
            data = "PDFERR " + str(e)
    (OUT / "pages").mkdir(exist_ok=True)
    (OUT / "pages" / f"{key}.txt.gz").write_bytes(gzip.compress(data.encode("utf-8", "replace")))
    return {"key": key, "url": url, "status": r.get("status"), "final": r.get("final"), "error": r.get("error"), "len": len(data)}

t0 = time.time()
for f in sorted(IN.glob("*.json")):
    spec = json.loads(f.read_text())
    done = OUT / f.name
    if done.exists() and json.loads(done.read_text()).get("_stamp") == spec.get("_stamp"):
        continue
    kind = spec["kind"]; items = spec["items"]
    fn = {"verify": check, "guess": guess, "pages": save_page}[kind]
    with ThreadPoolExecutor(spec.get("threads", 12)) as ex:
        res = list(ex.map(fn, items))
    done.write_text(json.dumps({"_stamp": spec.get("_stamp"), "kind": kind, "results": res}, indent=0))
    ok = sum(1 for r in res if r.get("status") == 200)
    print(f"- {f.name}: {kind} {len(res)} items, {ok} OK ({time.time()-t0:.0f}s)")
