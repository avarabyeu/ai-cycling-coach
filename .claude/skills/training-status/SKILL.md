---
name: training-status
description: Summarize recent training load, YTD totals, week-over-week trends, and current fitness state. Use when the user asks about YTD, year-to-date, monthly totals, weekly load, form/fitness, "how am I doing", or wants a high-level status check across many rides. For a single ride, use analyze-ride instead.
---

# training-status

Give the user a big-picture read on their training block using the SQLite summary table (fast — no `.fit` re-parsing needed).

## Steps

1. **Sync first** — invoke `sync-rides` unless it's clearly been run in this conversation.

2. **Pick the right canned view(s)** based on the question:
   ```bash
   python3 analyze.py ytd       # year-to-date totals
   python3 analyze.py yoy       # year-over-year
   python3 analyze.py monthly   # month-by-month for current year
   python3 analyze.py recent    # last 6 weeks of rides (one row per ride)
   python3 analyze.py ftp       # hardest ~60–90 min NP efforts (FTP-proxy shortlist)
   python3 analyze.py weeks     # last 12 weeks of weekly TSS/km/hours
   ```

3. **For custom slices** run ad-hoc SQL:
   ```bash
   sqlite3 -header -column activities.db "SELECT ... FROM activities WHERE ..."
   ```

## Coaching signals to compute and comment on

Don't just dump the tables. Interpret across at least these axes.

### Load management
- **Weekly TSS trend** over the last 4–6 weeks. Ideal build: gradual rise, then a down-week every 3–4. Flat-line high loads or two hard weeks stacked = fatigue risk.
- **Ride-count vs hours** — is the pattern lots of short hard rides, few long easy ones, or a healthy mix?
- **Sustained >600 TSS/week for 3+ weeks** is functional-overreach territory. Recommend a down-week before the next build.

### Intensity mix
- **Count IF ≥ 0.90 rides in the last 10–14 days.** More than 2–3 is heavy for an endurance-tilted rider; more than 4 is a burnout risk.
- **Z2 : quality ratio** — for base-building blocks, aim for ~3:1 Z2 rides vs threshold/VO2 sessions. If it's closer to 1:1, the rider is intensity-heavy and probably not accumulating aerobic capacity.

### Fitness trajectory
Compare recent NP on similar-length rides to earlier baselines (same route, same duration).
- Rising NP at flat/lower HR → fitness gain
- Flat NP over multiple weeks → plateau; consider FTP re-test or a stimulus change
- Falling NP at higher HR → detrained (post-layoff) or fatigued (mid-block)

### Recovery / gaps
- Gaps of 3+ days between rides — planned rest or forced (travel, illness)?
- Post-gap first ride's Pw:HR is the tell: clean numbers = came back fresh; +5-10% drift = under-recovered.

### Data quality
Watch for occasional zero-power quartiles or unusually low avg_power alongside high NP (VI > 1.6 on a solo endurance ride). Those flag a power meter dropout — the summary stats will be biased.

## Reporting

Structure:
1. **Headline number** — the one metric that captures the block (biggest week? YTD milestone? fatigue signal?).
2. **1–2 tables** at most — pick views that answer the actual question.
3. **Coaching read** — 3–5 sentences on what the data says.
4. **What to do next** — one concrete recommendation (rest week, FTP re-test, more Z2, etc.).

Keep it tight. A coach's brief, not an analytics dashboard.

## Notes

- Working FTP / HRMAX live in `config.py`. Reference the current values when discussing zones, but be prepared to recommend a re-test if the FTP-proxy queries show a rider is consistently outperforming their set FTP.
- If a rider's IF is consistently in the tempo/threshold range on "easy" days, flag it. Group-ride dynamics or terrain drift often turn planned Z2 into tempo — that's worth surfacing.
