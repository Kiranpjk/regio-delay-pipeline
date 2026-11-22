"""Command line entry point: `regio-delays ingest` and `regio-delays report`."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import load as db
from .extract import DEFAULT_BASE_URL, ApiSource, FixtureSource
from .transform import normalize


def _table(headers: list[str], rows: list[tuple]) -> str:
    cells = [headers] + [["-" if v is None else str(v) for v in r] for r in rows]
    widths = [max(len(c[i]) for c in cells) for i in range(len(headers))]
    lines = ["  ".join(c[i].ljust(widths[i]) for i in range(len(headers))).rstrip() for c in cells]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def cmd_ingest(args: argparse.Namespace) -> int:
    source = FixtureSource(args.fixtures) if args.fixtures else ApiSource(args.base_url)
    con = db.connect(args.db)
    observed_at = datetime.now(UTC)
    total = 0
    for station in args.stations:
        raw = source.departures(station, args.duration)
        rows, report = normalize(raw, observed_at)
        total += db.load(con, rows)
        print(
            f"station {station}: accepted={report.accepted} duplicates={report.duplicates} "
            f"rejected={report.total_rejected} {report.rejected or ''}".rstrip()
        )
        if report.accepted == 0 and report.total_rejected > 0:
            print(f"  data-quality failure: every row rejected for {station}", file=sys.stderr)
            return 2
    stored = con.execute("SELECT count(*) FROM departures").fetchone()[0]
    print(f"loaded {total} rows; {stored} departures stored in {args.db}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    con = db.connect(args.db)
    print("Punctuality per line (punctual = < 6 min late, cancellations excluded)\n")
    print(
        _table(
            ["station", "line", "deps", "cancelled", "punctual%", "avg_min", "max_min"],
            db.line_report(con),
        )
    )
    print("\nAverage delay by planned hour (Europe/Berlin)\n")
    print(_table(["hour", "deps", "avg_min"], db.hourly_report(con)))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="regio-delays", description=__doc__)
    parser.add_argument("--db", default="regio.duckdb", help="DuckDB file (default regio.duckdb)")
    sub = parser.add_subparsers(dest="command", required=True)

    ing = sub.add_parser("ingest", help="fetch departures and load them")
    ing.add_argument("stations", nargs="+", help="station IDs (EVA numbers)")
    ing.add_argument("--duration", type=int, default=60, help="minutes of departures to fetch")
    ing.add_argument("--fixtures", type=Path, help="read recorded JSON instead of calling the API")
    ing.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ing.set_defaults(func=cmd_ingest)

    rep = sub.add_parser("report", help="print punctuality statistics")
    rep.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
