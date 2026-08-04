"""
Push a workout from the registry to your intervals.icu calendar.

intervals.icu then generates the .fit server-side and syncs it to your Wahoo
ELEMNT via their native Wahoo Cloud integration (May 2024+). This is the
most reliable path — no manual file uploads, no import errors.

Prerequisites:
  1) Get your API key: intervals.icu → Settings → Developer.
  2) Export it:  export INTERVALS_API_KEY='k-xxxx...'
     Or write it to ./.intervals_api_key  (chmod 600).
  3) Enable Wahoo sync:  intervals.icu → Settings → Wahoo → authorize,
     tick "Upload planned workouts", set a workout-type filter (NOT "None"
     — that silently blocks sync).

Usage:
  python3 push_workout.py --list                      # list available workouts
  python3 push_workout.py sst_3x10                    # schedule for today
  python3 push_workout.py sst_3x10 --date 2026-07-24
  python3 push_workout.py sst_3x10 --date 2026-07-24 --time 07:00
  python3 push_workout.py sst_3x10 --dry-run          # show payload only

Ref: https://forum.intervals.icu/t/intervals-icu-api-integration-cookbook/80090
"""

import argparse
import base64
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, date
from pathlib import Path

from build_workout_fit import WORKOUTS, build_wdl, total_duration_s

API_URL = "https://intervals.icu/api/v1/athlete/0/events"


def get_api_key():
    """Read API key from env var or a local key file."""
    key = os.environ.get("INTERVALS_API_KEY")
    if key:
        return key.strip()
    for fname in ("intervals_icu_api_key", ".intervals_api_key"):
        p = Path(__file__).parent / fname
        if p.exists():
            return p.read_text().strip()
    return None


def build_payload(workout_key, when: datetime):
    """Assemble the JSON body for POST /api/v1/athlete/0/events."""
    if workout_key not in WORKOUTS:
        raise ValueError(
            f"unknown workout {workout_key!r}. "
            f"Available: {', '.join(sorted(WORKOUTS))}"
        )
    name, steps, _ = WORKOUTS[workout_key]()
    wdl = build_wdl(name, steps)
    duration = total_duration_s(steps)

    return {
        "category": "WORKOUT",
        "type": "Ride",
        "name": name,
        # intervals.icu treats this as the athlete's LOCAL time — no timezone.
        "start_date_local": when.strftime("%Y-%m-%dT%H:%M:%S"),
        "description": wdl,
        "moving_time": duration,
    }


def post_event(payload, api_key, dry_run=False):
    body = json.dumps(payload).encode()
    if dry_run:
        print(json.dumps(payload, indent=2))
        return None

    # HTTP Basic: username literal "API_KEY", password = user's key.
    auth = base64.b64encode(f"API_KEY:{api_key}".encode()).decode()
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Cloudflare (in front of intervals.icu) 403s the default python-urllib UA.
            "User-Agent": "ai-cycling-coach/1.0 (+github.com/avarabyeu/ai-cycling-coach)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        if e.code == 401:
            print("ERROR: 401 unauthorized — check INTERVALS_API_KEY.", file=sys.stderr)
        elif e.code == 429:
            retry = e.headers.get("Retry-After", "?")
            print(f"ERROR: 429 rate-limited. Retry-After={retry}s.", file=sys.stderr)
        else:
            print(f"ERROR: HTTP {e.code}\n{detail}", file=sys.stderr)
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(
        description="Push a workout to your intervals.icu calendar (auto-syncs to Wahoo).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("workout", nargs="?", help="workout key (see --list)")
    ap.add_argument("--date", help="YYYY-MM-DD, defaults to today")
    ap.add_argument("--time", default="06:00", help="HH:MM local, default 06:00")
    ap.add_argument("--dry-run", action="store_true", help="print payload; don't POST")
    ap.add_argument("--list", action="store_true", help="list available workouts and exit")
    args = ap.parse_args()

    if args.list:
        print("Available workouts:")
        for key, fn in sorted(WORKOUTS.items()):
            name, steps, _ = fn()
            dur = total_duration_s(steps)
            print(f"  {key:<18} {name:<28} {dur // 60:>3.0f} min")
        return

    if not args.workout:
        ap.error("workout key required (use --list to see options)")

    d = date.fromisoformat(args.date) if args.date else date.today()
    hh, mm = map(int, args.time.split(":"))
    when = datetime(d.year, d.month, d.day, hh, mm)

    payload = build_payload(args.workout, when)

    if not args.dry_run:
        api_key = get_api_key()
        if not api_key:
            print(
                "ERROR: no API key.\n"
                "  export INTERVALS_API_KEY='k-xxxx...'   (get it from intervals.icu → Settings → Developer)\n"
                "  or write it to ./.intervals_api_key",
                file=sys.stderr,
            )
            sys.exit(1)

    result = post_event(payload, api_key=None if args.dry_run else api_key, dry_run=args.dry_run)

    if result is not None:
        event_id = result.get("id")
        print(f"✓ pushed  {payload['name']!r}  → intervals.icu event {event_id}")
        print(f"  scheduled for {when.isoformat()}")
        print(f"  will sync to Wahoo on that day's ELEMNT (must be within 7-day window)")
        print(f"  view: https://intervals.icu/calendar")


if __name__ == "__main__":
    main()
