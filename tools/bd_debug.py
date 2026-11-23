import requests, re
UA = {"User-Agent": "Mozilla/5.0 (CivicsWA meeting finder; +https://civicswa.org)"}
for ua in [UA, {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}]:
    r = requests.get("https://go.boarddocs.com/wa/yakima/Board.nsf/Public", headers=ua, timeout=30)
    print("DBG", r.status_code, len(r.text), r.headers.get("server"), r.headers.get("content-type"), re.findall(r'committeeid="([A-Z0-9]+)"', r.text)[:2], repr(r.text[:300]))
    p = requests.post("https://go.boarddocs.com/wa/yakima/Board.nsf/BD-GetMeetingsList?open", data={"current_committee_id": "A94NFH5FB9C0"}, headers=ua, timeout=30)
    print("DBG2", p.status_code, repr(p.text[:200]))
