"""Berlinger Fridge-tag 2 / 2E / 2L history reports (`<serial>_<yyyyMMddHHmm>.txt` + `.pdf`).

    logger-generator fridgetag --model 2E --days 60 --seed 7 --scenario heat-excursion --out DIR

Also importable: build a `Story` and call `write(story, folder)`; `describe(days)` summarizes.

The layout mirrors what the tags write on their USB drive: ASCII, CRLF lines, a key/value
outline indented with single spaces, `<serial>_<yyyyMMddHHmm>.txt` beside a PDF with the
same base name. Each day is summarized from a simulated one-minute temperature series, so
the minimum, maximum, their times, the mean and the minutes beyond each alarm limit always
agree with each other.

Alarm semantics:
- `t Acc` is the minutes that day beyond the limit (every excursion counted).
- `TS A` / `C A` appear only on a day the alarm triggered: when one continuous excursion
  reaches the limit's duration (above +8.0 C for 600 min, at or below -0.5 C for 60 min by
  default), even if it started the day before. A day that starts inside an
  already-triggered excursion shows `TS A: 00:00`. A shorter excursion gets `t Acc` but no
  `TS A`.

Model differences:
- 2: `Fw Vers: 3.2p0o`, no `User Clock Config`, short CID, `Key_` lot, Q-tag certificate.
- 2E: `Fw Vers: 3.4p0o`, `User Clock Config: 1`, 8-digit CID, Berlinger certificate.
- 2L: a 2E with an external probe in use (`Ext Sensor` header, `Ext Sensor:` config block,
  `Use ext devices: 1`, a daily `Ext Sensor timeout:` block). These fields follow a 2E
  running an external sensor.

Serials, PCB numbers, lots, CIDs and signatures are made up.
"""
import math
import os
import random
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from . import damage, pdf
from .util import clear, hhmm

MINUTES_PER_DAY = 1440
HIGH_LIMIT, HIGH_MINUTES = 8.0, 600
LOW_LIMIT, LOW_MINUTES = -0.5, 60


@dataclass
class Model:
    device: str
    firmware: str
    pcb_prefix: str
    cid: str
    lot: str
    user_clock_config: bool
    int_sensor_timeout: int
    det_report: int
    external_sensor: bool
    cert_issuer: str
    cert_valid_from: str


MODELS = {
    "2": Model("Q-tag Fridge-tag 2", "3.2p0o", "BG02", "1000", "Key_2018", False, 1, 3, False,
               "Qtag AG", "2017-03-14 09:12"),
    "2E": Model("Q-tag Fridge-tag 2 E", "3.4p0o", "BG01", "62200031", "1811_21_03", True, 1, 19, False,
                "Berlinger & Co. AG", "2021-03-02 08:15"),
    "2L": Model("Q-tag Fridge-tag 2 L", "3.4p0o", "BG01", "62200047", "1811_21_03", True, 1, 19, True,
                "Berlinger & Co. AG", "2021-03-02 08:15"),
}


@dataclass
class Excursion:
    """Overrides the temperature between two times on one day (days_ago 0 is the report day).

    The reading warms from normal over the first third, tops out at `peak` half-way and
    cools back over the last third, so the minutes beyond a limit depend on the window
    and on how far the peak overshoots it."""
    days_ago: int
    start: str  # "HH:MM"
    end: str  # "HH:MM"; past 24:00 (e.g. "34:00") runs into the next day
    peak: float


@dataclass
class Story:
    model: str
    serial: str
    created: datetime
    days: int = 60
    seed: int = 1
    base: float = 4.6  # typical daily mean, C
    swing: float = 0.8  # half the normal daily range, C
    peak_hour: float = 16.0
    excursions: list = field(default_factory=list)
    # Days before the report day whose baseline drifts warmer/colder (e.g. a cloudy spell
    # running down a solar fridge's ice): {days_ago: offset_C}.
    drift: dict = field(default_factory=dict)
    checks: int = 5  # days with a recorded check-button press
    activated: datetime = None
    errors: list = field(default_factory=list)  # [(code, count, "yyyy-mm-dd HH:MM")]
    # Alarm configuration (the 2-8 C vaccine default; a freezer tag uses e.g. -15 C high).
    low_limit: float = LOW_LIMIT
    low_minutes: int = LOW_MINUTES
    high_limit: float = HIGH_LIMIT
    high_minutes: int = HIGH_MINUTES
    unit: str = "C"  # "F" writes every temperature and limit in Fahrenheit
    # The tag's clock was never set: it started at 2000-01-01 00:00 on activation, so every
    # printed date and time (and the file name) is that far behind the real ones.
    unset_clock: bool = False


def _minutes(value):
    h, m = map(int, value.split(":"))
    return h * 60 + m


def simulate(story):
    """One reading per minute from the first history day's 00:00 to report creation."""
    rnd = random.Random(story.seed)
    first_day = story.created.date() - timedelta(days=story.days - 1)
    total = (story.days - 1) * MINUTES_PER_DAY + story.created.hour * 60 + story.created.minute + 1
    day_offsets = {}
    level = 0.0
    for n in range(story.days):
        level = 0.75 * level + rnd.gauss(0, 0.18)  # slow day-to-day wander
        days_ago = story.days - 1 - n
        day_offsets[n] = level + story.drift.get(days_ago, 0.0)

    # Short warm bumps when the lid/door is opened during clinic hours.
    openings = []
    for n in range(story.days):
        for _ in range(rnd.randint(1, 4)):
            start = n * MINUTES_PER_DAY + rnd.randint(8 * 60 + 30, 15 * 60)
            openings.append((start, rnd.randint(2, 6), rnd.uniform(0.4, 1.4)))

    excursions = []
    for e in story.excursions:
        n = story.days - 1 - e.days_ago
        excursions.append((n * MINUTES_PER_DAY + _minutes(e.start), n * MINUTES_PER_DAY + _minutes(e.end), e.peak))

    readings = []
    wobble = 0.0
    for i in range(total):
        n, minute = divmod(i, MINUTES_PER_DAY)
        hour = minute / 60
        temp = story.base + day_offsets[n] + story.swing * math.cos(2 * math.pi * (hour - story.peak_hour) / 24)
        wobble = 0.97 * wobble + rnd.gauss(0, 0.03)
        temp += wobble
        for start, length, bump in openings:
            if start <= i < start + length + 25:
                k = i - start
                temp += bump * (k / length if k < length else math.exp(-(k - length) / 7))
        for start, end, peak in excursions:
            if start <= i <= end:
                x = (i - start) / (end - start)
                # Slow warm-up, a broad top that peaks mid-way, slow pull-down.
                ramp = min(1.0, x / 0.35, (1 - x) / 0.3)
                weight = ramp * ramp * (3 - 2 * ramp)
                top = peak - 0.6 * (1 - math.sin(math.pi * x))
                temp = temp + (top - temp) * weight
        readings.append(round(temp, 1))
    return first_day, readings


def summarize(story, first_day, readings):
    """Per-day min/max (and their minute), mean and (minutes, alarm time) for low and high."""
    days = []
    high_run = low_run = 0
    high_latched = low_latched = False
    for n in range(story.days):
        chunk = readings[n * MINUTES_PER_DAY:(n + 1) * MINUTES_PER_DAY]
        lo, hi = min(chunk), max(chunk)
        high_acc = low_acc = 0
        high_ts = low_ts = None
        if high_latched and chunk[0] > story.high_limit:
            high_ts = "00:00"
        if low_latched and chunk[0] <= story.low_limit:
            low_ts = "00:00"
        for minute, t in enumerate(chunk):
            if t > story.high_limit:
                high_acc += 1
                high_run += 1
                if high_run == story.high_minutes and high_ts is None:
                    high_ts = hhmm(minute)
                    high_latched = True
            else:
                high_run, high_latched = 0, False
            if t <= story.low_limit:
                low_acc += 1
                low_run += 1
                if low_run == story.low_minutes and low_ts is None:
                    low_ts = hhmm(minute)
                    low_latched = True
            else:
                low_run, low_latched = 0, False
        days.append({
            "date": first_day + timedelta(days=n),
            "min": lo, "min_at": chunk.index(lo),
            "max": hi, "max_at": chunk.index(hi),
            # fsum: plain sum() changed its rounding in Python 3.12; fsum is the same everywhere.
            "mean": round(math.fsum(chunk) / len(chunk), 1),
            "low": (low_acc, low_ts), "high": (high_acc, high_ts),
        })
    return days


def temperature_formatter(story):
    """`+4.6` style, converted to Fahrenheit when the tag is configured for it."""
    if story.unit == "F":
        return lambda value: f"{value * 9 / 5 + 32:+.1f}"
    return lambda value: f"{value:+.1f}"


def clock_lag(story, activated):
    """How far the tag's clock is behind real time (zero unless the clock was never set)."""
    if not story.unset_clock:
        return timedelta(0)
    lag = activated - datetime(2000, 1, 1)
    return timedelta(days=lag.days)  # keep wall-clock times; only the dates move


def render(story):
    """The report text (CRLF), the day summaries and the activation time."""
    model = MODELS[story.model]
    rnd = random.Random(story.seed * 7919)
    first_day, readings = simulate(story)
    days = summarize(story, first_day, readings)
    activated = story.activated or (story.created - timedelta(days=story.days + rnd.randint(40, 200),
                                                              minutes=rnd.randint(0, 1439)))
    tested = activated - timedelta(days=rnd.randint(60, 400), minutes=rnd.randint(0, 1439))
    fmt = "%Y-%m-%d %H:%M"
    lag = clock_lag(story, activated)
    _t = temperature_formatter(story)

    lines = [f"Device: {model.device}", "Vers: 0.5", f"Fw Vers: {model.firmware}", "Sensor: 1"]
    if model.external_sensor:
        lines.append("Ext Sensor: 1")
    lines += [
        "Conf:",
        f" Serial: {story.serial}",
        f" PCB: {model.pcb_prefix}{rnd.randint(0, 99999999):08d}",
        f" CID: {model.cid}",
        f" Lot: {model.lot}",
        " Zone: 0.00",
        " Measurement delay: 10",
        " Moving Avrg: 1",
        " User Alarm Config: 0",
    ]
    if model.user_clock_config:
        lines.append(" User Clock Config: 1")
    lines += [
        " Alarm Indication: 0",
        f" Temp unit: {story.unit}",
        " Alarm:",
        "  0:",
        f"   T AL: {_t(story.low_limit)}, t AL: {story.low_minutes}",
        "  1:",
        f"   T AL: {_t(story.high_limit)}, t AL: {story.high_minutes}",
    ]
    if model.external_sensor:
        lines += [" Ext Sensor:", "  Timeout: 10, Offset: +0.0"]
    lines += [
        " Int Sensor:",
        f"  Timeout: {model.int_sensor_timeout}, Offset: +0.0",
        " Report history length: 60",
        f" Det Report: {model.det_report}",
        f" Use ext devices: {1 if model.external_sensor else 0}",
        f" Test Res: 1, Test TS: {(tested - lag).strftime(fmt) if lag else tested.strftime(fmt)}",
    ]
    if story.errors:
        lines.append("Errors:")
        for code, count, when in story.errors:
            lines += [f" {code}:", f"  Err Count: {count}, Err TS: {when}"]
    lines += ["Hist:", f" TS Actv: {(activated - lag).strftime(fmt)}",
              f" TS Report Creation: {(story.created - lag).strftime(fmt)}"]

    # Never on the report day: a press after the report was written can't be in it.
    check_days = set(rnd.sample(range(2, story.days + 1), min(story.checks, story.days - 1)))
    for index, day in enumerate(reversed(days), start=1):
        lines += [
            f" {index}:",
            f"  Date: {(day['date'] - timedelta(days=lag.days)).isoformat()}",
            f"  Min T: {_t(day['min'])}, TS Min T: {hhmm(day['min_at'])}",
            f"  Max T: {_t(day['max'])}, TS Max T: {hhmm(day['max_at'])}",
            f"  Avrg T: {_t(day['mean'])}",
            "  Alarm:",
        ]
        for key, (acc, ts) in (("0", day["low"]), ("1", day["high"])):
            lines.append(f"   {key}:")
            lines.append(f"    t Acc: {acc}" + (f", TS A: {ts}, C A: 0" if ts else ""))
        if model.external_sensor:
            lines += ["  Ext Sensor timeout:", "   t AccST: 0"]
        lines += ["  Int Sensor timeout:", "   t AccST: 0"]
        if index in check_days:
            morning = rnd.random() < 0.5
            when = rnd.randint(7 * 60 + 30, 10 * 60) if morning else rnd.randint(13 * 60, 16 * 60 + 30)
            lines += [f"  Events: {8 if morning else 16}", "  Checked:", f"   TS {'AM' if morning else 'PM'}: {hhmm(when)}"]
        else:
            lines.append("  Events: 0")

    def hex_bytes(n):
        return "".join(f"{rnd.randrange(256):02x}" for _ in range(n))

    lines += [
        "Cert:",
        " Vers: 1.0",
        f" Lot: {model.lot}",
        f" Issuer: {model.cert_issuer}",
        f" Valid from: {model.cert_valid_from}",
        f" Owner: {model.cert_issuer}",
        f" Public Key: {hex_bytes(64)}",
        f"Sig Cert: {hex_bytes(64)}",
        f"Sig: {hex_bytes(64)}",
    ]
    return "\r\n".join(lines) + "\r\n", days, activated


def report_pdf(path, story, days, activated):
    """A one-page history report in the spirit of the tag's own PDF: header, alarm settings,
    a chart of daily minimum/mean/maximum against the 2-8 C band and a table of every day."""
    model = MODELS[story.model]
    fmt = "%Y-%m-%d %H:%M"
    info = [
        ("Serial number", story.serial), ("Firmware", model.firmware),
        ("Activated", activated.strftime(fmt)), ("Report created", story.created.strftime(fmt)),
        ("Low alarm", f"{story.low_limit:+.1f} °C for {story.low_minutes} min"),
        ("High alarm", f"{story.high_limit:+.1f} °C for {story.high_minutes} min"),
    ]
    pdf.summary_report_pdf(path, f"Fridge-tag {story.model} report", "Temperature history, last 60 days", info, days,
                           story.serial,
                           "Low/High: minutes beyond the alarm limit that day. Shaded rows: the alarm triggered.")


def write(story, folder):
    """Replaces the folder's Fridge-tag files with this story's report; returns the day summaries."""
    clear(folder, (".txt", ".pdf"))
    text, days, activated = render(story)
    stamp = story.created - clock_lag(story, activated)
    base = f"{story.serial}_{stamp.strftime('%Y%m%d%H%M')}"
    with open(os.path.join(folder, base + ".txt"), "w", newline="") as f:
        f.write(text)
    report_pdf(os.path.join(folder, base + ".pdf"), story, days, activated)
    return days


def describe(days):
    """Day count, alarm days and every day with minutes beyond a limit."""
    alarms = [d for d in days if d["low"][1] or d["high"][1]]
    lines = [f"{len(days)} days, {len(alarms)} alarm day(s)"]
    for d in days:
        if d["low"][0] or d["high"][0]:
            lines.append(f"  {d['date']}: low {d['low']}, high {d['high']}, min {d['min']}, max {d['max']}, mean {d['mean']}")
    return "\n".join(lines)


# --- Scenarios ---------------------------------------------------------------------------
# Each preset is a dict of Story fields (applied before the command-line options) and an
# optional `damage` step applied to the written files.

SCENARIOS = {
    "normal": ("A 2-8 C vaccine fridge with no excursions", {}),
    "heat-excursion": ("A 17 h warm spell 5 days back peaking at +12 C: high alarm (TS A) that day",
                       {"excursions": [Excursion(5, "06:00", "23:00", 12.0)]}),
    "heat-no-alarm": ("A 6 h warm spell 5 days back: t Acc minutes but shorter than the alarm delay, so no TS A",
                      {"excursions": [Excursion(5, "12:00", "18:00", 9.5)]}),
    "heat-across-midnight": ("One 19 h excursion from 15:00 six days back to 10:00 the next day: the first day gets "
                             "t Acc only, the alarm triggers early on the second day (TS A) from the run that "
                             "began the day before",
                             {"excursions": [Excursion(6, "15:00", "34:00", 11.5)]}),
    "freeze-event": ("A cold dawn 12 days back down to -1.6 C: low alarm after 60 min at or below -0.5 C",
                     {"excursions": [Excursion(12, "03:30", "06:00", -1.6)]}),
    "cloudy-week": ("A solar fridge's cloudy spell: baselines drift up to +1.5 C for three days, no alarm",
                    {"drift": {9: 0.8, 8: 1.5, 7: 1.1}}),
    "unset-clock": ("The tag's clock was never set: every date counts from 2000-01-01 at activation, "
                    "including the file name", {"unset_clock": True}),
    "freezer": ("A freezer tag around -20 C with limits -40 C (60 min) and -15 C (600 min)",
                {"base": -20.0, "swing": 1.5, "low_limit": -40.0, "high_limit": -15.0}),
    "fahrenheit": ("A tag configured for Fahrenheit (Temp unit: F): every temperature and limit in F",
                   {"unit": "F"}),
    "damaged-truncated": ("The report cut off part-way through the history (USB pulled while copying); "
                          "the PDF is intact", {"damage": damage.truncate_fridgetag}),
}


def build_story(args):
    """A Story from parsed command-line arguments on top of the chosen scenario."""
    preset = dict(SCENARIOS[args.scenario][1])
    damage_step = preset.pop("damage", None)
    parse = lambda value: datetime.strptime(value, "%Y-%m-%dT%H:%M")  # noqa: E731
    story = Story(args.model, args.serial or "160600000002", parse(args.created), args.days, args.seed)
    story = replace(story, **preset)
    overrides = {k: v for k, v in {
        "base": args.base, "swing": args.swing, "low_limit": args.low_limit, "low_minutes": args.low_minutes,
        "high_limit": args.high_limit, "high_minutes": args.high_minutes, "unit": args.unit,
        "activated": parse(args.activated) if args.activated else None,
    }.items() if v is not None}
    if args.unset_clock:
        overrides["unset_clock"] = True
    story = replace(story, **overrides)
    for spec in args.excursion:
        days_ago, start, end, peak = spec.split(",")
        story.excursions = story.excursions + [Excursion(int(days_ago), start, end, float(peak))]
    for spec in args.drift:
        k, v = spec.split(":")
        story.drift = {**story.drift, int(k): float(v)}
    for spec in args.error:
        c, n, when = spec.split(",", 2)
        story.errors = story.errors + [(int(c), int(n), when)]
    return story, damage_step


def add_arguments(parser):
    parser.add_argument("--scenario", choices=list(SCENARIOS), default="normal", metavar="NAME",
                        help="preset story: " + ", ".join(SCENARIOS) + " (default: normal; descriptions: logger-generator --list-scenarios). The options below adjust it")
    parser.add_argument("--model", choices=sorted(MODELS), default="2E", help="tag model (default: 2E)")
    parser.add_argument("--serial", help="12-digit tag serial, also the file name prefix (default: 160600000002)")
    parser.add_argument("--created", default="2026-10-15T09:20",
                        help="report creation, yyyy-mm-ddTHH:MM; the newest history day (default: 2026-10-15T09:20)")
    parser.add_argument("--activated", help="activation, yyyy-mm-ddTHH:MM (default: 40-200 days before the history, from the seed)")
    parser.add_argument("--days", type=int, default=60, help="history days, newest = the report day (default: 60, the tags' maximum)")
    parser.add_argument("--seed", type=int, default=1, help="random seed; same arguments + seed = identical files (default: 1)")
    parser.add_argument("--base", type=float, help="typical daily mean in C (default: 4.6)")
    parser.add_argument("--swing", type=float, help="half the normal daily range in C (default: 0.8)")
    parser.add_argument("--excursion", action="append", default=[], metavar="DAYS_AGO,HH:MM,HH:MM,PEAK",
                        help="push the temperature towards PEAK (C) between two times on one day, e.g. 21,10:00,22:40,10.8 "
                             "(repeatable, added to the scenario's; DAYS_AGO 0 is the report day)")
    parser.add_argument("--drift", action="append", default=[], metavar="DAYS_AGO:OFFSET",
                        help="shift a whole day's baseline by OFFSET C, e.g. 22:1.3 (repeatable)")
    parser.add_argument("--low-limit", type=float, help=f"low alarm threshold in C (default: {LOW_LIMIT})")
    parser.add_argument("--low-minutes", type=int, help=f"minutes at or below it before alarming (default: {LOW_MINUTES})")
    parser.add_argument("--high-limit", type=float, help=f"high alarm threshold in C (default: {HIGH_LIMIT})")
    parser.add_argument("--high-minutes", type=int, help=f"minutes above it before alarming (default: {HIGH_MINUTES})")
    parser.add_argument("--unit", choices=["C", "F"], help="unit the tag is configured for (default: C)")
    parser.add_argument("--unset-clock", action="store_true", help="the tag's clock was never set (dates count from 2000-01-01)")
    parser.add_argument("--error", action="append", default=[], metavar="CODE,COUNT,YYYY-MM-DD HH:MM",
                        help="an entry for the Errors block (repeatable)")
    parser.add_argument("--out", required=True,
                        help="folder for <serial>_<yyyyMMddHHmm>.txt and .pdf (existing .txt/.pdf there are replaced)")


def run(args):
    story, damage_step = build_story(args)
    days = write(story, args.out)
    if damage_step:
        damage_step(args.out)
    print(describe(days))
