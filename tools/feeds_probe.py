"""Look for each district's own calendar feed with board meetings."""
import re, urllib.parse, requests
H={"User-Agent":"CivicsWA calendar (civicswa.org)"}
D={"yakima":"https://www.ysd7.org","puyallup":"https://www.puyallupsd.org","south-kitsap":"https://www.skschools.org",
"meridian":"https://www.meridian.wednet.edu","lakewood":"https://www.lwsd.wednet.edu","selah":"https://www.selahschools.org",
"ferndale":"https://www.ferndalesd.org","coupeville":"https://www.coupeville.k12.wa.us","concrete":"https://www.concrete.k12.wa.us",
"tenino":"https://www.teninosd.org","mary-walker":"https://www.marywalker.org","toutle-lake":"https://www.toutlesd.org",
"winlock":"https://www.winlock.wednet.edu","wishkah":"https://www.wishkah.org"}
def get(u):
    try:
        r=requests.get(u,headers=H,timeout=25); return r.url,r.status_code,r.text
    except Exception as e: return u,0,str(e)
BOARD=re.compile(r"board|directors|trustee",re.I)
def board_in_ics(u):
    _,s,t=get(u)
    if s!=200 or "BEGIN:VCALENDAR" not in t: return f"status {s}"
    sums=re.findall(r"^SUMMARY[^:]*:(.*)$",t,re.M); b=[x for x in sums if BOARD.search(x)]
    return f"{len(sums)} events, {len(b)} board: {b[:4]}"
for k,u in D.items():
    print("=====",k)
    found=set(); texts=[]
    for p in ["","/calendar","/events","/school-board","/board"]:
        url,s,t=get(u+p); 
        if p=="": print("home",url,s,len(t))
        if s==200: texts.append((url,t))
    for url,t in texts:
        plat=[n for n in ["thrillshare","apptegy","finalsite","edlio","schoolmessenger","schoolwires","blackboard","sharpschool","wordpress","google.com/calendar","calendar.google.com","localist","rschooltoday","sitesgoogle"] if n in t.lower()]
        if plat: found.add("platform:"+",".join(plat))
        for m in re.findall(r'(?:href|src)="([^"]*(?:\.ics|ical|webcal:|calendar\.google\.com/calendar/[^"]*|calendar/embed[^"]*|icalfeed[^"]*|/fs/calendar-manager[^"]*))"',t,re.I):
            found.add(urllib.parse.urljoin(url,m.replace("&amp;","&")))
        for m in re.findall(r'thrillshare[^"\']*?/o/(\d+)',t): found.add("apptegy-org:"+m)
        for m in re.findall(r'"(?:organization_id|orgId|org_id)"\s*:\s*"?(\d+)',t): found.add("apptegy-org:"+m)
    for f in sorted(found):
        print("  ",f[:200])
        if "calendar.google.com" in f:
            for src in re.findall(r"src=([^&]+)",f):
                cid=urllib.parse.unquote(src); print("     gcal",cid,board_in_ics(f"https://calendar.google.com/calendar/ical/{urllib.parse.quote(cid)}/public/basic.ics"))
        elif f.startswith("apptegy-org:"):
            o=f.split(":")[1]
            try:
                j=requests.get(f"https://thrillshare-cmsv2.services.thrillshare.com/api/v4/o/{o}/cms/events",params={"locale":"en","page_no":1},headers=H,timeout=25).json()
                ev=j.get("events") or []; print("     apptegy",len(ev),[e.get("title") for e in ev if BOARD.search(e.get("title",""))][:5])
            except Exception as e: print("     apptegy err",e)
        elif re.search(r"\.ics|ical",f,re.I) and f.startswith("http"):
            print("     ",board_in_ics(f.replace("webcal:","https:")))
