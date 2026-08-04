"""
Build Garmin/Wahoo-compatible .fit workout files from compact step lists.

Each workout is defined by a function that returns (name, steps, out_path).
Targets are encoded as % FTP so the head-unit's FTP setting drives actual watts.

Reference: Garmin FIT Cookbook — https://developer.garmin.com/fit/cookbook/encoding-workout-files/

FIT quirks worth remembering when editing:
- `WorkoutStepMessage.duration_time` setter takes MILLISECONDS, not seconds.
- For `custom_target_value_low/high` with `target_type=POWER` and `target_value=0`,
  values 0..1000 mean "% FTP"; values ≥ 1000 mean absolute watts (subtract 1000).
  We always use %FTP so the user's head-unit FTP setting drives the actual watts.
- `custom_target_value_low <= high` — inverted ranges break strict importers.
- A repeat step: `duration_type=REPEAT_UNTIL_STEPS_CMPLT`,
  `duration_step=<step-index to jump back to>`, `target_type=OPEN`,
  `target_value=<n repetitions>`.
- `FileIdMessage.manufacturer` must be a real value. GARMIN(1) + product=65534 (CONNECT)
  is what Garmin Connect writes; DEVELOPMENT(255) is rejected by intervals.icu.

Wahoo ELEMNT display quirks (device firmware — not fixable in the file):
- BOLT/ROAM show the CENTER of a target range, not the range endpoints.
- Ramps (warmup/cooldown ranges) display as a fixed center value, not a ramp.
"""

from datetime import datetime, timezone

from fit_tool.fit_file import FitFile
from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.workout_message import WorkoutMessage
from fit_tool.profile.messages.workout_step_message import WorkoutStepMessage
from fit_tool.profile.profile_type import (
    FileType,
    GarminProduct,
    Intensity,
    Manufacturer,
    Sport,
    SubSport,
    WorkoutCapabilities,
    WorkoutStepDuration,
    WorkoutStepTarget,
)


def step(name, duration_s, intensity, pct_low, pct_high):
    """Define a target-power step. pct_* are integer % FTP (0..1000)."""
    if pct_low > pct_high:
        raise ValueError(f"step {name!r}: pct_low ({pct_low}) > pct_high ({pct_high})")
    if not (0 <= pct_low <= 1000 and 0 <= pct_high <= 1000):
        raise ValueError(f"step {name!r}: %FTP out of 0..1000 range")
    if duration_s <= 0:
        raise ValueError(f"step {name!r}: duration must be positive")
    if not name.isascii():
        raise ValueError(f"step {name!r}: non-ASCII in step name (BOLT V1 may not render)")
    return ("step", name, duration_s, intensity, pct_low, pct_high)


def repeat(from_index, repetitions):
    """Repeat the block of steps starting at from_index up to (not including) this repeat."""
    if repetitions < 2:
        raise ValueError(f"repeat: repetitions must be >= 2 (got {repetitions})")
    return ("repeat", from_index, repetitions)


def _make_step(idx, name, duration_s, intensity, pct_low, pct_high):
    s = WorkoutStepMessage()
    s.message_index = idx
    s.workout_step_name = name
    s.intensity = intensity
    s.duration_type = WorkoutStepDuration.TIME
    s.duration_time = duration_s * 1000  # ms
    s.target_type = WorkoutStepTarget.POWER
    s.target_value = 0                    # 0 = use custom range below
    s.custom_target_value_low = int(round(pct_low))
    s.custom_target_value_high = int(round(pct_high))
    return s


def _make_repeat(idx, from_index, repetitions):
    s = WorkoutStepMessage()
    s.message_index = idx
    s.duration_type = WorkoutStepDuration.REPEAT_UNTIL_STEPS_CMPLT
    s.duration_step = from_index
    s.target_type = WorkoutStepTarget.OPEN
    s.target_value = repetitions
    s.intensity = Intensity.ACTIVE
    return s


# ---------- .zwo (Zwift workout XML) emitter -------------------------------

def _zwo_line(name, dur, intensity, lo, hi, warmup_used, cooldown_used):
    """Return (xml_line, new_warmup_used, new_cooldown_used).
    Zwift .zwo expects at most one <Warmup> and one <Cooldown> per file.
    A ranged (lo != hi) WARMUP or COOLDOWN step becomes <Warmup> / <Cooldown>
    the first time, then <Ramp> for subsequent warmup/cooldown ramps.
    All other steps — including ranged ACTIVE/REST steps — become <SteadyState>
    at the midpoint (a range means "hold within this band", not "linearly ramp")."""
    lo_f, hi_f = lo / 100.0, hi / 100.0
    mid = (lo_f + hi_f) / 2 if lo != hi else lo_f

    if intensity == Intensity.WARMUP:
        if not warmup_used and lo != hi:
            return (
                f'    <Warmup Duration="{dur}" PowerLow="{lo_f:.2f}" PowerHigh="{hi_f:.2f}"/>',
                True, cooldown_used,
            )
        if lo != hi:
            return (
                f'    <Ramp Duration="{dur}" PowerLow="{lo_f:.2f}" PowerHigh="{hi_f:.2f}"/>',
                warmup_used, cooldown_used,
            )
        return (f'    <SteadyState Duration="{dur}" Power="{mid:.2f}"/>', warmup_used, cooldown_used)

    if intensity == Intensity.COOLDOWN:
        if not cooldown_used and lo != hi:
            return (
                f'    <Cooldown Duration="{dur}" PowerLow="{lo_f:.2f}" PowerHigh="{hi_f:.2f}"/>',
                warmup_used, True,
            )
        if lo != hi:
            return (
                f'    <Ramp Duration="{dur}" PowerLow="{lo_f:.2f}" PowerHigh="{hi_f:.2f}"/>',
                warmup_used, cooldown_used,
            )
        return (f'    <SteadyState Duration="{dur}" Power="{mid:.2f}"/>', warmup_used, cooldown_used)

    # ACTIVE / REST — a range means "hold within band", so use midpoint SteadyState.
    return (f'    <SteadyState Duration="{dur}" Power="{mid:.2f}"/>', warmup_used, cooldown_used)


def _build_zwo(name, steps, out_path):
    """Emit a Zwift workout (.zwo). Adjacent on/off pairs inside a repeat collapse
    to an IntervalsT for compactness; other repeats expand inline."""
    lines = [
        '<workout_file>',
        '    <author>ai-cycling-coach</author>',
        f'    <name>{name}</name>',
        f'    <description>Generated from build_workout_fit.py — targets are %FTP.</description>',
        '    <sportType>bike</sportType>',
        '    <tags/>',
        '    <workout>',
    ]
    wu_used = cd_used = False
    i = 0
    while i < len(steps):
        s = steps[i]
        if s[0] == "repeat":
            _, from_idx, reps = s
            body = steps[from_idx:i]
            if len(body) == 2 and body[0][0] == "step" and body[1][0] == "step":
                _, _, on_d, _, on_lo, on_hi = body[0]
                _, _, off_d, _, off_lo, off_hi = body[1]
                on_p = ((on_lo + on_hi) / 2) / 100.0
                off_p = ((off_lo + off_hi) / 2) / 100.0
                lines = lines[:-2]  # drop the two lines we emitted for the loop body
                lines.append(
                    f'    <IntervalsT Repeat="{reps}" OnDuration="{on_d}" OffDuration="{off_d}" '
                    f'OnPower="{on_p:.2f}" OffPower="{off_p:.2f}"/>'
                )
            else:
                for _ in range(reps - 1):
                    for b in body:
                        if b[0] != "step":
                            continue
                        _, n, dur, intensity, lo, hi = b
                        line, wu_used, cd_used = _zwo_line(n, dur, intensity, lo, hi, wu_used, cd_used)
                        lines.append(line)
        else:
            _, n, dur, intensity, lo, hi = s
            line, wu_used, cd_used = _zwo_line(n, dur, intensity, lo, hi, wu_used, cd_used)
            lines.append(line)
        i += 1
    lines += ['    </workout>', '</workout_file>']
    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")


# ---------- intervals.icu WDL emitter ---------------------------------------

def _wdl_target(intensity, lo, hi):
    """Format the %FTP target part of a WDL step line. Ranges become 'lo%-hi%';
    equal endpoints become 'lo%'. WARMUP/COOLDOWN ranges add 'ramp' prefix."""
    if lo != hi:
        if intensity in (Intensity.WARMUP, Intensity.COOLDOWN):
            return f"ramp {lo}%-{hi}%"
        return f"{lo}-{hi}%"
    return f"{lo}%"


def build_wdl(name, steps):
    """Return an intervals.icu Workout Description Language string.
    Ref: https://forum.intervals.icu/t/workout-builder-syntax-quick-guide/123701"""
    out = []
    i = 0
    while i < len(steps):
        s = steps[i]
        if s[0] == "repeat":
            # already consumed by the block-detection below
            i += 1
            continue

        # Look ahead: is there a repeat that closes on `body = steps[from_idx:repeat_i]`
        # where from_idx == i? If so, emit "Nx" header + block.
        j = i + 1
        while j < len(steps) and steps[j][0] != "repeat":
            j += 1
        if j < len(steps):
            _, from_idx, reps = steps[j]
            if from_idx == i:
                # Block from i..j-1 repeats `reps` times.
                out.append("")
                out.append(f"{reps}x")
                for k in range(i, j):
                    _, n, dur, intensity, lo, hi = steps[k]
                    dur_min = dur / 60
                    dur_str = f"{dur_min:g}m" if dur % 60 == 0 else f"{dur}s"
                    out.append(f"- {dur_str} {_wdl_target(intensity, lo, hi)}")
                out.append("")
                i = j + 1  # skip past the repeat marker
                continue

        # Plain step
        _, n, dur, intensity, lo, hi = s
        dur_min = dur / 60
        dur_str = f"{dur_min:g}m" if dur % 60 == 0 else f"{dur}s"
        line = f"- {dur_str} {_wdl_target(intensity, lo, hi)}"
        out.append(line)
        i += 1

    # collapse leading/trailing blanks and collapse doubled blanks
    txt = "\n".join(out).strip("\n")
    while "\n\n\n" in txt:
        txt = txt.replace("\n\n\n", "\n\n")
    return txt


def total_duration_s(steps):
    """Total workout duration in seconds, expanding all repeats."""
    total = 0
    i = 0
    while i < len(steps):
        s = steps[i]
        if s[0] == "step":
            total += s[2]
            i += 1
        else:
            _, from_idx, reps = s
            body_sum = sum(b[2] for b in steps[from_idx:i] if b[0] == "step")
            # body already counted once as we walked through; add (reps-1) more
            total += body_sum * (reps - 1)
            i += 1
    return total


# ---------- FIT emitter -----------------------------------------------------

# Capabilities bitmask advertised to the head unit — matches what Garmin Connect
# writes for a power-targeted interval workout. Devices ignore unknown bits, so
# advertising more than we strictly use is safe.
_WORKOUT_CAPS = (
    WorkoutCapabilities.INTERVAL.value      # has repeat blocks
    | WorkoutCapabilities.CUSTOM.value       # has custom target ranges
    | WorkoutCapabilities.POWER.value        # uses power targets
    | WorkoutCapabilities.TCX.value          # TCX/structured workout hint
)


def _validate_step_list(name, steps):
    """Pre-flight: catch repeat-index and step-count errors before emitting bytes."""
    if len(steps) == 0:
        raise ValueError(f"{name!r}: empty step list")
    if len(steps) > 250:
        raise ValueError(f"{name!r}: {len(steps)} steps — most head units cap at ~64")
    if all(s[0] == "repeat" for s in steps):
        raise ValueError(f"{name!r}: workout must contain at least one real step")
    for i, s in enumerate(steps):
        if s[0] == "repeat":
            _, from_idx, reps = s
            if from_idx >= i:
                raise ValueError(
                    f"{name!r} step {i}: repeat from_index {from_idx} must be < step index {i}"
                )
            if from_idx < 0:
                raise ValueError(f"{name!r} step {i}: repeat from_index cannot be negative")
            body = steps[from_idx:i]
            if not any(b[0] == "step" for b in body):
                raise ValueError(
                    f"{name!r} step {i}: repeat body has no real steps"
                )


def build_workout(name, steps, out_path):
    _validate_step_list(name, steps)

    # Emit sibling .zwo for services that prefer it (intervals.icu, Zwift).
    _build_zwo(name, steps, out_path.replace(".fit", ".zwo"))

    # Emit sibling .wdl.txt — intervals.icu workout-description text.
    # This is the format their web builder accepts and their API's `description`
    # field consumes directly — the most reliable path to a Wahoo BOLT.
    wdl = build_wdl(name, steps)
    with open(out_path.replace(".fit", ".wdl.txt"), "w") as f:
        f.write(wdl + "\n")

    builder = FitFileBuilder(auto_define=True, min_string_size=16)

    fid = FileIdMessage()
    fid.type = FileType.WORKOUT
    fid.manufacturer = Manufacturer.GARMIN.value       # (1) — GARMIN, real manufacturer id
    fid.garmin_product = GarminProduct.CONNECT.value   # (65534) — what Garmin Connect writes
    fid.time_created = round(datetime.now(timezone.utc).timestamp() * 1000)
    fid.serial_number = 0x12345678
    builder.add(fid)

    wkt = WorkoutMessage()
    wkt.workout_name = name
    wkt.sport = Sport.CYCLING
    wkt.sub_sport = SubSport.ROAD
    wkt.num_valid_steps = len(steps)
    wkt.capabilities = _WORKOUT_CAPS
    builder.add(wkt)

    for i, s in enumerate(steps):
        if s[0] == "step":
            _, n, dur, intensity, lo, hi = s
            builder.add(_make_step(i, n, dur, intensity, lo, hi))
        else:
            _, from_idx, reps = s
            builder.add(_make_repeat(i, from_idx, reps))

    builder.build().to_file(out_path)

    verified = _verify_written(out_path, name, steps)
    print(f"wrote {out_path}  ({len(steps)} steps, {verified['bytes']} bytes)")


def _verify_written(path, name, steps):
    """Round-trip check: read the file back with fit-tool and assert structure.
    Raises on any mismatch. Prevents subtle regressions from reaching the head unit."""
    f = FitFile.from_file(path)
    from fit_tool.data_message import DataMessage

    data_msgs = [r.message for r in f.records if isinstance(r.message, DataMessage)]

    fid_msgs = [m for m in data_msgs if isinstance(m, FileIdMessage)]
    if len(fid_msgs) != 1:
        raise AssertionError(f"{path}: expected 1 FileIdMessage, got {len(fid_msgs)}")
    fid = fid_msgs[0]
    fid_vals = {fld.name: fld.get_value() for fld in fid.fields}
    if fid_vals.get("type") != FileType.WORKOUT.value:
        raise AssertionError(f"{path}: file type != WORKOUT")
    if fid_vals.get("manufacturer") != Manufacturer.GARMIN.value:
        raise AssertionError(f"{path}: manufacturer must be GARMIN (1)")

    wkt_msgs = [m for m in data_msgs if isinstance(m, WorkoutMessage)]
    if len(wkt_msgs) != 1:
        raise AssertionError(f"{path}: expected 1 WorkoutMessage")
    wkt_vals = {fld.name: fld.get_value() for fld in wkt_msgs[0].fields}
    if wkt_vals.get("num_valid_steps") != len(steps):
        raise AssertionError(
            f"{path}: num_valid_steps {wkt_vals.get('num_valid_steps')} != len(steps) {len(steps)}"
        )
    if wkt_vals.get("wkt_name") != name:
        raise AssertionError(f"{path}: wkt_name mismatch")

    step_msgs = [m for m in data_msgs if isinstance(m, WorkoutStepMessage)]
    if len(step_msgs) != len(steps):
        raise AssertionError(
            f"{path}: emitted {len(step_msgs)} step msgs, expected {len(steps)}"
        )
    for i, msg in enumerate(step_msgs):
        v = {fld.name: fld.get_value() for fld in msg.fields}
        if v.get("message_index") != i:
            raise AssertionError(f"{path} step {i}: message_index != {i}")
        # Verify custom power range is well-formed for regular steps
        if steps[i][0] == "step":
            lo = v.get("custom_target_value_low")
            hi = v.get("custom_target_value_high")
            if lo is None or hi is None or lo > hi:
                raise AssertionError(f"{path} step {i}: bad custom range ({lo}, {hi})")

    import os
    return {"bytes": os.path.getsize(path)}


# ============================ Workouts ============================

def workout_60km_sst_vo2():
    """60km mixed-intensity: 3x10 SST + 4x2 VO2 + endurance tail. ~2h10m."""
    s = []
    s.append(step("WU ramp",   5 * 60,  Intensity.WARMUP,   50, 65))
    s.append(step("WU spin",   10 * 60, Intensity.WARMUP,   65, 65))
    sst = len(s)
    s.append(step("SST 10'",   10 * 60, Intensity.ACTIVE,   88, 88))
    s.append(step("Easy 5'",   5 * 60,  Intensity.REST, 55, 55))
    s.append(repeat(sst, 3))
    s.append(step("Bridge",    5 * 60,  Intensity.ACTIVE,   60, 60))
    vo2 = len(s)
    s.append(step("VO2 2'",    2 * 60,  Intensity.ACTIVE,   108, 112))
    s.append(step("Recover",   3 * 60,  Intensity.REST, 60,  60))
    s.append(repeat(vo2, 4))
    s.append(step("Endurance", 35 * 60, Intensity.ACTIVE,   68, 72))
    s.append(step("Cooldown",  10 * 60, Intensity.COOLDOWN, 45, 60))
    return ("60km SST + VO2", s, "workouts/60km_sweetspot_vo2.fit")


def workout_sst_3x10():
    """Sweet-spot session — 3 x 10 min @ 88-90% FTP with 5' easy. ~75 min. Classic FTP lifter."""
    s = []
    s.append(step("WU ramp",   5 * 60,  Intensity.WARMUP,   50, 65))
    s.append(step("WU spin",   10 * 60, Intensity.WARMUP,   65, 70))
    sst = len(s)
    s.append(step("SST 10'",   10 * 60, Intensity.ACTIVE,   88, 90))
    s.append(step("Easy 5'",   5 * 60,  Intensity.REST, 55, 55))
    s.append(repeat(sst, 3))
    s.append(step("Z2 spin",   10 * 60, Intensity.ACTIVE,   65, 70))
    s.append(step("Cooldown",  10 * 60, Intensity.COOLDOWN, 45, 60))
    return ("SST 3x10", s, "workouts/sst_3x10.fit")


def workout_vo2_5x3():
    """VO2max session — 5 x 3 min @ 110% FTP with 3' easy. ~65 min. Raises aerobic ceiling."""
    s = []
    s.append(step("WU ramp",     5 * 60, Intensity.WARMUP,   50, 65))
    s.append(step("WU steady",   7 * 60, Intensity.WARMUP,   65, 70))
    op = len(s)
    s.append(step("Opener 30s",  30,     Intensity.ACTIVE,   100, 100))
    s.append(step("Easy 30s",    30,     Intensity.REST, 55,  55))
    s.append(repeat(op, 3))
    s.append(step("Pre-block",   3 * 60, Intensity.ACTIVE,   65, 70))
    vo2 = len(s)
    s.append(step("VO2 3'",      3 * 60, Intensity.ACTIVE,   108, 112))
    s.append(step("Recover 3'",  3 * 60, Intensity.REST, 55,  60))
    s.append(repeat(vo2, 5))
    s.append(step("Z2 spin",     10 * 60, Intensity.ACTIVE,  65, 70))
    s.append(step("Cooldown",    8 * 60,  Intensity.COOLDOWN, 45, 60))
    return ("VO2 5x3", s, "workouts/vo2_5x3.fit")


def workout_long_z2_tempo():
    """Long endurance ride — Z2 base with 3 x 8' tempo accents. ~2h41m. Weekend long ride."""
    s = []
    s.append(step("WU ramp",      5 * 60,  Intensity.WARMUP,   50, 65))
    s.append(step("Z2 endurance", 80 * 60, Intensity.ACTIVE,   68, 72))
    tempo = len(s)
    s.append(step("Tempo 8'",     8 * 60,  Intensity.ACTIVE,   80, 85))
    s.append(step("Z2 4'",        4 * 60,  Intensity.ACTIVE,   65, 70))
    s.append(repeat(tempo, 3))
    s.append(step("Z2 endurance", 30 * 60, Intensity.ACTIVE,   68, 72))
    s.append(step("Cooldown",     10 * 60, Intensity.COOLDOWN, 45, 60))
    return ("Long Z2 + Tempo", s, "workouts/long_z2_tempo.fit")


def workout_recovery_45():
    """45 min pure recovery spin — Z1/low-Z2, HR cap ~130. For re-entry after a layoff."""
    s = []
    s.append(step("WU ramp",   5 * 60,  Intensity.WARMUP,   40, 55))
    s.append(step("Easy spin", 35 * 60, Intensity.ACTIVE, 55, 65))
    s.append(step("Cooldown",  5 * 60,  Intensity.COOLDOWN, 40, 55))
    return ("Recovery 45 min", s, "workouts/recovery_45.fit")


def workout_z2_60():
    """60 min steady Z2 — re-engage the aerobic engine without adding fatigue."""
    s = []
    s.append(step("WU ramp",      5 * 60,  Intensity.WARMUP,   50, 65))
    s.append(step("Z2 endurance", 50 * 60, Intensity.ACTIVE,   65, 72))
    s.append(step("Cooldown",     5 * 60,  Intensity.COOLDOWN, 45, 55))
    return ("Z2 60 min", s, "workouts/z2_60.fit")


def workout_sst_40km_route():
    """SST 3x10 tuned to a ~40 km road route where the first 3-5 km can't be
    controlled (traffic lights, junctions, rough surface). Opens with a wide
    18-min low-power warmup band that any real-world start pace will satisfy,
    then hits three 10-min sweet-spot blocks. ~76 min moving = ~35-40 km at
    typical 27-29 km/h."""
    s = []
    # Wide "get out of town" opener — 10-min band lets you soft-pedal traffic
    # lights and hard-brake corners without ever missing the (broad) target.
    s.append(step("Roll-out",  10 * 60, Intensity.WARMUP,   40, 65))
    # Once free of the urban section, real warmup starts.
    s.append(step("WU Z2",     8 * 60,  Intensity.WARMUP,   65, 72))
    sst = len(s)
    s.append(step("SST 10'",   10 * 60, Intensity.ACTIVE,   88, 90))
    s.append(step("Easy 5'",   5 * 60,  Intensity.REST,     55, 55))
    s.append(repeat(sst, 3))
    s.append(step("Z2 spin",   8 * 60,  Intensity.ACTIVE,   60, 70))
    s.append(step("Cooldown",  5 * 60,  Intensity.COOLDOWN, 45, 55))
    return ("SST 3x10 · 40km route", s, "workouts/sst_40km_route.fit")


WORKOUTS = {
    "60km_sst_vo2":    workout_60km_sst_vo2,
    "sst_3x10":        workout_sst_3x10,
    "sst_40km_route":  workout_sst_40km_route,
    "vo2_5x3":         workout_vo2_5x3,
    "long_z2_tempo":   workout_long_z2_tempo,
    "recovery_45":     workout_recovery_45,
    "z2_60":           workout_z2_60,
}


if __name__ == "__main__":
    for key, w in WORKOUTS.items():
        build_workout(*w())
