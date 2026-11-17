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

## Pages that need a hand edit

- `site/sitemap.xml`: add a line when you add a page.
- `site/data/local.json`: county and city links for the "Near you" boxes.

## Accounts and renewals

- GitHub repository: `davidmorganlund-oss/civicswa`. Give at least one other BarNone
  person admin access so the site doesn't depend on one account.
- Domain: civicswa.org at Namecheap. Keep auto-renew on.
- Security: code scanning, Dependabot alerts, secret scanning and private
  vulnerability reporting are on (Settings > Advanced Security).
