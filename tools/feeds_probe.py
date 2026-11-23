import re, io, requests
H={"User-Agent":"CivicsWA calendar (civicswa.org)"}
def get(u): 
    try: return requests.get(u,headers=H,timeout=30)
    except Exception as e: print("ERR",u,e); return None
P=["https://www.coupeville.k12.wa.us/about-us/school-board/school-board-meeting-calendar","https://www.puyallupsd.org/about-us/school-board",
"https://www.lwsd.wednet.edu/our-board/board-meeting-schedule","https://www.skschools.org/board-meetings","https://www.ferndalesd.org/meet-the-board",
"https://marywalker.org/apps/pages/sycalendar","https://www.concrete.k12.wa.us/en-US/calendar","https://www.wishkah.org/en-US/calendar","https://www.meridian.wednet.edu/our-district/school-board/"]
for u in P:
    r=get(u); 
    if not r: continue
    t=r.text; txt=re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",re.sub(r"(?s)<(script|style).*?</\1>","",t)))
    print("=====",u,r.status_code)
    print("  board text:",[m for m in re.findall(r".{0,90}(?:[Bb]oard [Mm]eeting|[Rr]egular [Mm]eeting|[Ss]tudy [Ss]ession).{0,90}",txt)][:4])
    print("  links:",sorted({h for h in re.findall(r'(?:href|src)="([^"]+)"',t) if re.search(r"boarddocs|\.pdf|resource-manager|calendar\.google|\.ics|ical|schoolblocks|docs\.google",h,re.I)})[:12])
r=get("https://www.toutlesd.org/apps/events/ical/?id=3"); print("TOUTLE ICS\n",r.text[:2500])
r=get("https://www.selahschools.org/fs/resource-manager/view/f2107e0a-ea84-4fa0-95f0-a79a1b16e31b")
if r is not None:
    print("SELAH",r.status_code,r.headers.get("content-type"))
    try:
        from pypdf import PdfReader; print("\n".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)[:3000])
    except Exception as e: print("pdf err",e)
