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
- **Quiet calendars:** a calendar that answers but lists no meetings is marked "quiet".
  After 14 quiet nights in a row it is added to the same issue, because that usually
  means the site changed its layout or moved its calendar. If a source really is
  empty for long stretches, add `quiet_ok: true` to its entry in `pipeline/sources.yml`.
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

- `site/404.html`: the "page not found" page GitHub Pages serves for a bad address.
  It uses root-relative links (`/index.html`) because it can appear at any path.
  If the header or footer changes, change it here too.
- Fonts: Montserrat is served from `site/fonts/` (SIL Open Font License, in
  `site/fonts/OFL.txt`), not from Google, so no visitor data goes to a font host.

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

## Links to a place or a search

The calendar keeps the visitor's county, city, filter and search in the address
(`/?county=King&city=Seattle&cat=school&q=budget`), so any view can be shared.
A shared link doesn't change the place the recipient's browser had saved.

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
- Boistfort
- Centerville
- Chehalis
- Colfax
- Columbia (Walla Walla County)
- Coulee-Hartline
- Crescent
- Davenport
- Elma
- Ephrata
- Fife
- Glenwood
- Goldendale
- Grand Coulee Dam
- Great Northern
- Inchelium
- Kahlotus
- Kalama
- Keller
- Kittitas
- La Center
- Lake Chelan
- Lake Stevens
- Liberty
- Longview
- Lyle
- Mansfield
- Medical Lake
- Methow Valley
- Montesano
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
- Queets-Clearwater
- Quilcene
- Riverside
- Roosevelt
- Rosalia
- Selkirk
- Shaw Island
- South Bend
- Sprague
- St. John
- Starbuck
- Stehekin
- Stevenson-Carson
- Toledo
- Trout Lake
- Wahkiakum
- Wapato
- Waterville
- Wellpinit
- Wenatchee
- White River
- Wilbur
- Zillah

## Libraries still without a source (November 2026)

Checked against MRSC's list of library service providers. Branches of systems
already covered (KCLS, Sno-Isle, Pierce County, Timberland, Kitsap, Spokane
County, Fort Vancouver, Mid-Columbia, NCW Libraries) are covered by those
systems. These library boards still need a source, from the board's page:

- Everett, Bellingham, Richland, Longview, Kelso, Walla Walla (city), Puyallup,
  Camas, Anacortes, Mount Vernon, Sedro-Woolley, Port Townsend, Ellensburg,
  Liberty Lake, Neill (Pullman), Yakima Valley Libraries (4th Monday; time not
  published), Pend Oreille County (4th Thursday; time not published), Jefferson
  County, Asotin County, Stevens County Rural, Walla Walla County Rural,
  Columbia County Rural, La Conner, Ocean Shores, Grandview, Othello, Weller
  (Waitsburg), Yale Valley, Castle Rock, Kalama, Colville, Kettle Falls,
  Carpenter Memorial (Cle Elum), Roslyn, Kittitas, Cathlamet, Denny Ashby
  (Pomeroy), Roy, and the Lincoln County town libraries (Davenport, Harrington,
  Odessa, Reardan, Sprague, Wilbur).


## BoardDocs boards (the nightly snapshot)

BoardDocs (go.boarddocs.com) refuses requests from GitHub's servers, so the
nightly build can't read it. Thirteen school boards post only there. Each has a
hand-entered `schedule` entry with a `boarddocs:` site name (for example
`boarddocs: psd` for Puyallup).

A small job on David's Mac fills the gap. Every night at 1:40 a.m. it reads
each `boarddocs:` board's posted meetings and pushes them to the
`boarddocs-data` branch as `boarddocs.json`. The nightly build copies that
file to `pipeline/boarddocs.json` and uses the posted meetings (with their
real dates, times, places and cancellations) up to the last date posted, then
the board's pattern after that.

- **Setting it up (once):** in Terminal, run
  `curl -fsSL https://raw.githubusercontent.com/davidmorganlund-oss/civicswa/main/tools/boarddocs/install.sh -o /tmp/civicswa-install.sh && bash /tmp/civicswa-install.sh`.
  It clones the repo into `~/Library/Application Support/CivicsWA`, runs once
  to check it can push, and adds a nightly job.
- **Log:** `~/Library/Application Support/CivicsWA/boarddocs.log`.
- **If the Mac is off:** the job runs when it next wakes. If the snapshot is
  more than 10 days old, the build ignores it and uses the patterns alone, so
  nothing breaks, it just gets less exact.
- **Adding a board:** add `boarddocs: <site>` to its schedule entry (the
  `<site>` is the part after `/wa/` in its BoardDocs address). The next night's
  snapshot picks it up.
- **Removing the job:** `launchctl bootout gui/$(id -u)/org.civicswa.boarddocs`
  and delete `~/Library/LaunchAgents/org.civicswa.boarddocs.plist`.
