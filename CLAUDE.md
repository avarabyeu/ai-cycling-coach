# AI Cycling Coach — Project Guide

A local pipeline that ingests Wahoo `.fit` activity files into SQLite for long-term road-cycling analysis and coaching. Designed to scale to thousands of activities without re-parsing on every query. Coupled with a workout designer that emits `.fit`/`.zwo`/WDL and a one-shot pusher that schedules workouts on intervals.icu (auto-syncs to Wahoo ELEMNT).

## Layout

```
ai-cycling-coach/
├── README.md                     # user-facing entry point
├── LICENSE                       # MIT
├── .gitignore                    # keeps personal training data + secrets local
├── requirements.txt              # pip deps: fitparse, fit-tool
├── config.example.py             # template — copy to config.py, set your FTP/HRMAX
│
├── WahooFitness/                 # rclone sink — mirrors dropbox:Apps/WahooFitness (gitignored)
├── parse_activities.py           # incremental ingest: .fit → SQLite
├── analyze.py                    # canned coaching queries over the SQLite db
├── analyze_ride.py               # deep-dive on a single .fit file (zones, decoupling, peaks, laps)
├── build_workout_fit.py          # emit .fit, .zwo, and .wdl.txt for each named workout
├── push_workout.py               # push a workout to intervals.icu (auto-syncs to Wahoo)
├── activities.db                 # SQLite (gitignored)
├── workouts/                     # each session emitted as .fit + .zwo + .wdl.txt
└── .claude/skills/               # invokable coaching skills (see below)
```

## Data model

**`activities`** — one row per ride with summary fields (sport, start_time, year/month, duration_s, distance_km, elevation_m, avg/max speed, avg/max HR, avg/max/NP power, cadence, calories, TSS, IF). Indexed on `local_date`, `(year, month)`, and `sport`.

**`file_index`** — `(file, mtime, parsed_at)`. Used to skip unchanged files on re-ingest.

**Deliberately omitted:** per-second sample streams. Storing waveforms for thousands of rides would balloon the DB and slow queries. Re-parse the source `.fit` on demand when you need detail (e.g. true 20-min best-power, lap analysis, GPS).

## Setup (once)

```bash
pip3 install -r requirements.txt
cp config.example.py config.py                          # then edit FTP + HRMAX
rclone config                                           # add a "dropbox" remote
echo 'k-xxx...' > intervals_icu_api_key                 # optional, for push_workout.py
```

## Workflow

```bash
# 1. Sync .fit files from Dropbox (Wahoo ELEMNT auto-uploads there)
rclone copy "dropbox:Apps/WahooFitness" ./WahooFitness --progress

# 2. Ingest (idempotent — only new/changed files are parsed)
python3 parse_activities.py

# 3. Query
python3 analyze.py ytd       # year-to-date totals
python3 analyze.py yoy       # year-over-year
python3 analyze.py monthly   # monthly breakdown, current year
python3 analyze.py recent    # last 6 weeks of rides
python3 analyze.py ftp       # hardest ~60-90min NP efforts (FTP proxy)
python3 analyze.py weeks     # last 12 weeks of weekly load

# Deep-dive on a single .fit (latest by default)
python3 analyze_ride.py                          # newest file in WahooFitness/
python3 analyze_ride.py WahooFitness/<file>.fit

# Build / refresh all .fit + .zwo + .wdl.txt workout files
python3 build_workout_fit.py

# Push a workout to intervals.icu calendar
python3 push_workout.py --list
python3 push_workout.py sst_3x10 --date 2026-08-15 --time 07:00

# Ad hoc:
sqlite3 activities.db "SELECT ... FROM activities WHERE ..."
```

## Dependencies

- Python 3.10+
- `fitparse` — read FIT activity files
- `fit-tool` — write FIT workout files
- `sqlite3` (stdlib)
- `rclone` with a `dropbox:` remote configured — pulls fresh activities from `Apps/WahooFitness`

## Working assumptions for coaching

- **Sport**: road cycling only — every ingested ride has `sport='cycling'`. Adding other sports means extending the schema.
- **FTP / HRMAX**: read from `config.py` (`analyze_ride.py` imports them with defaults if the file is missing). Every workout target is written as `%FTP`, so the actual watts scale with whatever FTP is configured on the head unit — the workout files themselves don't need to be regenerated when FTP changes.
- **Zone system**: Coggan power zones (see `analyze_ride.py` for exact edges).
- **Re-testing cadence**: FTP drifts with fitness. Re-estimate every 6–8 weeks or after a significant training block. When you update it, edit `config.py` **and** the FTP setting on the head unit.

## Conventions for future Claude sessions

- **Always sync + re-ingest before answering data questions** — run `rclone copy "dropbox:Apps/WahooFitness" ./WahooFitness --progress` then `python3 parse_activities.py`. The Wahoo ELEMNT auto-uploads to Dropbox, so the Dropbox path is authoritative.
- **Prefer SQL over re-parsing.** If a question can be answered from the `activities` table, do that. Only touch `.fit` files for waveform-level questions (zone distributions, decoupling, peaks, laps).
- **When recommending FTP-based workouts**, the builder writes `.fit`, `.zwo`, and `.wdl.txt` for every workout. Add a new function to `build_workout_fit.py` returning `(name, steps, out_path)`, register it in `WORKOUTS`, and re-run. Use the `step(...)` / `repeat(...)` helpers — targets are written as `%FTP`.
- **Prefer the API push over file uploads.** `push_workout.py` sends the workout as intervals.icu WDL text; intervals.icu generates the FIT server-side and pushes it to Wahoo via native Wahoo Cloud integration (May 2024+). This bypasses the fragile `.fit`/`.zwo` drag-drop codepath that silently fails with "unable to parse file".
- **Workout push paths — in order of reliability** (the Wahoo mobile app's "Add Activity → Upload .fit" is NOT one — that feature is for completed activity files, not planned workouts):
  1. **`python3 push_workout.py <key>`** — POSTs WDL to intervals.icu's `/api/v1/athlete/0/events`. intervals.icu generates the FIT and auto-syncs to Wahoo. Prereq: `intervals_icu_api_key` file (or `INTERVALS_API_KEY` env var) + Wahoo sync enabled in intervals.icu Settings (**and workout-type filter must not be "None"** — that silently blocks sync).
  2. **Copy-paste `.wdl.txt`** into intervals.icu's web workout builder — same result, no API key needed.
  3. **intervals.icu drag-and-drop `.fit` or `.zwo`** — sometimes fails; use only if WDL paths don't work.
  4. **TrainingPeaks (free)** — calendar drag/drop the `.fit`, authorize in ELEMNT app → Profile → Authorized Apps. Slower to sync.
- **FIT quirks / rules the builder enforces** (verified against Wahoo ELEMNT BOLT V1 + intervals.icu compatibility):
  - `WorkoutStepMessage.duration_time` setter expects **milliseconds**, not seconds.
  - `custom_target_value_low/high` with `target_type=POWER` and `target_value=0` is interpreted as **% FTP** (0–1000). Values ≥ 1000 mean absolute watts (subtract 1000). We always use %FTP so the head-unit FTP setting drives the watts.
  - `custom_target_value_low/high` defines a target **range** — `low <= high` is required. Inverted ranges (e.g. cool-down "60% → 45%") make strict importers refuse with "unable to parse". The `step(...)` helper raises on inversion.
  - **`FileIdMessage.manufacturer` must be real.** `DEVELOPMENT` (255) is rejected by intervals.icu. Use `GARMIN` (1) + `garmin_product = CONNECT` (65534) — the same combo Garmin Connect writes.
  - **Intensity values 0–3 only.** BOLT V1 firmware predates the FIT SDK additions of `RECOVERY`(4), `INTERVAL`(5), `OTHER`(6). Use `WARMUP`(2), `ACTIVE`(0), `REST`(1) for between-interval rests, `COOLDOWN`(3). Never `RECOVERY`/`INTERVAL`/`OTHER`.
  - **All steps must share the same `target_type`.** intervals.icu rejects mixed-target workouts. We use `POWER` throughout.
  - **`FileIdMessage.time_created`** setter takes a Unix-epoch timestamp in milliseconds; fit-tool converts to FIT `date_time` (seconds since 1989-12-31 UTC) on-wire.
  - **Repeat steps**: `duration_type=REPEAT_UNTIL_STEPS_CMPLT`, `duration_step=<step-index to loop back to>`, `target_type=OPEN`, `target_value=<n repetitions>`. Repetition count goes in `target_value` (not a dedicated field).
  - **BOLT/ELEMNT display quirk (not fixable in the file):** ranges display as the center value, not endpoints. Ramps show as a fixed number. This is a device limitation acknowledged by Wahoo.
- Every `build_workout(...)` call round-trip-verifies its output before printing "wrote" — the `_verify_written` guard catches fit-tool regressions, inverted ranges, or missing required fields.
- **Heart-rate ranges drift with fitness**; lead with power targets, give HR as a secondary anchor.
- **`analyze_ride.py` reads `FTP` / `HRMAX` from `config.py`** if present, else falls back to defaults. Keep `config.py` in sync with your current fitness.

## Coaching signals worth interpreting

Not baked-in facts about any specific user — these are analytical frameworks the skills apply to whatever data is in the DB.

- **Pw:HR decoupling** (compare 1st-half to 2nd-half power/HR ratio):
  - ≤ 2 % or negative → good durability, well-fueled/paced
  - 2–5 % → normal aerobic drift
  - 5–10 % → meaningful fade (fueling or cumulative fatigue)
  - \> 10 % → severe fade (glycogen depletion / illness / big under-recovery)
- **IF interpretation:** < 0.70 recovery, 0.70–0.80 endurance, 0.80–0.90 tempo, 0.90–0.95 threshold, ≥ 0.95 near-max threshold or VO2. Comment when the actual IF doesn't match the ride's stated intent.
- **Weekly TSS trend:** flat-line high loads or two hard weeks stacked = fatigue risk. Ideal build: gradual rise then a down-week every 3–4.
- **Cadence:** grinding (< 80 rpm) shifts load onto calves and shortens endurance. A drop of 5+ rpm from a rider's baseline is a fatigue signal.
- **On climbs:** hard cap at 75–80 % FTP on long sustained climbs; anything higher accumulates cost that pays out later in the ride.

## Skills

`.claude/skills/` contains packaged workflows Claude auto-invokes on matching prompts. Prefer invoking these over ad-hoc reconstruction — they encode the coaching frame and the exact commands to run.

| Skill | When it fires |
|---|---|
| `sync-rides` | User asks to update rides / pull latest / refresh data |
| `analyze-ride` | User asks for feedback on latest workout, breakdown of a ride, "how did that go" |
| `training-status` | YTD, weekly load, "how am I doing", form/fitness questions |
| `build-workout` | User wants to DESIGN a new workout / add one to the registry |
| `push-workout` | User wants to SCHEDULE a workout to the calendar / push it to Wahoo — the reliable path (intervals.icu API → Wahoo Cloud → ELEMNT) |
| `estimate-ftp` | User asks about FTP, wants a re-estimate, after a training block |

Skills chain:
- `analyze-ride`, `training-status`, `estimate-ftp` all start by invoking `sync-rides` unless data is known fresh.
- `build-workout` designs and registers → `push-workout` schedules an existing registry entry.
- Pushing a training week: often paired with `training-status` first so choices are informed by recent load / fatigue.

## Workout registry

Functions in `build_workout_fit.py` listed in `WORKOUTS`. Re-run the script to regenerate all output files.

| Key | Name | Purpose | Duration |
|---|---|---|---|
| `60km_sst_vo2` | 60km SST + VO2 | 3×10' SST + 4×2' VO2 + endurance tail | ~2h10m |
| `sst_3x10` | SST 3x10 | 3×10' Sweet Spot @ 88–90% FTP | ~75 min |
| `sst_40km_route` | SST 3x10 · 40km route | SST with a wide "roll-out" band tolerant of traffic in the first 3–5 km | ~76 min |
| `vo2_5x3` | VO2 5x3 | 5×3' VO2 @ 108–112% FTP | ~66 min |
| `long_z2_tempo` | Long Z2 + Tempo | 3h Z2 with 3×8' tempo accents | ~2h41m |
| `recovery_45` | Recovery 45 min | 45' Z1/low-Z2 recovery spin | 45 min |
| `z2_60` | Z2 60 min | 60' steady Z2 (65–72 % FTP) | 60 min |

## Adding a new analysis

Add a function to `analyze.py` and register it in the `CMDS` dict. Keep it a single SQL query — that's the whole point of the SQLite layer.

## Adding new fields to the schema

If a new field is needed from the `.fit` `session` message:
1. Add a column to the `activities` `CREATE TABLE` in `parse_activities.py`.
2. Add the field to the dict returned by `parse_one()`.
3. Delete `activities.db` and re-ingest (cheap — a few hundred files parse in ~2–3 minutes).

Alternatively, add the column via `ALTER TABLE` and backfill by deleting matching rows from `file_index` so they re-parse on the next run.
