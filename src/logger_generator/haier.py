"""Haier HETL-01 30-day temperature recorder exports (`HE<serial>.CSV`).

    logger-generator haier --scenario heat-excursion --seed 4 --out DIR

The HETL-01 is the 30-day temperature recorder (PQS E006) sold with Haier Biomedical
vaccine refrigerators. Plugged into a computer it shows a USB drive with one CSV:

    Note: All temperature are in degree ceslsius        <- sic, as the device writes it
    (blank)
    Device Information
    ****************************************
    Device:HETL-01
    Version: V1.0
    Serial Number:HE01234567890
    Record Interval:  6 min
    Start Delay: 30 min
    Alarm Temperature High: +8  Delay 10 h
    Alarm Temperature Low: -0.5 Delay 1 h
    Alarm State: High Alarm
    (blank)
    Recorded Temperature
    ****************************************
    MM.DD.YYYY  HH:MM:SS   T
    10.15.2026  08:44:39  4.6
    ...

CRLF line endings, oldest reading first, one reading per record interval from the start
(after the start delay) to the read, in C with one decimal. The logger holds 8192 readings
(about 34 days at 6 minutes). `Alarm State` is `High Alarm` or `Low Alarm` once a run beyond
a limit lasted its delay (high: above, low: at or below), otherwise `Normal`.

The temperature series comes from the same one-minute simulation as the Fridge-tag
generator (daily cycle, day-to-day wander, door-opening bumps, shaped excursions), sampled
every record interval. Serial numbers are made up.
"""
import os
import random
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from . import damage, fridgetag
from .util import clear

CAPACITY = 8192
SERIAL = re.compile(r"^HE[0-9]+$")
STARS = "*" * 40


@dataclass
class HaierStory:
    serial: str = "HE09900000001"
    read_at: datetime = datetime(2026, 10, 15, 9, 20, 0)
    days: int = 30
    seed: int = 1
    base: float = 4.6
    swing: float = 0.8
    excursions: list = field(default_factory=list)  # fridgetag.Excursion, days_ago from the read
    interval: int = 6  # minutes
    start_delay: int = 30  # minutes
    high_limit: float = 8.0
    high_delay_hours: float = 10
    low_limit: float = -0.5
    low_delay_hours: float = 1


def _number(value):
    text = f"{value:+g}"
    return text


def _hours(value):
    return f"{value:g}"


def readings(story):
    """[(datetime, temperature)] oldest first."""
    rnd = random.Random(story.seed * 104729)
    started = (story.read_at - timedelta(days=story.days)).replace(second=rnd.randint(0, 59))
    first = started + timedelta(minutes=story.start_delay)
    series_story = fridgetag.Story("2E", "", story.read_at, days=story.days + 1, seed=story.seed,
                                   base=story.base, swing=story.swing, excursions=story.excursions)
    first_day, series = fridgetag.simulate(series_story)
    origin = datetime.combine(first_day, datetime.min.time())
    out = []
    when = first
    while when <= story.read_at:
        minute = int((when - origin).total_seconds() // 60)
        out.append((when, series[minute]))
        when += timedelta(minutes=story.interval)
    if len(out) > CAPACITY:
        raise SystemExit(f"{len(out)} readings exceed the logger's {CAPACITY}; use fewer --days or a longer --interval")
    return out


def alarm_state(story, values):
    high_need = story.high_delay_hours * 60 / story.interval
    low_need = story.low_delay_hours * 60 / story.interval
    high = low = False
    high_run = low_run = 0
    for _, t in values:
        high_run = high_run + 1 if t > story.high_limit else 0
        low_run = low_run + 1 if t <= story.low_limit else 0
        high = high or high_run >= high_need
        low = low or low_run >= low_need
    return "High Alarm" if high else "Low Alarm" if low else "Normal"


def render(story):
    if not SERIAL.match(story.serial):
        raise SystemExit(f"Haier serials look like HE01234567890, got {story.serial!r}")
    values = readings(story)
    lines = [
        "Note: All temperature are in degree ceslsius",
        "",
        "Device Information",
        STARS,
        "Device:HETL-01",
        "Version: V1.0",
        f"Serial Number:{story.serial}",
        f"Record Interval: {story.interval:>2} min",
        f"Start Delay: {story.start_delay} min",
        f"Alarm Temperature High: {_number(story.high_limit):<3} Delay {_hours(story.high_delay_hours)} h",
        f"Alarm Temperature Low: {_number(story.low_limit):<3} Delay {_hours(story.low_delay_hours)} h",
        f"Alarm State: {alarm_state(story, values)}",
        "",
        "Recorded Temperature",
        STARS,
        "MM.DD.YYYY  HH:MM:SS   T",
    ]
    lines += [f"{when.strftime('%m.%d.%Y  %H:%M:%S')}  {t:.1f}" for when, t in values]
    return "\r\n".join(lines) + "\r\n", values


def write(story, folder):
    """Replaces the folder's Haier CSV with this story's; returns the readings."""
    clear(folder, (".csv",))
    text, values = render(story)
    with open(os.path.join(folder, f"{story.serial}.CSV"), "w", newline="") as f:
        f.write(text)
    return values


def describe(story, values):
    temps = [t for _, t in values]
    return (f"{len(values)} readings from {values[0][0]} to {values[-1][0]}, {min(temps)}..{max(temps)} C, "
            f"alarm state: {alarm_state(story, values)}")


SCENARIOS = {
    "normal": ("In a 2-8 C fridge, no excursions: Alarm State Normal", {}),
    "heat-excursion": ("A 17 h warm spell 5 days back peaking at +12 C: High Alarm",
                       {"excursions": [fridgetag.Excursion(5, "06:00", "23:00", 12.0)]}),
    "freeze-event": ("A cold dawn 12 days back down to -1.6 C: Low Alarm",
                     {"excursions": [fridgetag.Excursion(12, "03:30", "06:00", -1.6)]}),
    "room-temperature": ("A logger left out of the fridge at room temperature (about 22 C): High Alarm",
                         {"base": 22.0, "swing": 1.5}),
    "damaged-lines": ("A few corrupted reading lines (a wrong year, garbled digits, a cut-off line) among good ones",
                      {"damage": damage.haier_lines}),
}


def add_arguments(parser):
    parser.add_argument("--scenario", choices=list(SCENARIOS), default="normal", metavar="NAME",
                        help="preset story: " + ", ".join(SCENARIOS) + " (default: normal; descriptions: logger-generator --list-scenarios). The options below adjust it")
    parser.add_argument("--serial", default="HE09900000001", help="HE + digits, also the file name (default: HE09900000001)")
    parser.add_argument("--read-at", default="2026-10-15T09:20:00", help="time of the read, yyyy-mm-ddTHH:MM:SS (default: 2026-10-15T09:20:00)")
    parser.add_argument("--days", type=int, default=30, help="days of readings before the read (default: 30; at most about 34)")
    parser.add_argument("--seed", type=int, default=1, help="random seed; same arguments + seed = identical files (default: 1)")
    parser.add_argument("--base", type=float, help="typical daily mean in C (default: 4.6)")
    parser.add_argument("--swing", type=float, help="half the normal daily range in C (default: 0.8)")
    parser.add_argument("--excursion", action="append", default=[], metavar="DAYS_AGO,HH:MM,HH:MM,PEAK",
                        help="push the temperature towards PEAK (C) between two times on one day (repeatable)")
    parser.add_argument("--interval", type=int, default=6, help="record interval in minutes (default: 6)")
    parser.add_argument("--out", required=True, help="folder for HE<serial>.CSV (an existing .csv there is replaced)")


def run(args):
    preset = dict(SCENARIOS[args.scenario][1])
    damage_step = preset.pop("damage", None)
    story = replace(HaierStory(serial=args.serial, read_at=datetime.strptime(args.read_at, "%Y-%m-%dT%H:%M:%S"),
                               days=args.days, seed=args.seed, interval=args.interval), **preset)
    if args.base is not None:
        story.base = args.base
    if args.swing is not None:
        story.swing = args.swing
    for spec in args.excursion:
        days_ago, start, end, peak = spec.split(",")
        story.excursions = story.excursions + [fridgetag.Excursion(int(days_ago), start, end, float(peak))]
    values = write(story, args.out)
    if damage_step:
        damage_step(args.out)
    print(describe(story, values))
