# Running CivicsWA

CivicsWA is a static site on GitHub Pages (custom domain civicswa.org, registered at
Namecheap). A GitHub Actions workflow rebuilds the calendar every night. There is no
server, database or paid service.

## What runs, and when

- **Refresh and publish** (`.github/workflows/refresh.yml`) runs nightly at 11:17 UTC
  (3:17 a.m. Pacific), on every push to `main`, and on demand from the Actions tab.
  It runs the tests, reads every calendar in `pipeline/sources.yml`
  (`pipeline/build.py`), updates representatives (`pipeline/officials.py`),
  commits the data in `site/data/`, and deploys `site/` to GitHub Pages.
- **Alerts** (`pipeline/alerts.py`): when a calendar has failed three nights in a row,
  the run opens or updates the GitHub issue "Calendar sources need attention", and
  closes it when everything reads again. Watch the repository to get those emails.
- When a calendar can't be read, the site keeps showing what it listed the last time
  it worked, and the coverage page says so.
- `build.py` reads up to 8 calendars at once but never sends one website more than
  2 requests at a time. The run summary lists how many seconds each source took, so a
  slow one is easy to find. The job stops after 30 minutes; a normal run takes a few.
- Python packages (`requirements.txt`) and GitHub Actions are pinned to exact
  versions. Dependabot opens one pull request a month for each when updates are out;
  merge it once its checks pass.

## Adding or fixing a calendar

1. Find the platform. `tools/probe.py` (Actions: "Probe sites") scans a list of
   websites and reports what meeting software each uses.
2. Write the source in a YAML file and try it with `tools/trial.py`
   (Actions: "Trial sources"). It prints how many upcoming meetings each source
   returns and a few titles.
3. Add working sources to `pipeline/sources.yml`. The comment at the top of that file
   lists every field. Push; the next run picks it up.

Supported platforms: Legistar, CivicClerk, CivicPlus, CivicWeb and Diligent
Community, PrimeGov, Granicus agenda feeds, GovAccess, Apptegy school sites,
iCalendar feeds (Google Calendar, WordPress, Finalsite), BiblioCommons library events,
and published standing schedules (`type: schedule`).

Rules we keep: respect sites that block automated readers or ask them to stay out
(BoardDocs, robots.txt), and link to their pages instead.
Removed for that reason: Normandy Park (its events feed began refusing our reader in
November 2026).

## Pages that need a hand edit

- `site/sitemap.xml`: add a line when you add a page.
- `site/data/local.json`: county and city links for the "Near you" boxes.

## Accounts and renewals

- Google Search Console: property https://civicswa.org/, verified by the file
  `site/googleff798193875b3f67.html`. Don't delete that file. The sitemap is submitted there.
- Corrections and accessibility reports go to admin@barnoneinc.org.

- GitHub repository: `davidmorganlund-oss/civicswa`. Give at least one other BarNone
  person admin access so the site doesn't depend on one account.
- Domain: civicswa.org at Namecheap. Keep auto-renew on.
- Security: code scanning, Dependabot alerts, secret scanning and private
  vulnerability reporting are on (Settings > Advanced Security).

## Spotlight banner (outside opportunities)

The home pages (`site/index.html` and `site/es/index.html`) have an
`<aside class="spotlight">` under the hero for an opportunity we pass along
from another organization, such as a grant. Its `data-until` attribute is an
ISO time in UTC; `site/spotlight.js` removes the banner once that time passes,
so a closed deadline never stays up. To post a new one, edit the text, link and
`data-until` in both files. To retire one early, delete the `<aside>` block.
Keep the "Run by ..., not CivicsWA" line so it's clear who runs the program.


## School districts still without a source (November 2026)

A coverage pass against OSPI's 295 districts left these without a feed that
carries board meetings or a published regular schedule we could find. Most
post meetings only to BoardDocs (which asks automated readers to stay out) or
state their schedule only in a color-coded PDF. Add them one at a time from
the district's board page, as `type: schedule` with `when` or adopted `dates`:

- Adna
- Anacortes
- Asotin-Anatone
- Bellingham
- Boistfort
- Centerville
- Chehalis
- Clover Park
- Colfax
- Columbia (Walla Walla County)
- Concrete
- Coulee-Hartline
- Coupeville
- Crescent
- Davenport
- Eastmont
- Elma
- Ephrata
- Federal Way
- Ferndale
- Fife
- Glenwood
- Goldendale
- Grand Coulee Dam
- Great Northern
- Inchelium
- Kahlotus
- Kalama
- Keller
- Kennewick
- Kittitas
- La Center
- Lake Chelan
- Lake Stevens
- Lakewood
- Liberty
- Longview
- Lyle
- Mansfield
- Mary Walker
- Mead
- Medical Lake
- Meridian
- Methow Valley
- Montesano
- Moses Lake
- Naselle-Grays River Valley
- Nespelem
- Newport
- North River
- Northport
- Oakesdale
- Oakville
- Odessa
- Orient
- Oroville
- Othello
- Palouse
- Pateros
- Paterson
- Pe Ell
- Pomeroy
- Port Angeles
- Puyallup
- Queets-Clearwater
- Quilcene
- Riverside
- Roosevelt
- Rosalia
- Selah
- Selkirk
- Shaw Island
- Snohomish
- South Bend
- South Kitsap
- Sprague
- St. John
- Starbuck
- Stehekin
- Stevenson-Carson
- Tahoma
- Tenino
- Toledo
- Toutle Lake
- Trout Lake
- Wahkiakum
- Wapato
- Waterville
- Wellpinit
- Wenatchee
- White River
- Wilbur
- Winlock
- Wishkah Valley
- Yakima
- Zillah
