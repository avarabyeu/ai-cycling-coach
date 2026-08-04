---
name: sync-rides
description: Sync fresh .fit activity files from Dropbox and re-ingest into the SQLite training DB. Use when the user asks to update rides, refresh training data, pull latest activities, or mentions new rides to analyze. Always run this first if the user's question depends on recent activity data.
---

# sync-rides

Pull fresh `.fit` files from the authoritative Dropbox source and update `activities.db`.

## Steps

1. **Sync from Dropbox** (Wahoo ELEMNT auto-uploads to `dropbox:Apps/WahooFitness`):
   ```bash
   rclone copy "dropbox:Apps/WahooFitness" ./WahooFitness --progress
   ```

2. **Ingest into SQLite** — incremental, only new/changed files are parsed:
   ```bash
   python3 parse_activities.py
   ```

Run both in a single Bash call chained with `&&`. Both are idempotent — safe to re-run.

## Reporting

After running, report the delta:
- How many new files transferred by rclone
- How many new rows added to the DB (parser prints `done: N new, M unchanged, ...`)

If new rides came in, briefly note the newest one's date and distance so the user can decide whether to dig deeper.

## Notes

- The rclone remote `dropbox:` must already be configured; if it errors, tell the user to run `rclone config`.
- If parsing fails on a specific file, the parser logs it and continues — mention any failures.
- The DB scales cleanly to thousands of rides; no need to pre-check file counts.
