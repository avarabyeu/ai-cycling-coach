# AI Cycling Coach

A local, script-based cycling coach: ingests Wahoo `.fit` activity files into SQLite for long-term analysis, designs structured workouts as `.fit` / `.zwo` / intervals.icu WDL, and pushes them to your calendar (which auto-syncs to your Wahoo ELEMNT).

Built to work well inside [Claude Code](https://claude.ai/claude-code) with a set of coaching skills (`.claude/skills/`) — Claude Code becomes the coach, the DB and workout files become its memory and its outputs. The Python scripts are fully usable standalone if you want to skip Claude.

## What it does

- **Ingests** every ride your Wahoo head unit records (via Dropbox mirror) into a local SQLite database. Scales to thousands of activities without re-parsing.
- **Analyzes** any ride at coach-level depth: power/HR zone distribution, quartile pacing, Pw:HR decoupling (durability), best-power windows, and lap breakdowns.
- **Summarizes** your training block: YTD totals, weekly load trend, hardest efforts, FTP-proxy shortlist.
- **Estimates FTP** using multiple independent methods (20-min × 0.95, Critical Power model, sustained-NP median) and reports whether they converge.
- **Designs workouts** as spec-clean `.fit`, `.zwo`, and intervals.icu WDL text — all three formats emitted from a single Python step-list.
- **Pushes workouts** directly to your intervals.icu calendar via their API. intervals.icu then syncs to your Wahoo ELEMNT within its native 7-day window. No fragile file drag-and-drop.

## Why the file-format effort

Getting a structured workout onto a Wahoo ELEMNT is famously frustrating:

- The Wahoo mobile app's "Add Activity → Upload .fit" is for **completed activity files**, not planned workouts.
- Drag-dropping `.fit` or `.zwo` files into intervals.icu / TrainingPeaks silently fails with "unable to parse file" for reasons that vary across the two services.

This project generates spec-clean `.fit` (audited against the Garmin FIT Cookbook, targeted for BOLT V1 firmware compatibility), spec-clean `.zwo`, **and** intervals.icu's own Workout Description Language. The push script uses intervals.icu's API — the same codepath their own web builder uses — so the workout appears on your ELEMNT reliably.

## Setup

Prerequisites: Python 3.10+, [rclone](https://rclone.org/) with a Dropbox remote configured.

```bash
# Clone and install deps
git clone https://github.com/avarabyeu/ai-cycling-coach.git
cd ai-cycling-coach
pip3 install -r requirements.txt

# Personal config — your FTP and max HR
cp config.example.py config.py
$EDITOR config.py

# Point rclone at your Dropbox (one-time)
rclone config     # add a remote named "dropbox"

# (Optional, for automated workout push) intervals.icu API key
echo 'k-xxx...' > intervals_icu_api_key    # get from intervals.icu → Settings → Developer
```

`config.py`, `intervals_icu_api_key`, `activities.db`, and everything under `WahooFitness/` are gitignored — your training data and secrets stay local.

## Daily use

```bash
# 1. Sync your Dropbox → local mirror
rclone copy "dropbox:Apps/WahooFitness" ./WahooFitness --progress

# 2. Ingest (idempotent — only new files parsed)
python3 parse_activities.py

# 3. Query your training
python3 analyze.py ytd         # year-to-date totals
python3 analyze.py yoy         # year-over-year
python3 analyze.py monthly     # month-by-month, current year
python3 analyze.py recent      # last 6 weeks of rides
python3 analyze.py ftp         # hardest ~60-90 min NP efforts
python3 analyze.py weeks       # weekly load, last 12 weeks

# 4. Deep-dive a specific ride (defaults to latest)
python3 analyze_ride.py
python3 analyze_ride.py WahooFitness/<file>.fit

# 5. Regenerate all workout files (fit / zwo / wdl.txt)
python3 build_workout_fit.py

# 6. Push a workout to intervals.icu calendar (→ auto-syncs to Wahoo)
python3 push_workout.py --list
python3 push_workout.py sst_3x10 --date 2026-08-15 --time 07:00
```

## Adding your own workout

Open `build_workout_fit.py`, copy an existing `workout_*` function, and register it in the `WORKOUTS` dict. Use the `step()` and `repeat()` helpers — targets are written as `% FTP`, so the actual watts scale with whatever FTP your head unit is configured to.

Every `build_workout()` call round-trip-verifies its output against the FIT spec — if the script prints `wrote …`, the file passed structural validation.

Then re-run: `python3 build_workout_fit.py`.

## Using with Claude Code

The `.claude/skills/` directory contains modular skills that guide [Claude Code](https://claude.ai/claude-code) sessions:

| Skill | What it does |
|---|---|
| `sync-rides` | rclone from Dropbox + ingest new files into SQLite |
| `analyze-ride` | Deep-dive analysis of a specific ride with coach's interpretation |
| `training-status` | Big-picture weekly / YTD load summary with coaching read |
| `estimate-ftp` | Multi-method FTP estimator with recommendation |
| `build-workout` | Design and register a new workout in the library |
| `push-workout` | Schedule a workout on the intervals.icu calendar |

Ask Claude Code things like "analyze my latest ride", "how's my training block looking", "give me a sweet-spot workout for a 90-minute session" — the skills fire automatically based on the request.

## Data model

**`activities`** — one row per ride, indexed on date/year/month/sport. Contains: sport, start_time, duration, distance, elevation, avg/max HR, avg/max/normalized power, cadence, calories, TSS, IF.

**`file_index`** — `(file, mtime, parsed_at)`. Used to skip unchanged files on re-ingest.

Per-second waveform samples are **not** stored — they'd balloon the DB and slow queries. When you need waveform detail (best 20-min effort, decoupling, laps), `analyze_ride.py` re-parses the source `.fit` on demand.

Adding a new field: append a column to `activities` in `parse_activities.py`, add it to `parse_one()`, and either delete `activities.db` to re-ingest everything, or `ALTER TABLE` and delete matching rows from `file_index` to force re-parse on next run.

## Compatibility

- **Head units**: developed against a Wahoo ELEMNT BOLT V1. `.fit` workouts follow BOLT V1 firmware quirks (intensity values 0–3 only, GARMIN manufacturer, %FTP encoding, ranges with `low ≤ high`).
- **Services**: intervals.icu (primary — has native Wahoo Cloud integration since May 2024), TrainingPeaks (secondary path via `.fit` upload).
- **Files**: `.fit` (Garmin/ANT+ standard binary), `.zwo` (Zwift XML), `.wdl.txt` (intervals.icu Workout Description Language plain text).

## License

MIT — see `LICENSE`.

## Contributing

Personal training data lives in `activities.db` and `WahooFitness/*.fit` — both gitignored. When contributing, make sure you're not committing anything that could reveal your rides.

Ideas / issues welcome. Common asks:
- Support for HR-based zones as an alternative to power
- Non-cycling sport support (running, swimming — schema is currently cycling-only)
- More workout templates in the library
