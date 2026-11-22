# regio-delay-pipeline

[![CI](https://github.com/Kiranpjk/regio-delay-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/Kiranpjk/regio-delay-pipeline/actions/workflows/ci.yml)
[![Docker](https://github.com/Kiranpjk/regio-delay-pipeline/actions/workflows/docker.yml/badge.svg)](https://github.com/Kiranpjk/regio-delay-pipeline/actions/workflows/docker.yml)

A small batch ELT pipeline that collects **regional** train departures (the trains a
Deutschlandticket is valid on) from the public `v6.db.transport.rest` API, cleans them, loads
them into DuckDB and reports how punctual each line really is, per station and per hour.

## Problem

If you commute on a Deutschlandticket you only get RE/RB/S-Bahn trains, and you mostly hear
about delays in anecdotes. I wanted numbers for my own lines: which line is worst, at which
hour, how often trains are cancelled.

Sources (Reddit threads read while scoping the project):

- r/transit: <https://www.reddit.com/r/transit/comments/177yh9r/> - commenters discuss how
  delays on German trains have become a daily frustration and argue about why.
- r/dataengineering: <https://www.reddit.com/r/dataengineering/comments/1j1m5gt/> - a job
  seeker got critical feedback on a basic API-to-S3 ETL project and asks what a stronger
  portfolio project looks like. This repo tries to answer that with idempotent loads,
  data-quality checks and tests instead of just moving JSON around.

## Architecture

```
v6.db.transport.rest  --(extract: httpx, 1 req/s, retries with backoff)-->  raw JSON
          or fixtures/*.json (offline)
raw JSON  --(transform: flatten, type, validate, dedupe)-->  rows + quality report
rows      --(load: DuckDB upsert on (trip_id, station_id, planned_at))-->  departures table
departures --(SQL)-->  punctuality per line, average delay per hour
```

| Module | Responsibility |
| --- | --- |
| `extract.py` | `ApiSource` (rate limited, regional-only filter `national=false&nationalExpress=false`) and `FixtureSource` |
| `transform.py` | Normalises departures, computes missing delays, rejects bad rows (missing fields, bad timestamps, delays over 6 h), drops duplicates |
| `load.py` | DuckDB schema, idempotent upsert, report queries |
| `cli.py` | `ingest` and `report` commands |

"Punctual" follows DB's own definition: less than 6 minutes late. Cancelled trains are
counted separately and excluded from delay averages.

### Respecting the API

`v6.db.transport.rest` is a free, community-run service. Its docs ask for at most 100
requests per minute. This client sends at most 1 request per second, identifies itself with a
User-Agent, and backs off on 429/5xx. There is no scraping and no login.

## Demo

The sandbox this was built in could not reach the live API, so the demo uses
**synthetic fixtures** in the API's departures format, generated deterministically by
`scripts/make_fixtures.py` (station IDs `900001`/`900002` are fake). Each fixture file also
contains one duplicate and one broken row to exercise the quality checks.

```
$ regio-delays --db demo.duckdb ingest 900001 900002 --fixtures fixtures
station 900001: accepted=36 duplicates=1 rejected=1 {'missing_required_field': 1}
station 900002: accepted=36 duplicates=1 rejected=1 {'missing_required_field': 1}
loaded 72 rows; 72 departures stored in demo.duckdb

$ regio-delays --db demo.duckdb report
Punctuality per line (punctual = < 6 min late, cancellations excluded)

station               line   deps  cancelled  punctual%  avg_min  max_min
--------------------  -----  ----  ---------  ---------  -------  -------
Erfurt Hbf (demo)     RE 1   12    1          63.6       5.1      16.9
Jena Paradies (demo)  RE 15  13    1          66.7       3.5      8.4
Erfurt Hbf (demo)     RB 20  9     0          77.8       4.2      12.6
Jena Paradies (demo)  RE 42  9     0          77.8       3.8      8.6
Jena Paradies (demo)  RB 25  14    1          84.6       3.7      10.4
Erfurt Hbf (demo)     RE 15  15    1          85.7       2.7      10.9

Average delay by planned hour (Europe/Berlin)

hour  deps  avg_min
----  ----  -------
6     6     0.7
7     6     2.5
...
```

## Usage

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# live: find your station ID first, e.g.
#   curl 'https://v6.db.transport.rest/locations?query=Jena%20Paradies&results=1'
regio-delays ingest <STATION_ID> [<STATION_ID> ...] --duration 60
regio-delays report

# offline
regio-delays ingest 900001 900002 --fixtures fixtures
```

Run `ingest` on a schedule (cron, or a scheduled GitHub Actions job) to build up history;
re-running is safe because loads are upserts.

## Run with Docker

```bash
docker build -t regio-delays .
docker run --rm -v "$PWD/data:/data" regio-delays ingest 900001 900002 --fixtures /app/fixtures
docker run --rm -v "$PWD/data:/data" regio-delays report
```

Published image (after the Docker workflow runs on `main`): `ghcr.io/kiranpjk/regio-delay-pipeline`.

## Tests

```bash
pytest -q   # 9 tests: transform rules, dedupe, idempotent upsert, report SQL,
            # rate limiter, API request params (mocked transport), CLI end to end
```

## CI/CD

- `.github/workflows/ci.yml`: ruff lint + format check and pytest on Python 3.11, 3.12, 3.13.
- `.github/workflows/docker.yml`: builds the image on every PR; on `main` and `v*` tags pushes
  it to GHCR using the built-in `GITHUB_TOKEN`.
- `.github/dependabot.yml`: weekly updates for pip, GitHub Actions and the Docker base image.

## License

MIT, see [LICENSE](LICENSE).
