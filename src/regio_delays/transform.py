"""Transform step: flatten raw API departures into typed rows and run data-quality checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

COLUMNS = (
    "trip_id",
    "station_id",
    "station_name",
    "line",
    "product",
    "direction",
    "planned_at",
    "actual_at",
    "delay_s",
    "cancelled",
    "observed_at",
)

# Anything beyond ±6 hours is almost certainly bad data, not a delay.
MAX_ABS_DELAY_S = 6 * 3600


@dataclass
class QualityReport:
    accepted: int = 0
    duplicates: int = 0
    rejected: dict[str, int] = field(default_factory=dict)

    def reject(self, reason: str) -> None:
        self.rejected[reason] = self.rejected.get(reason, 0) + 1

    @property
    def total_rejected(self) -> int:
        return sum(self.rejected.values())


def _parse_ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def normalize(raw: dict, observed_at: datetime) -> tuple[list[tuple], QualityReport]:
    """Return (rows, report). Rows follow COLUMNS order. Duplicate departures are dropped."""
    report = QualityReport()
    rows: list[tuple] = []
    seen: set[tuple] = set()

    for dep in raw.get("departures", []):
        stop = dep.get("stop") or {}
        line = dep.get("line") or {}
        trip_id = dep.get("tripId")
        planned = dep.get("plannedWhen")

        if not trip_id or not stop.get("id") or not planned:
            report.reject("missing_required_field")
            continue
        try:
            planned_at = _parse_ts(planned)
            actual_at = _parse_ts(dep.get("when"))
        except ValueError:
            report.reject("bad_timestamp")
            continue

        cancelled = bool(dep.get("cancelled", False))
        delay = dep.get("delay")
        if delay is None and actual_at and not cancelled:
            delay = int((actual_at - planned_at).total_seconds())
        if delay is not None and abs(delay) > MAX_ABS_DELAY_S:
            report.reject("implausible_delay")
            continue

        key = (trip_id, stop["id"], planned_at)
        if key in seen:
            report.duplicates += 1
            continue
        seen.add(key)

        rows.append(
            (
                trip_id,
                stop["id"],
                stop.get("name", ""),
                line.get("name", "unknown"),
                line.get("product", "unknown"),
                dep.get("direction", ""),
                planned_at,
                actual_at,
                delay,
                cancelled,
                observed_at,
            )
        )
        report.accepted += 1

    return rows, report
