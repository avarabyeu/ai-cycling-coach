"""
Parse Wahoo .fit files into a SQLite database for long-term analysis.

Design:
- activities table: one row per file with summary stats (fast aggregates over thousands of rides).
- file_index table: track parsed files by mtime so re-runs only ingest new/changed files.
- Optional samples table omitted on purpose -- summary fields cover ~95% of coaching queries,
  and parsing per-second streams for 1000s of rides would balloon the DB. Re-parse the source
  .fit on demand when you need waveform-level detail.
"""

import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from fitparse import FitFile

ROOT = Path(__file__).parent
FIT_DIR = ROOT / "WahooFitness"
DB_PATH = ROOT / "activities.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    file            TEXT PRIMARY KEY,
    sport           TEXT,
    sub_sport       TEXT,
    start_time      TEXT,         -- ISO8601 UTC
    local_date      TEXT,         -- YYYY-MM-DD
    year            INTEGER,
    month           INTEGER,
    duration_s      REAL,         -- total_timer_time
    elapsed_s       REAL,         -- total_elapsed_time
    distance_km     REAL,
    elevation_m     REAL,
    avg_speed_kmh   REAL,
    max_speed_kmh   REAL,
    avg_hr          INTEGER,
    max_hr          INTEGER,
    avg_power       INTEGER,
    max_power       INTEGER,
    np_power        INTEGER,      -- normalized power if present
    avg_cadence     INTEGER,
    calories        INTEGER,
    tss             REAL,
    intensity       REAL,         -- intensity factor
    training_load   REAL
);
CREATE INDEX IF NOT EXISTS idx_activities_date ON activities(local_date);
CREATE INDEX IF NOT EXISTS idx_activities_year_month ON activities(year, month);
CREATE INDEX IF NOT EXISTS idx_activities_sport ON activities(sport);

CREATE TABLE IF NOT EXISTS file_index (
    file   TEXT PRIMARY KEY,
    mtime  REAL NOT NULL,
    parsed_at TEXT NOT NULL
);
"""


def to_kmh(mps):
    return mps * 3.6 if mps is not None else None


def parse_one(path: Path):
    """Return a dict of summary fields, or None if file unreadable / not an activity."""
    try:
        fit = FitFile(str(path))
    except Exception as e:
        print(f"  ! cannot open {path.name}: {e}", file=sys.stderr)
        return None

    session = None
    for msg in fit.get_messages("session"):
        session = {d.name: d.value for d in msg}
        break  # first session is enough for single-sport rides

    if not session:
        return None

    start = session.get("start_time")
    start_iso = start.isoformat() if isinstance(start, datetime) else None
    local_date = start.date().isoformat() if isinstance(start, datetime) else None

    return {
        "file": path.name,
        "sport": session.get("sport"),
        "sub_sport": session.get("sub_sport"),
        "start_time": start_iso,
        "local_date": local_date,
        "year": start.year if isinstance(start, datetime) else None,
        "month": start.month if isinstance(start, datetime) else None,
        "duration_s": session.get("total_timer_time"),
        "elapsed_s": session.get("total_elapsed_time"),
        "distance_km": (session.get("total_distance") or 0) / 1000.0 or None,
        "elevation_m": session.get("total_ascent"),
        "avg_speed_kmh": to_kmh(session.get("avg_speed") or session.get("enhanced_avg_speed")),
        "max_speed_kmh": to_kmh(session.get("max_speed") or session.get("enhanced_max_speed")),
        "avg_hr": session.get("avg_heart_rate"),
        "max_hr": session.get("max_heart_rate"),
        "avg_power": session.get("avg_power"),
        "max_power": session.get("max_power"),
        "np_power": session.get("normalized_power"),
        "avg_cadence": session.get("avg_cadence"),
        "calories": session.get("total_calories"),
        "tss": session.get("training_stress_score"),
        "intensity": session.get("intensity_factor"),
        "training_load": session.get("total_training_effect"),
    }


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    cur = conn.cursor()

    seen = {row[0]: row[1] for row in cur.execute("SELECT file, mtime FROM file_index")}

    files = sorted(FIT_DIR.glob("*.fit"))
    new = 0
    skipped = 0
    failed = 0

    for i, path in enumerate(files, 1):
        mt = path.stat().st_mtime
        if seen.get(path.name) == mt:
            skipped += 1
            continue

        rec = parse_one(path)
        if rec is None:
            failed += 1
            continue

        cols = ",".join(rec.keys())
        placeholders = ",".join("?" * len(rec))
        cur.execute(
            f"INSERT OR REPLACE INTO activities ({cols}) VALUES ({placeholders})",
            list(rec.values()),
        )
        cur.execute(
            "INSERT OR REPLACE INTO file_index(file,mtime,parsed_at) VALUES(?,?,?)",
            (path.name, mt, datetime.utcnow().isoformat()),
        )
        new += 1

        if i % 50 == 0:
            conn.commit()
            print(f"  ... {i}/{len(files)} parsed", file=sys.stderr)

    conn.commit()
    conn.close()
    print(f"done: {new} new, {skipped} unchanged, {failed} failed, total files={len(files)}")


if __name__ == "__main__":
    main()
