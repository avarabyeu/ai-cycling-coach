"""
Deep-dive analysis of a single .fit ride file.

Reports: power-zone time, HR-zone time, quartile pacing breakdown,
Pw:HR decoupling (durability), best rolling power windows, lap structure.

Usage:
  python3 analyze_ride.py                          # newest .fit in WahooFitness/
  python3 analyze_ride.py WahooFitness/<file>.fit  # specific file
"""

import statistics as st
import sys
from pathlib import Path

from fitparse import FitFile

# Personal coaching constants — read from config.py if present, else fall back
# to defaults. Copy config.example.py to config.py and set your values.
try:
    from config import FTP, HRMAX
except ImportError:
    FTP = 250
    HRMAX = 185

FIT_DIR = Path(__file__).parent / "WahooFitness"


def find_latest():
    files = sorted(FIT_DIR.glob("*.fit"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def best_rolling(series, window):
    if len(series) < window:
        return None
    cum = [0]
    for v in series:
        cum.append(cum[-1] + v)
    return max((cum[i + window] - cum[i]) / window for i in range(len(series) - window + 1))


def rolling_np(powers):
    """30-second rolling-average → 4th-power-mean → 4th-root. Same idea as TrainingPeaks NP."""
    w = 30
    if len(powers) < w:
        return 0
    cum = [0]
    for v in powers:
        cum.append(cum[-1] + v)
    ravs = [(cum[i + w] - cum[i]) / w for i in range(len(powers) - w + 1)]
    return (sum(r ** 4 for r in ravs) / len(ravs)) ** 0.25


def bar(pct):
    return "█" * int(pct / 2)


def analyze(path):
    print(f"file: {path.name}")
    records = [{f.name: f.value for f in m} for m in FitFile(str(path)).get_messages("record")]
    print(f"records: {len(records)}")
    if not records:
        return

    powers = [r.get("power") or 0 for r in records]
    hrs = [r.get("heart_rate") for r in records if r.get("heart_rate")]
    cads = [r.get("cadence") for r in records if r.get("cadence") not in (None, 0)]

    # ---- Power zones ----
    edges = [0, 0.55, 0.75, 0.87, 0.94, 1.05, 1.20, 99]
    zlbl = ["Z1 <55%", "Z2 56-75%", "Z3 76-87%", "Z4 88-94%",
            "Z5 95-105%", "Z6 106-120%", "Z7 >120%"]
    zcount = [0] * len(zlbl)
    for p in powers:
        pct = p / FTP
        for i in range(len(zlbl)):
            if pct <= edges[i + 1]:
                zcount[i] += 1
                break
    total = sum(zcount)
    print(f"\nPower zones (FTP={FTP} W):")
    for lbl, c in zip(zlbl, zcount):
        pct = 100 * c / total if total else 0
        print(f"  {lbl:<12} {c / 60:6.1f} min  {pct:5.1f}%  {bar(pct)}")

    # ---- HR zones ----
    hr_edges = [0, 0.68, 0.78, 0.87, 0.94, 1.0, 99]
    hr_lbl = ["Z1 <68%", "Z2 68-78%", "Z3 78-87%", "Z4 87-94%", "Z5 >94%"]
    hrz = [0] * len(hr_lbl)
    for h in hrs:
        pct = h / HRMAX
        for i in range(len(hr_lbl)):
            if pct <= hr_edges[i + 1]:
                hrz[i] += 1
                break
    print(f"\nHR zones (HRmax={HRMAX}):")
    for lbl, c in zip(hr_lbl, hrz):
        pct = 100 * c / sum(hrz) if hrz else 0
        print(f"  {lbl:<11} {c / 60:6.1f} min  {pct:5.1f}%  {bar(pct)}")

    # ---- Quartile pacing ----
    n = len(records)
    print("\nQuartile breakdown:")
    print(f"  {'Q':<4}{'NP':>6}{'avgP':>7}{'HR':>6}{'P/HR':>7}{'km/h':>7}")
    for q in range(4):
        seg = records[n * q // 4: n * (q + 1) // 4]
        ps = [r.get("power") or 0 for r in seg]
        hs = [r.get("heart_rate") for r in seg if r.get("heart_rate")]
        ss = [(r.get("enhanced_speed") or r.get("speed") or 0) * 3.6 for r in seg
              if (r.get("enhanced_speed") or r.get("speed") or 0) * 3.6 > 5]
        ap = st.mean(ps) if ps else 0
        ah = st.mean(hs) if hs else 0
        nps = rolling_np(ps)
        kmh = st.mean(ss) if ss else 0
        print(f"  Q{q+1:<3}{nps:>6.0f}{ap:>7.0f}{ah:>6.0f}"
              f"{(ap / ah if ah else 0):>7.2f}{kmh:>7.1f}")

    # ---- Pw:HR decoupling (1st half vs 2nd half) ----
    mid = n // 2
    def ratio(rs):
        ps = [r.get("power") or 0 for r in rs]
        hs = [r.get("heart_rate") for r in rs if r.get("heart_rate")]
        return st.mean(ps) / st.mean(hs) if hs else 0
    r1, r2 = ratio(records[:mid]), ratio(records[mid:])
    drift = (r1 - r2) / r1 * 100 if r1 else 0
    note = ("severe fade — fueling / fitness gap" if drift > 10 else
            "meaningful fade" if drift > 5 else
            "good durability" if drift > -2 else
            "got stronger in 2nd half")
    print(f"\nPw:HR decoupling: 1st half {r1:.2f} → 2nd half {r2:.2f}   drift {drift:+.1f}%  ({note})")

    # ---- Best rolling power ----
    print("\nBest rolling power:")
    for w, lbl in [(5, "5s"), (30, "30s"), (60, "1min"), (5 * 60, "5min"),
                   (10 * 60, "10min"), (20 * 60, "20min"), (60 * 60, "60min"),
                   (3 * 60 * 60, "3h")]:
        b = best_rolling(powers, w)
        if b:
            print(f"  {lbl:<6}: {b:>4.0f} W  ({100 * b / FTP:.0f}% FTP)")

    if cads:
        print(f"\nCadence: avg {st.mean(cads):.0f} rpm, median {st.median(cads):.0f}")

    # ---- Laps ----
    laps = list(FitFile(str(path)).get_messages("lap"))
    if len(laps) > 1:
        print("\nLaps:")
        for i, msg in enumerate(laps, 1):
            d = {f.name: f.value for f in msg}
            dist = (d.get("total_distance") or 0) / 1000
            dur = (d.get("total_timer_time") or 0) / 60
            elev = d.get("total_ascent") or 0
            print(f"  L{i}: {dist:5.1f} km / {dur:5.0f} min  +{elev}m  "
                  f"avgP {d.get('avg_power')}  NP {d.get('normalized_power')}  "
                  f"HR {d.get('avg_heart_rate')}")


if __name__ == "__main__":
    p = Path(sys.argv[1]) if len(sys.argv) > 1 else find_latest()
    if not p or not p.exists():
        print("no .fit file found")
        sys.exit(1)
    analyze(p)
