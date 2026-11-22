"""Load step and reporting queries (DuckDB)."""

from __future__ import annotations

from pathlib import Path

import duckdb

SCHEMA = """
CREATE TABLE IF NOT EXISTS departures (
    trip_id      VARCHAR NOT NULL,
    station_id   VARCHAR NOT NULL,
    station_name VARCHAR,
    line         VARCHAR,
    product      VARCHAR,
    direction    VARCHAR,
    planned_at   TIMESTAMPTZ NOT NULL,
    actual_at    TIMESTAMPTZ,
    delay_s      INTEGER,
    cancelled    BOOLEAN NOT NULL,
    observed_at  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (trip_id, station_id, planned_at)
);
"""

# Idempotent upsert: re-running ingestion keeps the latest observation of each departure.
UPSERT = """
INSERT INTO departures VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (trip_id, station_id, planned_at) DO UPDATE SET
    actual_at = excluded.actual_at,
    delay_s = excluded.delay_s,
    cancelled = excluded.cancelled,
    observed_at = excluded.observed_at
"""

# "Punctual" uses DB's own definition: less than 6 minutes late (delay < 360 s).
LINE_REPORT = """
SELECT
    station_name,
    line,
    count(*)                                                      AS departures,
    sum(CASE WHEN cancelled THEN 1 ELSE 0 END)                    AS cancelled,
    round(100.0 * avg(CASE WHEN delay_s < 360 THEN 1 ELSE 0 END)
          FILTER (WHERE NOT cancelled), 1)                        AS punctual_pct,
    round(avg(delay_s) FILTER (WHERE NOT cancelled) / 60.0, 1)    AS avg_delay_min,
    round(max(delay_s) / 60.0, 1)                                 AS max_delay_min
FROM departures
GROUP BY station_name, line
ORDER BY punctual_pct ASC NULLS LAST, departures DESC
"""

HOURLY_REPORT = """
SELECT
    hour(planned_at AT TIME ZONE 'Europe/Berlin')                AS hour,
    count(*)                                                     AS departures,
    round(avg(delay_s) FILTER (WHERE NOT cancelled) / 60.0, 1)   AS avg_delay_min
FROM departures
GROUP BY 1
ORDER BY 1
"""


def connect(path: str | Path = ":memory:") -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(path))
    con.execute(SCHEMA)
    return con


def load(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> int:
    if rows:
        con.executemany(UPSERT, rows)
    return len(rows)


def line_report(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    return con.execute(LINE_REPORT).fetchall()


def hourly_report(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    return con.execute(HOURLY_REPORT).fetchall()
