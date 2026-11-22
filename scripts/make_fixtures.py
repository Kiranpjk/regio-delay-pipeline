"""Generate deterministic offline fixtures in the v6.db.transport.rest departures format.

The sandbox this project was built in had no access to the live API, so the demo data is
synthetic: field names and structure follow the documented /stops/:id/departures response,
the values are seeded random. Replace them with real captures via:

    curl 'https://v6.db.transport.rest/stops/<ID>/departures?duration=60' \
        -G -d national=false -d nationalExpress=false > fixtures/<ID>-<date>.json
"""

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=1))  # CET (November)
STATIONS = {
    "900001": ("Jena Paradies (demo)", ["RE 15", "RB 25", "RE 42"]),
    "900002": ("Erfurt Hbf (demo)", ["RE 1", "RB 20", "RE 15"]),
}


def build(station_id: str, name: str, lines: list[str], rng: random.Random) -> dict:
    deps = []
    start = datetime(2026, 11, 20, 6, 0, tzinfo=TZ)
    for i in range(36):
        planned = start + timedelta(minutes=20 * i + rng.randint(0, 5))
        line = rng.choice(lines)
        cancelled = rng.random() < 0.05
        delay = None if cancelled else max(0, int(rng.expovariate(1 / 240)))
        when = None if cancelled else (planned + timedelta(seconds=delay)).isoformat()
        dep = {
            "tripId": f"1|{station_id}|{i}|80|20112026",
            "stop": {"type": "stop", "id": station_id, "name": name},
            "when": when,
            "plannedWhen": planned.isoformat(),
            "delay": delay,
            "platform": str(rng.randint(1, 4)),
            "direction": "Demo direction",
            "line": {
                "type": "line",
                "name": line,
                "product": "regional",
                "productName": line.split()[0],
                "mode": "train",
            },
        }
        if cancelled:
            dep["cancelled"] = True
        deps.append(dep)
    deps.append(dict(deps[0]))  # the API sometimes repeats a departure; tests dedupe
    deps.append({"tripId": None, "stop": {"id": station_id}, "plannedWhen": None})  # junk row
    return {"departures": deps}


if __name__ == "__main__":
    rng = random.Random(42)
    out = Path(__file__).resolve().parent.parent / "fixtures"
    out.mkdir(exist_ok=True)
    for sid, (name, lines) in STATIONS.items():
        path = out / f"{sid}-2026-11-20.json"
        path.write_text(json.dumps(build(sid, name, lines, rng), indent=1), encoding="utf-8")
        print("wrote", path)
