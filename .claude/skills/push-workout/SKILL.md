---
name: push-workout
description: Schedule one or more workouts from the registry onto the user's intervals.icu calendar. intervals.icu then auto-syncs them to the Wahoo ELEMNT BOLT. Use when the user asks to schedule a workout, push a training file to Wahoo, plan the week's rides, or "add X workout for [day]". Reliable path that bypasses fragile .fit / .zwo file imports.
---

# push-workout

Get planned workouts onto the user's Wahoo ELEMNT via intervals.icu — no file uploads, no import errors.

**How this beats file uploads:** intervals.icu → Wahoo Cloud is a first-class integration (since May 2024). We POST the workout as Workout Description Language (WDL) text to their API; intervals.icu generates the FIT on their servers and pushes it to the ELEMNT within their 7-day sync window. The `push_workout.py` codepath is the same one their own web builder uses — it works when drag-drop .fit / .zwo files silently fail with "unable to parse file".

## Prerequisites (verify once, remind the user if any step is missing)

1. **API key** — stored at `./intervals_icu_api_key` (or via `INTERVALS_API_KEY` env var). If missing, the user gets one from **intervals.icu → Settings → Developer**.
2. **Wahoo sync enabled in intervals.icu** — Settings → Wahoo → authorize, tick "Upload planned workouts", **set the workout-type filter (NOT "None"** — leaving it "None" silently blocks sync; this is the #1 gotcha).

## Steps

1. **Pick the workouts and days.** If the user asked for a full week, choose 2–4 workouts from the registry that fit their recent training state. A balanced polarized-ish rhythm for an endurance rider:
   - 1× Z2 aerobic day (`z2_60`)
   - 1× threshold quality (`sst_3x10` or the route-tolerant `sst_40km_route`)
   - Optional 1× VO2 day (`vo2_5x3`) — only if recent decoupling / TSS load shows good recovery
   - 1× long ride (`long_z2_tempo` or `60km_sst_vo2`)
   - Rest days between quality days — leave the calendar blank, don't push a workout
   Consult `training-status` first if you're unsure about current fatigue.

2. **Pre-flight — check registry**:
   ```bash
   python3 push_workout.py --list
   ```
   Shows keys, names, and durations.

3. **Dry-run first** for anything unusual:
   ```bash
   python3 push_workout.py sst_3x10 --dry-run --date 2026-08-15 --time 07:00
   ```
   Confirms the WDL and duration look right.

4. **Push each workout** (parallelizable — multiple `python3 push_workout.py ...` invocations in one Bash call):
   ```bash
   python3 push_workout.py z2_60 --date 2026-08-15 --time 07:00
   python3 push_workout.py sst_3x10 --date 2026-08-16 --time 07:00
   python3 push_workout.py long_z2_tempo --date 2026-08-18 --time 07:00
   ```
   Each prints an event ID + calendar URL. **The event ID confirms the workout landed on the server** — don't skip reading these back.

5. **Report back** — show the user the week's schedule as a table, and remind them of the intervals.icu → Wahoo checkbox if this is their first push.

## Reporting

Structured brief:
- **Table** — day / date / time / workout name / event ID
- **Load estimate** — approximate total weekly TSS at current FTP (`total_duration_s(steps) * IF^2 / 3600`)
- **Where to see it** — direct links:
  - Calendar: https://intervals.icu/calendar
  - Individual workout: `https://intervals.icu/workout/i<event_id>`
- **What the user needs to do**: confirm Wahoo sync is armed, then open Wahoo app to trigger the push.

## Common failure modes

| Symptom | Cause / Fix |
|---|---|
| `HTTP 403 Cloudflare error 1010` | Python-urllib UA banned. `push_workout.py` already sets a custom UA; if this reappears, bump the UA string. |
| `HTTP 401` | Bad API key. Recheck `intervals_icu_api_key` file contents; regenerate at intervals.icu → Settings → Developer if needed. |
| Landed on calendar but not on the ELEMNT | Wahoo sync not fully configured. Send user to intervals.icu → Settings → Wahoo and confirm both toggles + the workout-type filter. |
| `HTTP 429` | Rate-limited. Wait `Retry-After` seconds; the tool prints this. |
| `unknown workout <key>` | Typo. Run `--list` to see registry keys. |

## Adding a new workout to the schedule flow

If the user wants a workout that isn't in the registry, invoke the `build-workout` skill first to design and register it, then come back here to schedule it. `push-workout` only schedules workouts that already exist in `WORKOUTS` in `build_workout_fit.py`.

## Do NOT

- Do NOT recommend Wahoo mobile app's "Add Activity → Upload .fit" path — that's for completed activity files and always fails for planned workouts.
- Do NOT drag-drop the `.fit` on intervals.icu unless the API path is unavailable. The .fit *is* spec-clean, but their drag-drop parser has been buggy for two years.
- Do NOT push a workout for a date more than 7 days out — Wahoo's sync window is 7 days.
- Do NOT push same-day workouts for a Wahoo device before ~06:00 local user time; sync is timezone-fragile for today's date.
