# CivicsWA

A pilot civic calendar and Engage guides for Thurston County, Washington.
A project of BarNone, an independent nonprofit. Not affiliated with the
Washington Secretary of State or any government agency.

**Status: public pilot for Thurston County at civicswa.org.**

## How it works

- `pipeline/sources.yml` lists the public calendars the site reads.
- `pipeline/build.py` reads each one and writes `site/data/events.json`,
  `site/data/status.json` and `site/data/thurston.ics`.
- `.github/workflows/refresh.yml` runs that every night and saves the result.
- `site/` is a plain static site that reads those files. No accounts, no tracking.

## Sources

| Source | Platform | Connector | State |
|---|---|---|---|
| City of Olympia | Legistar | `legistar` | Live |
| City of Lacey | CivicClerk | `civicclerk` | Live |
| Thurston County | Published Outlook calendar | `ics` | Live |
| Port of Olympia | WordPress events feed | `mec_rss` | Live |
| City of Tumwater | City website calendar feed | `govaccess_rss` | Live, about a week ahead |
| Timberland Regional Library | BiblioCommons events feed | `bibliocommons` | Live, civic programs only |
| School boards | BoardDocs (Olympia) | none | BoardDocs blocks automated readers; needs another route |

## Run it yourself

    pip install -r requirements.txt
    python -m pytest -q tests
    python pipeline/build.py
    python -m http.server --directory site 8000

## Adding a city

If it runs Legistar or CivicClerk, add four lines to `sources.yml`. A site with
an iCal feed uses the `ics` connector. Anything else needs a new connector in
`build.py`.
