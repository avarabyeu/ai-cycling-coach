---
name: build-workout
description: DESIGN a new structured cycling workout and register it in the workout library (build_workout_fit.py). Emits .fit, .zwo, and .wdl.txt files. Use when the user wants to CREATE a workout that doesn't exist yet — e.g. new intervals, a specific SST/VO2/threshold session, or a modification to an existing registry entry. For SCHEDULING an already-registered workout onto the user's calendar/Wahoo, use `push-workout` instead.
---

# build-workout

Design a workout, add it to the registry in `build_workout_fit.py`, and regenerate all output files. This skill is about **authoring**; use `push-workout` to schedule an existing workout onto the intervals.icu calendar.

## Steps

1. **Design the workout.** Talk it through with the user if the ask is vague. Typical structure:
   - Warm-up (5–15 min, ramping from ~50 % to ~65 % FTP)
   - Main set(s) — the training stimulus
   - Recovery bridges between sets when needed
   - Endurance tail (optional)
   - Cool-down (5–10 min, ramp *upward from low* — see quirk below)

2. **Add a function to `build_workout_fit.py`** — mirror the existing ones. Signature: returns `(name, steps, out_path)`. Use the helpers already in the file:
   - `step(name, duration_s, intensity, pct_low, pct_high)` — a target-power step. `pct_*` are integer % FTP (e.g. 88 = 88% FTP). **Use only these intensities** (BOLT V1 firmware safe): `Intensity.WARMUP` (2), `Intensity.ACTIVE` (0), `Intensity.REST` (1, for between-interval rest), `Intensity.COOLDOWN` (3). Never `RECOVERY(4)` / `INTERVAL(5)` / `OTHER(6)`.
   - `repeat(from_index, repetitions)` — repeat the block of steps from `from_index` inclusive up to (but not including) the repeat itself. Repetition count is the *total* number of times through, not the number of extra loops.

3. **Register in the `WORKOUTS` dict** at the bottom of the file. Key is the short slug used by `push_workout.py`; value is the workout function.

4. **Run the builder**:
   ```bash
   python3 build_workout_fit.py
   ```
   Emits `workouts/<name>.fit`, `workouts/<name>.zwo`, and `workouts/<name>.wdl.txt`. The builder round-trip-verifies each file — if it prints "wrote", the file passed structural validation.

5. **Update the workout registry table in `CLAUDE.md`** — same table format as existing rows.

## Non-negotiable FIT rules (verified by round-trip and audit)

The `step()` helper enforces these; only relevant if you edit lower-level code directly:

- **`WorkoutStepMessage.duration_time` setter takes milliseconds**, not seconds. The helper handles this.
- **`custom_target_value_low/high` with `target_type=POWER` and `target_value=0` is `% FTP`** (0–1000). Values ≥ 1000 mean absolute watts (subtract 1000). Always use % FTP so the head-unit setting drives actual watts.
- **`low <= high` is REQUIRED** for the power range. The helper raises `ValueError` on inversion. Cool-downs are written as `(45, 60)` — the head unit renders it as a ramp because `Intensity.COOLDOWN` is set.
- **`FileIdMessage.manufacturer` must be `Manufacturer.GARMIN` (1)** with `garmin_product = GarminProduct.CONNECT` (65534). `DEVELOPMENT` (255) is rejected by intervals.icu.
- **Intensity 0–3 only** for BOLT V1 firmware compat (see helper note above).
- **All steps must use the same `target_type`** — intervals.icu rejects mixed. We always use `POWER`.
- **Repeat encoding**: `duration_type=REPEAT_UNTIL_STEPS_CMPLT`, `duration_step=<step-index to loop back to>`, `target_type=OPEN`, `target_value=<repetition count>`. Count goes in `target_value`, not a dedicated field.

## Zone reference (percent of FTP)

Workout targets are always in `%FTP`; the head-unit setting scales them to watts. The rider's actual FTP lives in `config.py`.

| Zone | % FTP | Purpose |
|---|---|---|
| Z1 Recovery | < 55 | spin only |
| Z2 Endurance | 56–75 | long rides / base |
| Z3 Tempo | 76–87 | "comfortably hard" |
| Z4 Sweet Spot | 88–94 | FTP lifter |
| Z5 VO2 | 106–120 | ceiling raiser |
| Z6 Anaerobic | 120+ | short hard bursts |

## After building — how to get it on the head unit

Once the workout is in the registry and files are regenerated, **invoke the `push-workout` skill** to schedule it onto the user's intervals.icu calendar. That skill knows the API push flow, the Wahoo sync toggles, and the gotchas.

Do NOT recommend the Wahoo mobile app's "Add Activity → Upload .fit" path — that's for completed activity files, not planned workouts. Every attempt through it fails.

## Reporting (design phase)

Show:
- The step list with durations and %FTP targets
- Estimated single-pass duration and total duration (with repeats)
- Estimated TSS if useful
- Which registry key (`<workout_name>`) was added, so the user (or the follow-up `push-workout` call) can schedule it via `python3 push_workout.py <key> --date ...`

