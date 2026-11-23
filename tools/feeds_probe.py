import re, urllib.parse, requests
H={"User-Agent":"CivicsWA calendar (civicswa.org)"}
BOARD=re.compile(r"board|directors|trustee",re.I)
def get(u):
    try: r=requests.get(u,headers=H,timeout=25); return r.url,r.status_code,r.text
    except Exception as e: return u,0,str(e)[:100]
def ics(u):
    _,s,t=get(u)
    if s!=200 or "BEGIN:VCALENDAR" not in t: return None
    ev=re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT",t,re.S); b=[]
    for e in ev:
        sm=re.search(r"^SUMMARY[^:]*:(.*)$",e,re.M); st=re.search(r"^DTSTART[^:]*:(\S+)",e,re.M)
        if sm and BOARD.search(sm.group(1)): b.append((st.group(1) if st else "")+" "+sm.group(1).strip())
    b.sort(); return f"{len(ev)} events, {len(b)} board, latest: {b[-5:]}"
def links(url,t,pat): return {urllib.parse.urljoin(url,m.replace("&amp;","&")) for m in re.findall(r'href="([^"]+)"',t) if re.search(pat,m,re.I)}
def gcal_ids(t):
    ids=set(urllib.parse.unquote(x) for x in re.findall(r'(?:src|cid)=([A-Za-z0-9%._+-]+(?:%40|@)[A-Za-z0-9%._-]+)',t))
    ids|=set(re.findall(r'[A-Za-z0-9._+-]+@(?:group\.calendar\.google\.com|gmail\.com|[a-z0-9.-]+\.(?:org|net|edu|us))',t)) if "calendar.google" in t else set()
    return {i for i in ids if "calendar" in i or "gmail" in i or "k12" in i or "wednet" in i or "sd" in i}
def deep(name,root):
    print("=====",name)
    url,s,t=get(root); print("home",url,s)
    pages=[(url,t)]
    for l in sorted(links(url,t,r"calendar|board|events"))[:12]:
        if urllib.parse.urlparse(l).netloc.split(".")[-2:]==urllib.parse.urlparse(url).netloc.split(".")[-2:] or "google" in l:
            u2,s2,t2=get(l); 
            if s2==200: pages.append((u2,t2))
    seen=set()
    for u,t in pages:
        for c in re.findall(r'calendar[_-]?ids?(?:\[\])?["\'=:\s]+\[?"?(\d+)',t): seen.add(("fs",urllib.parse.urljoin(u,"/").rstrip("/"),c))
        for c in re.findall(r'data-calendar-ids?="([\d,]+)"',t):
            for x in c.split(","): seen.add(("fs",urllib.parse.urljoin(u,"/").rstrip("/"),x))
        for g in gcal_ids(t): seen.add(("g",g))
        for l in links(u,t,r"\.ics|ical|webcal"): seen.add(("ics",l.replace("webcal:","https:")))
        for m in re.findall(r'/apps/events/\?id=(\d+)',t): seen.add(("edlio",urllib.parse.urljoin(u,"/").rstrip("/"),m))
    print("  pages:",[p[0] for p in pages][:12])
    for x in sorted(seen):
        if x[0]=="fs": r=ics(f"{x[1]}/fs/calendar-manager/events.ics?calendar_ids[]={x[2]}")
        elif x[0]=="g": r=ics(f"https://calendar.google.com/calendar/ical/{urllib.parse.quote(x[1])}/public/basic.ics")
        elif x[0]=="ics": r=ics(x[1])
        else: r=ics(f"{x[1]}/apps/events/ical/?id={x[2]}")
        print("  ",x,"->",r)
    return pages
D={"yakima":"https://www.ysd7.org","puyallup":"https://www.puyallupsd.org","south-kitsap":"https://www.skschools.org",
"meridian":"https://www.meridian.wednet.edu","lakewood":"https://www.lwsd.wednet.edu","selah":"https://www.selahschools.org",
"ferndale":"https://www.ferndalesd.org","coupeville":"https://www.coupeville.k12.wa.us","concrete":"https://www.concrete.k12.wa.us",
"mary-walker":"https://marywalker.org","toutle-lake":"https://www.toutlesd.org","winlock":"https://winlock.wednet.edu","wishkah":"https://www.wishkah.org"}
for k,u in D.items(): deep(k,u)
for base in ["https://marywalker.org","https://www.toutlesd.org"]:
    for i in range(0,12):
        r=ics(f"{base}/apps/events/ical/?id={i}")
        if r: print("edlio",base,i,r)
b=[]
for p in range(1,9):
    try: ev=requests.get("https://thrillshare-cmsv2.services.thrillshare.com/api/v4/o/637/cms/events",params={"locale":"en","page_no":p},headers=H,timeout=25).json().get("events") or []
    except Exception: break
    b+=[(e.get("formatted_start"),e.get("title")) for e in ev if BOARD.search(e.get("title",""))]
print("tenino apptegy board:",b[:10])
