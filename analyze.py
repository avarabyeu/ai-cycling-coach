"""
Coaching queries on the SQLite activity database.
Usage: python3 analyze.py [ytd|yoy|monthly|recent|ftp|weeks]
"""
import sqlite3
import sys
from datetime import date
from pathlib import Path

DB = Path(__file__).parent / "activities.db"
THIS_YEAR = date.today().year


def q(sql, params=()):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def print_rows(rows):
    if not rows:
        print("(no rows)")
        return
    cols = rows[0].keys()
    widths = [max(len(c), max(len(str(r[c])) for r in rows)) for c in cols]
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(str(r[c]).ljust(w) for c, w in zip(cols, widths)))


def ytd():
    print_rows(q(f"""
        SELECT COUNT(*) rides,
               ROUND(SUM(distance_km),1) km,
               ROUND(SUM(duration_s)/3600.0,1) hours,
               ROUND(SUM(elevation_m)) elev_m,
               ROUND(AVG(avg_power),0) avg_pwr,
               ROUND(AVG(np_power),0)  avg_np,
               MAX(max_power)          peak_pwr
        FROM activities WHERE year={THIS_YEAR} AND sport='cycling'
    """))


def yoy():
    print_rows(q("""
        SELECT year, COUNT(*) rides,
               ROUND(SUM(distance_km)) km,
               ROUND(SUM(duration_s)/3600.0) hours,
               ROUND(SUM(elevation_m)) elev,
               ROUND(AVG(np_power),0)  avg_np
        FROM activities WHERE sport='cycling' GROUP BY year ORDER BY year
    """))


def monthly():
    print_rows(q(f"""
        SELECT month, COUNT(*) rides,
               ROUND(SUM(distance_km)) km,
               ROUND(SUM(duration_s)/3600.0,1) hours,
               ROUND(SUM(elevation_m)) elev,
               ROUND(AVG(np_power),0) avg_np
        FROM activities WHERE year={THIS_YEAR} AND sport='cycling'
        GROUP BY month ORDER BY month
    """))


def recent():
    print_rows(q("""
        SELECT local_date date, ROUND(distance_km,1) km,
               ROUND(duration_s/60.0) min, ROUND(elevation_m) elev,
               avg_hr, avg_power, np_power
        FROM activities
        WHERE sport='cycling' AND local_date >= date('now','-42 days')
        ORDER BY local_date DESC
    """))


def ftp():
    """Best hard ~60-90 min normalized power efforts as FTP proxies."""
    print_rows(q("""
        SELECT local_date date, ROUND(duration_s/60.0) min,
               np_power, avg_power, max_power, avg_hr
        FROM activities
        WHERE sport='cycling' AND np_power IS NOT NULL
          AND duration_s BETWEEN 60*60 AND 95*60
        ORDER BY np_power DESC LIMIT 10
    """))


def weeks():
    print_rows(q("""
        SELECT strftime('%Y-W%W', local_date) wk,
               COUNT(*) rides,
               ROUND(SUM(distance_km)) km,
               ROUND(SUM(duration_s)/3600.0,1) hrs,
               ROUND(SUM(elevation_m)) elev,
               ROUND(AVG(np_power),0) avg_np
        FROM activities WHERE sport='cycling'
          AND local_date >= date('now','-84 days')
        GROUP BY wk ORDER BY wk
    """))


CMDS = {"ytd": ytd, "yoy": yoy, "monthly": monthly,
        "recent": recent, "ftp": ftp, "weeks": weeks}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ytd"
    if cmd not in CMDS:
        print(f"unknown command. options: {', '.join(CMDS)}")
        sys.exit(1)
    CMDS[cmd]()
