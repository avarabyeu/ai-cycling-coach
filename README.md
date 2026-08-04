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

Once your data is synced and your config is in place, the whole project becomes a conversational coach. Open [Claude Code](https://claude.ai/claude-code) in this directory and talk to it in plain language — the `.claude/skills/` files tell Claude which script to run and how to interpret the output.

You don't call skills by name. Claude picks the right one from what you ask. Here's each skill, what triggers it, and what you'll get back.

### `sync-rides` — refresh the training database

**Triggers:** *"update my rides"*, *"pull latest activities"*, *"refresh training data"*

Runs `rclone copy` from your Dropbox `Apps/WahooFitness` folder into `WahooFitness/`, then re-ingests any new files into `activities.db`. Fast (a few seconds for a few new rides). Reports how many new rides landed.

Every other skill invokes this first automatically when it thinks the data might be stale, so you rarely need to trigger it explicitly.

### `analyze-ride` — coach's read on a specific ride

**Triggers:** *"analyze my latest ride"*, *"how did today's session go?"*, *"break down yesterday's ride"*

Runs `analyze_ride.py` on the newest `.fit` (or a specific file if you name one), then interprets the numbers as a coach would. What you get:

- **Ride type inferred from IF** — flags if the actual ride didn't match the intent (e.g. "billed as easy Z2, was tempo")
- **Durability read** via Pw:HR decoupling — the most important signal for whether the ride broke you
- **Peak-power windows** compared to your FTP — surfaces new benchmarks
- **Quartile pacing** — where in the ride you cracked (if you did)
- **Cadence and zone drift** on long rides

**Example:** *"analyze my latest ride"* → 5-line headline with the coach's take, one metrics table if it helps, one recommendation.

### `training-status` — big-picture form and load

**Triggers:** *"how am I doing?"*, *"YTD totals"*, *"weekly load"*, *"am I fresh?"*

Runs one or more of the canned queries in `analyze.py` and interprets the trends:

- Weekly TSS trend over the last 4–6 weeks — flags when you're overreaching
- Intensity mix — Z2 vs quality ratio, count of hard days in the last two weeks
- Fitness trajectory — is NP rising at the same HR? (fitness) or falling? (fatigue or detrain)
- Recovery signals from gaps between rides

**Example:** *"how's my training block looking?"* → headline number + 1-2 tables + coaching read + one concrete recommendation.

### `estimate-ftp` — is your FTP setting right?

**Triggers:** *"estimate my FTP"*, *"do I need a re-test?"*, *"what's my FTP now?"*

Runs a multi-method estimator across the last 60 days of rides: 20-min × 0.95 (Coggan), Critical Power model, sustained-NP median from your hardest 60–90 min efforts. Reports whether the methods converge (they usually do) and gives you one number with a confidence range.

If your recent ceilings cluster tightly, it'll say a formal test isn't necessary. If they're noisy, it'll recommend a 20-min all-out test on fresh legs.

**Example:** *"estimate my FTP"* → table of methods with values, plus "recommended: 245 W, range 240–255. Formal test not needed — three recent max efforts converge tightly."

### `build-workout` — design a new interval session

**Triggers:** *"design a sweet-spot workout"*, *"give me a 90-min VO2 session"*, *"create a threshold workout for a hilly route"*

Talks through the workout with you if it's vague, then adds a new function to `build_workout_fit.py`, registers it, and regenerates all three output formats (`.fit`, `.zwo`, `.wdl.txt`) for it. The FIT builder round-trip-verifies against the spec — if the script prints "wrote", the file passed structural validation for Wahoo ELEMNT BOLT V1 + intervals.icu.

**Example:** *"give me a sweet-spot workout with a 3×12 main set, ~75 min total"* → step list, estimated TSS, files emitted, registry key you can then schedule.

Chains into `push-workout` if you also want it on the calendar.

### `push-workout` — schedule to intervals.icu → Wahoo

**Triggers:** *"schedule the SST workout for Wednesday"*, *"push tomorrow's training"*, *"plan my week"*

POSTs a workout from the registry as intervals.icu WDL text via their API. intervals.icu generates the FIT server-side and pushes it to your Wahoo ELEMNT (native Wahoo Cloud integration since May 2024). This bypasses the fragile `.fit`/`.zwo` drag-and-drop path.

If you ask for a full week, it picks a balanced set (Z2 base + threshold + long ride, rest days left blank) and pushes them in parallel. You get back a schedule table with intervals.icu event IDs, direct workout URLs, and estimated weekly TSS.

**Example:** *"plan my next week — I want two quality days and a long Saturday"* → 3–4 workouts scheduled with dates and times, plus a note about verifying the intervals.icu → Wahoo sync toggle.

### How skills chain

- `analyze-ride`, `training-status`, `estimate-ftp` — all silently invoke `sync-rides` first
- `build-workout` → `push-workout` — designing a new session then scheduling it
- `training-status` → `push-workout` — pick this week's workouts based on your recent load

### Getting the most out of it

- **Be direct.** "Analyze my last three rides and tell me if I need a rest week" works better than "how am I doing?"
- **Push back on what Claude says.** If a workout suggestion looks wrong for your fitness, say so — the skills are opinionated, not authoritative.
- **Update your FTP when it drifts.** Edit `config.py`, then also update the FTP setting on your head unit — the workout files use `%FTP`, so they auto-scale.

If you don't want to use Claude, all the underlying scripts (`analyze.py`, `analyze_ride.py`, `push_workout.py --list`) work standalone from the command line.

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
