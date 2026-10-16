"""Aucma MetaFridge CFD-50 SDD 30 DTR reports (`<serial>_<yyyyMMdd>_<yyyyMMdd>.csv` + `.pdf`).

    logger-generator metafridge --scenario heat-excursion --seed 4 --out DIR

The MetaFridge CFD-50 SDD is a solar direct-drive vaccine refrigerator with a built-in
30-day temperature recorder (30 DTR). Its user manual (section 5.5) describes the download:
connected to a computer with a micro USB cable the fridge shows a USB drive whose top level
holds the newest 30 DTR report as CSV and PDF, named with the last 7 characters of the fridge
serial and the date range the report covers. Older reports sit in subfolders (not modelled).

Current layout (UTF-8 with a byte order mark, CRLF line endings):

    CFD50 30 DTR REPORT
    Fridge Serial Number:, ,99S-0001
    Report Creation Date:, ,2026-10-15
    Report Creation Time:, ,09:20:00
    DayNum,Date,Average Temperature (°C),Status,Minimum Temperature (°C),Total Time Below Limit (hh:mm),
      Total Low Alarm Time (hh:mm),Maximum Temperature (°C),Total Time Above Limit (hh:mm),
      Total High Alarm Time (hh:mm),Door Open Time (seconds),Min Holdover (days),Power Good (%),Faults
    01,2026-10-15,4.8,OK,4.1,00:00,00:00,5.6,00:00,00:00,74,4.4,46.5,0
    ...
    60,2026-08-17, , , , , , , , , , , ,

(the header is one line). One row per day for the report window, newest first; row 01 is the
report day up to the creation time. Days before the fridge was installed keep their number
and date with every other cell blank. Durations are `hh:mm`, a whole day `24:00`.

Older firmware writes a narrower layout: no byte order mark, LF line endings, every line
padded with commas to 10 columns, the serial line blank, day numbers unpadded, `M/d/yyyy`
dates, `h:mm` durations and `24:00:00` for a whole day, and only the first ten columns.

Time below/above limit counts minutes below +2 °C and above +8 °C. The alarm time equals it,
as in every download the formats were checked against; `Status` is `ALARM` on a day with any
alarm time. Door, holdover and power figures are illustrative; fault codes are always 0.

The temperature series comes from the same one-minute simulation as the Fridge-tag generator
(daily cycle, day-to-day wander, door-opening bumps, shaped excursions, baseline drifts).
Serial numbers are made up.
"""
import math
import os
import random
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from . import damage, fridgetag, pdf
from .util import clear

SERIAL = re.compile(r"^[A-Z0-9-]+$")
TITLE = "CFD50 30 DTR REPORT"
HEADER = ["DayNum", "Date", "Average Temperature (°C)", "Status", "Minimum Temperature (°C)",
          "Total Time Below Limit (hh:mm)", "Total Low Alarm Time (hh:mm)", "Maximum Temperature (°C)",
          "Total Time Above Limit (hh:mm)", "Total High Alarm Time (hh:mm)", "Door Open Time (seconds)",
          "Min Holdover (days)", "Power Good (%)", "Faults"]
LEGACY_COLUMNS = 10
LOW_LIMIT, HIGH_LIMIT = 2.0, 8.0


@dataclass
class MetaFridgeStory:
    serial: str = "99S-0001"
    created: datetime = datetime(2026, 10, 15, 9, 20, 0)
    days: int = 60  # rows in the report window
    active_days: int = None  # days with readings (default: all); earlier rows are blank
    seed: int = 1
    base: float = 4.6
    swing: float = 0.8
    excursions: list = field(default_factory=list)  # fridgetag.Excursion, days_ago from the report day
    drift: dict = field(default_factory=dict)  # {days_ago: offset_C}, e.g. a cloudy spell
    running: bool = True  # False: switched off, no solar power, no holdover
    legacy: bool = False  # the older firmware's 10-column layout


def simulate(story):
    """Day dicts, newest first: number, date and (for days with readings) the summary values."""
    active = story.days if story.active_days is None else story.active_days
    if not 1 <= active <= story.days:
        raise SystemExit(f"--active-days must be between 1 and --days ({story.days}), got {active}")
    series_story = fridgetag.Story("2E", "", story.created, days=active, seed=story.seed, base=story.base,
                                   swing=story.swing, excursions=story.excursions, drift=story.drift)
    first_day, readings = fridgetag.simulate(series_story)
    rnd = random.Random(story.seed * 7919)
    days = []
    for n in range(1, story.days + 1):
        day = {"number": n, "date": story.created.date() - timedelta(days=n - 1)}
        if n <= active:
            start = (active - n) * fridgetag.MINUTES_PER_DAY
            chunk = readings[start:start + fridgetag.MINUTES_PER_DAY]
            if n == 1:  # the report day counts only the minutes completed before creation
                chunk = chunk[:max(1, story.created.hour * 60 + story.created.minute)]
            below = sum(1 for t in chunk if t < LOW_LIMIT)
            above = sum(1 for t in chunk if t > HIGH_LIMIT)
            drift = max(0.0, story.drift.get(n - 1, 0.0))
            day.update({
                "min": min(chunk), "max": max(chunk),
                # fsum: plain sum() changed its rounding in Python 3.12; fsum is the same everywhere.
                "mean": round(math.fsum(chunk) / len(chunk), 1),
                "low": (below, below > 0), "high": (above, above > 0),
                "door": sum(rnd.randint(10, 90) for _ in range(rnd.randint(1, 5))) if story.running else 0,
                "holdover": round(max(0.5, 4.6 - 1.2 * drift + rnd.gauss(0, 0.15)), 1) if story.running else None,
                "power": round(min(100.0, max(0.0, 46.0 - 14.0 * drift + rnd.gauss(0, 3.0))), 1) if story.running else 0.0,
            })
        days.append(day)
    return days


def _duration(minutes, legacy):
    if minutes == fridgetag.MINUTES_PER_DAY:
        return "24:00:00" if legacy else "24:00"
    hours, rest = divmod(minutes, 60)
    return f"{hours}:{rest:02d}" if legacy else f"{hours:02d}:{rest:02d}"


def _row(day, legacy):
    number = str(day["number"]) if legacy else f"{day['number']:02d}"
    date = f"{day['date'].month}/{day['date'].day}/{day['date'].year}" if legacy else day["date"].isoformat()
    if "mean" not in day:
        return [number, date] + [" "] * (LEGACY_COLUMNS - 2 if legacy else len(HEADER) - 3) + ([] if legacy else [""])
    (below, _), (above, _) = day["low"], day["high"]
    cells = [number, date, f"{day['mean']:.1f}", "ALARM" if below or above else "OK", f"{day['min']:.1f}",
             _duration(below, legacy), _duration(below, legacy), f"{day['max']:.1f}",
             _duration(above, legacy), _duration(above, legacy)]
    if legacy:
        return cells
    holdover = "" if day["holdover"] is None else f"{day['holdover']:.1f}"
    return cells + [str(day["door"]), holdover, f"{day['power']:.1f}", "0"]


def render(story):
    if not SERIAL.match(story.serial):
        raise SystemExit(f"MetaFridge serials are letters, digits and dashes (e.g. 99S-0001), got {story.serial!r}")
    days = simulate(story)
    if story.legacy:
        def pad(cells):
            return ",".join(cells + [""] * (LEGACY_COLUMNS - len(cells)))
        lines = [pad([TITLE]), pad(["Fridge Serial Number:", " "]),
                 pad(["Report Creation Date:", " ", f"{story.created.month}/{story.created.day}/{story.created.year}"]),
                 pad(["Report Creation Time:", " ", story.created.strftime("%H:%M:%S")]),
                 ",".join(HEADER[:LEGACY_COLUMNS])]
        lines += [pad(_row(day, True)) for day in days]
        return "\n".join(lines) + "\n", days
    lines = ["﻿" + TITLE, f"Fridge Serial Number:, ,{story.serial}",
             f"Report Creation Date:, ,{story.created.date().isoformat()}",
             f"Report Creation Time:, ,{story.created.strftime('%H:%M:%S')}", ",".join(HEADER)]
    lines += [",".join(_row(day, False)) for day in days]
    return "\r\n".join(lines) + "\r\n", days


def file_base(story):
    oldest = story.created.date() - timedelta(days=story.days - 1)
    return f"{story.serial}_{oldest.strftime('%Y%m%d')}_{story.created.strftime('%Y%m%d')}"


def report_pdf(path, story, days):
    """A one-page summary in the spirit of the fridge's own PDF: chart and table of every day with readings."""
    recorded = [d for d in reversed(days) if "mean" in d]
    fmt = "%Y-%m-%d %H:%M"
    info = [("Serial number", story.serial), ("Report created", story.created.strftime(fmt)),
            ("Report window", f"{days[-1]['date']} to {days[0]['date']}"),
            ("Days with readings", str(len(recorded)))]
    pdf.summary_report_pdf(path, "MetaFridge CFD-50 30 DTR report", "Daily temperature record", info, recorded,
                           story.serial, "Low/High: minutes below +2 °C / above +8 °C that day. Shaded rows: alarm.")


def write(story, folder):
    """Replaces the folder's MetaFridge CSV and PDF with this story's report; returns the day rows."""
    clear(folder, (".csv", ".pdf"))
    text, days = render(story)
    base = os.path.join(folder, file_base(story))
    with open(base + ".csv", "w", newline="", encoding="utf-8") as f:
        f.write(text)
    report_pdf(base + ".pdf", story, days)
    return days


def describe(story, days):
    recorded = [d for d in days if "mean" in d]
    alarms = [d for d in recorded if d["low"][1] or d["high"][1]]
    return (f"{len(days)} day rows ({len(recorded)} with readings), {len(alarms)} alarm day(s), "
            f"{min(d['min'] for d in recorded)}..{max(d['max'] for d in recorded)} C"
            + (", older 10-column layout" if story.legacy else ""))


SCENARIOS = {
    "normal": ("A 2-8 C solar fridge, no excursions", {}),
    "heat-excursion": ("A 17 h warm spell 5 days back peaking at +12 C: ALARM with time above limit that day",
                       {"excursions": [fridgetag.Excursion(5, "06:00", "23:00", 12.0)]}),
    "freeze-event": ("A cold dawn 12 days back down to -1.6 C: ALARM with time below limit that day",
                     {"excursions": [fridgetag.Excursion(12, "03:30", "06:00", -1.6)]}),
    "cloudy-week": ("A cloudy spell: baselines drift up to +1.5 C for three days, lower Power Good and holdover, no alarm",
                    {"drift": {9: 0.8, 8: 1.5, 7: 1.1}}),
    "recently-installed": ("Installed 28 days before the report: rows 29-60 have a date and blank cells",
                           {"active_days": 28}),
    "not-cooling": ("Switched off at room temperature (about 22 C): ALARM all day every day, Power Good 0.0, "
                    "no holdover", {"base": 22.0, "swing": 1.5, "running": False}),
    "legacy-layout": ("The older firmware layout: no BOM, LF, 10 comma-padded columns, blank serial, "
                      "M/d/yyyy dates, h:mm and 24:00:00 durations", {"legacy": True}),
    "damaged-truncated": ("The CSV cut off part-way through the rows (USB pulled while copying); the PDF is intact",
                          {"damage": damage.truncate_metafridge}),
}


def add_arguments(parser):
    parser.add_argument("--scenario", choices=list(SCENARIOS), default="normal", metavar="NAME",
                        help="preset story: " + ", ".join(SCENARIOS) + " (default: normal; descriptions: logger-generator --list-scenarios). The options below adjust it")
    parser.add_argument("--serial", default="99S-0001", help="fridge serial (last 7 characters), also the file name prefix (default: 99S-0001)")
    parser.add_argument("--created", default="2026-10-15T09:20:00", help="report creation, yyyy-mm-ddTHH:MM:SS (default: 2026-10-15T09:20:00)")
    parser.add_argument("--days", type=int, default=60, help="day rows in the report window (default: 60)")
    parser.add_argument("--active-days", type=int, help="days with readings; earlier rows are blank (default: all)")
    parser.add_argument("--seed", type=int, default=1, help="random seed; same arguments + seed = identical files (default: 1)")
    parser.add_argument("--base", type=float, help="typical daily mean in C (default: 4.6)")
    parser.add_argument("--swing", type=float, help="half the normal daily range in C (default: 0.8)")
    parser.add_argument("--excursion", action="append", default=[], metavar="DAYS_AGO,HH:MM,HH:MM,PEAK",
                        help="push the temperature towards PEAK (C) between two times on one day (repeatable; DAYS_AGO 0 is the report day)")
    parser.add_argument("--drift", action="append", default=[], metavar="DAYS_AGO:OFFSET",
                        help="shift a whole day's baseline by OFFSET C, e.g. 8:1.5 (repeatable)")
    parser.add_argument("--legacy", action="store_true", help="write the older firmware's 10-column layout")
    parser.add_argument("--out", required=True, help="folder for the .csv and .pdf (existing .csv/.pdf there are replaced)")


def run(args):
    preset = dict(SCENARIOS[args.scenario][1])
    damage_step = preset.pop("damage", None)
    story = replace(MetaFridgeStory(serial=args.serial, created=datetime.strptime(args.created, "%Y-%m-%dT%H:%M:%S"),
                                    days=args.days, seed=args.seed), **preset)
    overrides = {k: v for k, v in {"active_days": args.active_days, "base": args.base, "swing": args.swing}.items()
                 if v is not None}
    if args.legacy:
        overrides["legacy"] = True
    story = replace(story, **overrides)
    for spec in args.excursion:
        days_ago, start, end, peak = spec.split(",")
        story.excursions = story.excursions + [fridgetag.Excursion(int(days_ago), start, end, float(peak))]
    for spec in args.drift:
        k, v = spec.split(":")
        story.drift = {**story.drift, int(k): float(v)}
    days = write(story, args.out)
    if damage_step:
        damage_step(args.out)
    print(describe(story, days))
