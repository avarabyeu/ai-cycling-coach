---
name: estimate-ftp
description: Estimate FTP using multiple methods (20-min × 0.95, Critical Power model, sustained 60–90 min NP median) across the last ~60 days of rides. Use when the user asks about their current FTP, wants an FTP re-estimate, questions whether the working number is right, or after a significant training block. Also propose whether a formal 20-min test is warranted.
---

# estimate-ftp

Cross-check FTP with several estimators. No single number is authoritative — convergence across methods is what matters.

## Steps

1. **Ensure fresh data** — invoke `sync-rides` first.

2. **Run the multi-method estimator.** It analyzes peak power windows across all rides in the last ~60 days:

```bash
python3 - <<'PY'
from fitparse import FitFile
from pathlib import Path
import sqlite3, statistics as st

FIT_DIR = Path("WahooFitness")

def best_avg(powers, window):
    if len(powers) < window: return None
    cum = [0]
    for v in powers: cum.append(cum[-1] + v)
    return max((cum[i+window]-cum[i])/window for i in range(len(powers)-window+1))

conn = sqlite3.connect("activities.db")
rows = conn.execute("""
  SELECT file FROM activities
  WHERE sport='cycling' AND local_date >= date('now','-60 days')
  ORDER BY local_date
""").fetchall()

windows = [5, 30, 60, 5*60, 8*60, 10*60, 20*60, 60*60]
labels  = ["5s","30s","1m","5m","8m","10m","20m","60m"]
peaks = {w: [] for w in windows}
for (fname,) in rows:
    path = FIT_DIR/fname
    if not path.exists(): continue
    powers = []
    for msg in FitFile(str(path)).get_messages("record"):
        p = None
        for f in msg:
            if f.name == "power": p = f.value; break
        powers.append(p or 0)
    for w in windows:
        b = best_avg(powers, w)
        if b: peaks[w].append((b, fname))

print(f"Analyzed {len(rows)} rides\n")
best = {}
print("All-time peaks in this window:")
for w, lbl in zip(windows, labels):
    if not peaks[w]: continue
    peaks[w].sort(reverse=True)
    b, f = peaks[w][0]
    best[lbl] = b
    print(f"  {lbl:<5} {b:>5.0f} W   {f}")

print("\nFTP estimators:")
if "20m" in best: print(f"  20-min × 0.95 (Coggan)         : {best['20m']*0.95:>5.0f} W")
if "5m" in best:  print(f"  5-min × 0.85 (rough)           : {best['5m']*0.85:>5.0f} W")
if "60m" in best: print(f"  60-min NP proxy (floor)        : {best['60m']:>5.0f} W")
if "5m" in best and "20m" in best:
    t5, t20 = 300, 1200
    cp = (best["20m"]*t20 - best["5m"]*t5) / (t20 - t5)
    wprime = (best["5m"] - cp) * t5
    print(f"  Critical Power (5/20 model)    : {cp:>5.0f} W   W' = {wprime/1000:.1f} kJ")

r = conn.execute("""
    SELECT local_date, np_power, ROUND(duration_s/60.0) mins, ROUND(intensity,2) if_
    FROM activities WHERE sport='cycling'
      AND duration_s BETWEEN 60*60 AND 95*60
      AND local_date >= date('now','-60 days')
    ORDER BY np_power DESC LIMIT 5
""").fetchall()
print("\nHardest sustained 60–95 min efforts:")
for d, np, m, iF in r:
    print(f"  {d}  NP {np} W  ({m} min, IF {iF})")
if r:
    med = st.median([x[1] for x in r[:3]])
    print(f"\n  Median of top-3 sustained NP   : {med:>5.0f} W")
conn.close()
PY
```

## Interpretation

Aim for **convergence** across ≥ 3 methods. If 20-min × 0.95, CP model, and top-3-sustained-NP-median all land within a 10 W band, that's a defensible FTP.

Watch for these divergences:

- **5-min × 0.85 running high vs 20-min × 0.95** → strong VO2 relative to threshold (room to grow FTP with more Z4/threshold work).
- **60-min NP much lower than 20-min × 0.95** → the 20-min peak was inside a structured workout with recovery baked in, not a pure max effort. Adjust down slightly.
- **CP model producing high W'** (> 20 kJ) → you're capturing anaerobic contribution, not steady-state FTP. Distrust.
- **All peaks from group rides** → hard to isolate the rider's own effort from drafting benefit. Note that a formal test would be more reliable.

## Reporting

Give the user:
1. A table of methods → W, marking convergent ones.
2. Explicit interpretation of any outliers.
3. **One number**: the recommended working FTP, with a confidence range (e.g. "245 W, range 240–255").
4. Whether a formal 20-min test is warranted:
   - **Yes** if the sustained-NP median and 20-min × 0.95 differ by > 8 W (data is noisy)
   - **Yes** if all peaks were inside interval workouts and none from a dedicated max effort
   - **No** if 3+ recent max-effort attempts cluster tightly (already a de facto test)

## Applying a new FTP

If FTP changes:
1. Update `config.py` — the `FTP` constant (drives zone reports in `analyze_ride.py`).
2. Update the head-unit FTP setting (drives actual watts on planned workouts, since `.fit` targets are `%FTP`).

The workout `.fit` files themselves do **not** need to be regenerated — they encode `%FTP`, not absolute watts.
