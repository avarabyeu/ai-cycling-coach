---
name: analyze-ride
description: Deep-dive coaching analysis of a single ride — power/HR zones, quartile pacing, Pw:HR decoupling, best-power windows, laps. Use when the user asks to analyze the latest workout/ride/session, review a specific ride file, wants a breakdown of "how did that ride go", or requests feedback on a training session. Invoke sync-rides first if the ride is expected to be new.
---

# analyze-ride

Run the deep-dive analyzer on a single `.fit` file and interpret the numbers as a cycling coach would.

## Steps

1. **Ensure fresh data.** If the ride might not be in the DB yet, invoke `sync-rides` first.

2. **Run the analyzer.** Default is the newest file in `WahooFitness/`:
   ```bash
   python3 analyze_ride.py                            # latest
   python3 analyze_ride.py "WahooFitness/<file>.fit"  # specific
   ```

3. **Also pull the summary row** from SQLite so you have distance, elevation, TSS, IF alongside the deep-dive:
   ```bash
   sqlite3 -header -column activities.db "SELECT local_date, ROUND(distance_km,1) km, ROUND(duration_s/3600.0,2) hr, ROUND(elevation_m) elev, avg_hr, max_hr, avg_power, np_power, ROUND(tss) tss, intensity FROM activities ORDER BY start_time DESC LIMIT 1;"
   ```

## Coaching interpretation framework

After running the tool, produce a short coaching read structured around these signals. Don't just re-format the tool output — interpret it.

### Ride type / intent
Infer from IF and power distribution:
- IF < 0.70 → recovery / easy Z2
- 0.70–0.80 → endurance day
- 0.80–0.90 → tempo / long tempo
- 0.90–0.95 → threshold work
- ≥ 0.95 → near-max threshold or VO2 session

Comment if the actual distribution doesn't match what was intended (e.g. "billed as easy, was tempo").

### Durability — the most important signal
**Pw:HR decoupling** (1st half vs 2nd half power/HR ratio):
- ≤ 2 % or negative → good durability, well fueled / paced
- 2–5 % → normal aerobic drift
- 5–10 % → meaningful fade — usually fueling shortfall or leg fatigue
- \> 10 % → severe fade — name the likely cause (fueling deficit, cumulative training load, illness, under-slept)

Also look at the quartile breakdown: NP dropping sharply in Q4 while HR stays high = classic late-ride bonk / glycogen depletion.

### Peak-power windows
Compare to the working FTP (from `config.py`; `analyze_ride.py` displays it in the header):
- 5-min at ≥ 115 % FTP → strong VO2 effort
- 20-min at ≥ 95 % FTP inside a longer ride → likely over-cap on a climb (flag as pacing risk on long rides)
- 60-min at ≥ 90 % FTP → near-threshold hour effort

If several recent rides converge on similar 20-min or 60-min NPs, mention it — that's an FTP re-test signal (invoke `estimate-ftp`).

### Cadence
Endurance-cyclist norm is ~85–95 rpm. Below 80 = grinding (often steep climbs with too-tall gearing → shifts load onto calves → cramps and shortened endurance).

Compare against the rider's typical cadence from recent rides — a drop of 5+ rpm from baseline is a fatigue signal.

### Zones
For long rides that should be Z2: > 85 % time in Z1–Z2 is healthy. Z3+ time creeping up on "easy" rides is drift worth naming.

For interval sessions: check whether the actual time in the target zone matches the intent. Group-ride dynamics or terrain often overrun structured workouts by one zone.

### Data-quality checks
Before interpreting: verify no obvious sensor issues. If avg_power is unusually low but NP is high, or if a quartile shows 0 for power/HR, flag the possibility of a dropped sensor (dead battery, ANT+ pairing loss) and note that summary stats may be biased.

## Reporting

Deliver a concise coaching brief, not a data dump:
- **Headline** — one line: what kind of ride it was + the standout finding
- **Key metrics** — a table only if it clarifies the story
- **Durability read** — always
- **What to notice / do next** — one or two actionable takeaways

Keep the tone direct. Interpret, don't just repeat.
