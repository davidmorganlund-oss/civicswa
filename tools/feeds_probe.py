import sys,re,requests; sys.path.insert(0,"pipeline"); import build
from datetime import date; from zoneinfo import ZoneInfo
t=requests.get("https://www.toutlesd.org/apps/events/ical/?id=3",headers={"User-Agent":"CivicsWA"},timeout=30).text
for e in re.findall(r"BEGIN:VEVENT.*?END:VEVENT",t,re.S): print(e[:700]); print("--")
src={"id":"toutle-lake-schools","name":"x","type":"ics","url":"https://www.toutlesd.org/apps/events/ical/?id=3","category":"school","default_category":"school"}
ev=build.fetch_ics(src,date(2026,11,1),date(2027,6,30),ZoneInfo("America/Los_Angeles"))
print([e["start"][:16]+" "+e["title"] for e in ev])
