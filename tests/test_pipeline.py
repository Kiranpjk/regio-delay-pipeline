from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from regio_delays import load as db
from regio_delays.cli import main
from regio_delays.extract import ApiSource, FixtureSource, RateLimiter
from regio_delays.transform import normalize

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
NOW = datetime(2026, 11, 20, 12, tzinfo=UTC)


def dep(trip="t1", planned="2026-11-20T08:00:00+01:00", when=None, delay=None, **extra):
    d = {
        "tripId": trip,
        "stop": {"id": "1", "name": "Test"},
        "plannedWhen": planned,
        "when": when,
        "delay": delay,
        "line": {"name": "RE 1", "product": "regional"},
    }
    d.update(extra)
    return d


def test_normalize_computes_delay_when_missing():
    rows, rep = normalize({"departures": [dep(when="2026-11-20T08:07:00+01:00")]}, NOW)
    assert rep.accepted == 1
    assert rows[0][8] == 420


def test_normalize_rejects_and_dedupes():
    raw = {
        "departures": [
            dep(),
            dep(),  # duplicate
            dep(trip=None),
            dep(trip="t2", planned="not-a-date"),
            dep(trip="t3", delay=99999),
        ]
    }
    rows, rep = normalize(raw, NOW)
    assert len(rows) == 1
    assert rep.duplicates == 1
    assert rep.rejected == {
        "missing_required_field": 1,
        "bad_timestamp": 1,
        "implausible_delay": 1,
    }


def test_cancelled_has_no_delay():
    rows, _ = normalize({"departures": [dep(cancelled=True)]}, NOW)
    assert rows[0][9] is True and rows[0][8] is None


def test_upsert_is_idempotent_and_keeps_latest():
    con = db.connect()
    rows, _ = normalize({"departures": [dep(delay=60)]}, NOW)
    db.load(con, rows)
    rows, _ = normalize({"departures": [dep(delay=600)]}, NOW)
    db.load(con, rows)
    assert con.execute("SELECT count(*), max(delay_s) FROM departures").fetchone() == (1, 600)


def test_line_report_punctuality():
    con = db.connect()
    raw = {"departures": [dep("a", delay=0), dep("b", delay=400), dep("c", cancelled=True)]}
    db.load(con, normalize(raw, NOW)[0])
    (row,) = db.line_report(con)
    _, line, deps, cancelled, punctual, *_ = row
    assert (line, deps, cancelled, float(punctual)) == ("RE 1", 3, 1, 50.0)


def test_fixture_source_reads_recorded_files():
    data = FixtureSource(FIXTURES).departures("900001")
    assert len(data["departures"]) > 30
    with pytest.raises(FileNotFoundError):
        FixtureSource(FIXTURES).departures("nope")


def test_rate_limiter_sleeps_between_calls():
    t = [0.0]
    slept = []
    rl = RateLimiter(1.0, clock=lambda: t[0], sleep=lambda s: slept.append(s) or None)
    rl.wait()
    t[0] = 0.25
    rl.wait()
    assert slept == [pytest.approx(0.75)]


def test_api_source_sends_regional_only_filter():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"departures": []})

    src = ApiSource(client=httpx.Client(transport=httpx.MockTransport(handler)), min_interval=0)
    assert src.departures("8011956") == {"departures": []}
    assert "/stops/8011956/departures" in seen["url"]
    assert "national=false" in seen["url"] and "nationalExpress=false" in seen["url"]


def test_cli_end_to_end(tmp_path, capsys):
    dbfile = tmp_path / "t.duckdb"
    args = ["--db", str(dbfile), "ingest", "900001", "900002", "--fixtures", str(FIXTURES)]
    assert main(args) == 0
    assert main(["--db", str(dbfile), "report"]) == 0
    out = capsys.readouterr().out
    assert "duplicates=1" in out and "RE 15" in out and "punctual%" in out
