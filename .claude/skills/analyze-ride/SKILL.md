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
- **ASCII visualizations** — mandatory. See `## Visualizations` below.
- **Durability read** — always
- **What to notice / do next** — one or two actionable takeaways

Keep the tone direct. Interpret, don't just repeat.

## Visualizations

Every ride analysis must include at least the first three of these. Add the others when they clarify a specific finding. ASCII only — render in fenced code blocks so alignment survives.

### 1. Power-zone distribution (always)

Horizontal bars, one row per Coggan zone, width scaled to time-in-zone. Include % and mm:ss. Mark the target zone(s) for the ride's stated intent with `◀ target`.

```
Z1  Recovery      ██                            8%   07:12
Z2  Endurance     ████████████                 30%   26:15  ◀ target
Z3  Tempo         ████████                     14%   12:11
Z4  Threshold     █████████████                18%   15:52
Z5  VO2max        ██████████                   13%   11:28
Z6  Anaerobic     ██████                        6%   05:15
Z7  Neuromuscular ██████████                   11%   09:47
```

### 2. Heart-rate zone distribution (always)

Same treatment as power, based on HR zones from `HRMAX` in `config.py`. Compare against the power distribution — HR skewed higher than power = fatigue or heat; HR skewed lower = fresh / cool day.

### 3. Quartile pacing (always for rides ≥ 45 min)

Q1..Q4 as a compact table AND a mini power-and-HR sparkline. Draw the P/HR ratio trend with arrows (`↗ ↘ →`) so drift direction is instantly visible.

```
        Q1     Q2     Q3     Q4
Power   215    207    215    213   W
HR      158    158    158    162   bpm
P/HR   1.36   1.31   1.36   1.32   →  ↘  ↗  ↘   (fade: none)
```

Follow with a one-line durability verdict (`good / normal drift / meaningful fade / severe fade`).

### 4. Best-power curve (when peaks are notable)

Compact log-ish x-axis for 5s, 30s, 1m, 5m, 10m, 20m, 60m. Watts + %FTP + bar.

```
5s    780W  390%FTP  ████████████████████████
30s   520W  260%FTP  ████████████████
1m    380W  190%FTP  ████████████
5m    238W  119%FTP  ███████    ← VO2 window
20m   190W   95%FTP  █████      ← near-threshold
60m   172W   86%FTP  ████
```

Annotate any window that crosses a meaningful threshold (VO2, threshold, ceiling).

### 5. Lap / interval sketch (interval sessions)

One row per lap. Show target vs actual, and NP where it diverges from avg.

```
     avg    NP    HR   %FTP  target
I1   215   217   158    108%   100%   ██████████▏
I2   207   210   158    104%   100%   ██████████
I3   215   228   158    108%   100%   ██████████▏  (NP > avg: wind/hills)
I4   213   219   159    107%   100%   ██████████▏
I5   238   241   162    119%   100%   ████████████ ← ceiling
```

### 6. Elevation + power on long rides (optional, when climbs shape the story)

10 km buckets. Small profile bar + a mini power dot per bucket. Flag over-cap segments.

```
 0–10   ▁▁▁     +12m   avg 145W
10–20   ▂▃▄     +45m   avg 162W
20–30   ▆▇█     +88m   avg 231W  ← over-cap (target 180)
30–40   █▇▆     -50m   avg 174W
```

## Rules for the ASCII

- Wrap in triple-backtick fences so monospace alignment survives Markdown rendering.
- Bar unit `█` = ~2 %. Keep the widest row ≤ 40 chars so it fits a narrow terminal.
- Never invent numbers to fill a chart. If a section (e.g. laps) is not present in the ride, skip that visualization — do not fabricate one.
- Numbers align in columns. Percent + duration always appear next to the bar.
