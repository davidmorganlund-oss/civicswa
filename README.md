# CivicsWA

A pilot civic calendar and playbook for Thurston County, Washington.
A project of BarNone, an independent nonprofit. Not affiliated with the
Washington Secretary of State or any government agency.

**Status: private pilot. Not launched.**

## How it works

- `pipeline/sources.yml` lists the public calendars the site reads.
- `pipeline/build.py` reads each one and writes `site/data/events.json`,
  `site/data/status.json` and `site/data/thurston.ics`.
- `.github/workflows/refresh.yml` runs that every night and saves the result.
- `site/` is a plain static site that reads those files. No accounts, no tracking.

## Sources

| Source | Platform | Connector | State |
|---|---|---|---|
| City of Olympia | Legistar | `legistar` | Feed confirmed |
| City of Lacey | CivicClerk | `civicclerk` | Feed confirmed |
| Thurston County | Published Outlook calendar | `ics` | Feed confirmed |
| Port of Olympia | WordPress events | `ics` | Feed unconfirmed |
| City of Tumwater | Municode Meetings | none | Blocked to crawlers; ask for a feed |
| Timberland Regional Library | BiblioCommons | none | Blocked to crawlers; ask for a feed |
| School boards | not inventoried | none | To do |

## Run it yourself

    pip install -r requirements.txt
    python -m pytest -q tests
    python pipeline/build.py
    python -m http.server --directory site 8000

## Adding a city

If it runs Legistar or CivicClerk, add four lines to `sources.yml`. A site with
an iCal feed uses the `ics` connector. Anything else needs a new connector in
`build.py`.
