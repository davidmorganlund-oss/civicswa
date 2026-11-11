"""Build schools.tsv (name, county, website) from OSPI's district website list."""
import re, sys, html
import requests

CITY_COUNTY = {}
for line in open("tools/cities.tsv"):
    n, c, _ = line.rstrip("\n").split("\t")
    CITY_COUNTY[n.lower()] = c
CITY_COUNTY.update({k.lower(): v for k, v in {
    "Seattle": "King", "Tacoma": "Pierce", "Spokane": "Spokane", "Vancouver": "Clark", "Olympia": "Thurston",
    "Lacey": "Thurston", "Tumwater": "Thurston", "Bellevue": "King", "Redmond": "King", "Kent": "King",
    "Renton": "King", "Auburn": "King", "Kennewick": "Benton", "Richland": "Benton", "Pasco": "Franklin",
    "Marysville": "Snohomish", "Spokane Valley": "Spokane", "Sammamish": "King", "Burien": "King",
    "Lakewood": "Pierce", "Everett": "Snohomish", "Puyallup": "Pierce", "Issaquah": "King",
    "Federal Way": "King", "Kirkland": "King", "Bothell": "King", "Lynnwood": "Snohomish", "Shoreline": "King",
    "Spanaway": "Pierce", "Graham": "Pierce", "Brush Prairie": "Clark", "Yakima": "Yakima", "Bellingham": "Whatcom",
    "Wenatchee": "Chelan", "Walla Walla": "Walla Walla", "Mead": "Spokane", "Nine Mile Falls": "Spokane",
    "Port Townsend": "Jefferson", "Mercer Island": "King", "Woodinville": "King", "Kenmore": "King",
    "Camas": "Clark", "Woodland": "Cowlitz", "Toppenish": "Yakima", "Wapato": "Yakima", "Chehalis": "Lewis",
}.items()})

UA = {"User-Agent": "Mozilla/5.0 (CivicsWA meeting finder; +https://civicswa.org)"}
rows = []
for page in range(1, 8):
    t = requests.get("https://ospi.k12.wa.us/maps/sdmainmap.aspx", params={"page": page - 1} if page > 1 else None,
                     headers=UA, timeout=30).text
    for tr in re.findall(r"<tr\b.*?</tr>", t, re.S):
        cells = re.findall(r"<td\b.*?</td>", tr, re.S)
        if len(cells) < 3:
            continue
        link = re.search(r'href="(https?://[^"]+)"', cells[0])
        name = html.unescape(re.sub(r"<[^>]+>", "", cells[0])).strip()
        addr = html.unescape(re.sub(r"<[^>]+>", " ", cells[2])).strip()
        m = re.search(r",\s*([A-Za-z .'-]+),\s*WA", addr)
        city = m.group(1).strip() if m else ""
        if link and name:
            rows.append((name, CITY_COUNTY.get(city.lower(), "?" + city), link.group(1)))
seen = set()
with open(sys.argv[1], "w") as f:
    for r in rows:
        if r[2] in seen or re.search(r"charter|academy|tribal|ESD|educational service", r[0], re.I):
            continue
        seen.add(r[2])
        f.write("%s School District\t%s\t%s\n" % r)
print(len(seen), "districts")
