"""The scenario catalogue: per-format presets and curated multi-file stories.

Per-format presets live next to their generator (`fridgetag.SCENARIOS`, `ems.SCENARIOS`,
`haier.SCENARIOS`) and are chosen with `--scenario` on that command. The curated stories
here write several drives at once and take no options except `--out`:

    logger-generator scenario screenshot-story --out DIR
    logger-generator --list-scenarios
"""
import os
from dataclasses import replace
from datetime import datetime

from . import ems, ems_simple, fridgetag, haier
from .fridgetag import Excursion


def _fridgetag(name, folder, story):
    preset = dict(fridgetag.SCENARIOS[name][1])
    step = preset.pop("damage", None)
    story = replace(story, **preset)
    days = fridgetag.write(story, folder)
    if step:
        step(folder)
    return f"{name}: Fridge-tag {story.model} {story.serial}, " + fridgetag.describe(days).split("\n")[0]


def _ems(name, folder, story=None):
    preset = dict(ems.SCENARIOS[name][1])
    step = preset.pop("damage", None)
    story = replace(story or ems.EmsStory(), **preset)
    records = ems.write(story, folder)
    if step:
        step(folder)
    return f"{name}: EMS {story.serial}, {len(records)} records"


def _haier(name, folder, story=None):
    preset = dict(haier.SCENARIOS[name][1])
    step = preset.pop("damage", None)
    story = replace(story or haier.HaierStory(), **preset)
    values = haier.write(story, folder)
    if step:
        step(folder)
    return f"{name}: Haier {story.serial}, " + haier.describe(story, values)


def screenshot_story(out):
    """App screenshot data for a clinic read on 2026-10-15: FridgeTag/, FridgeTagPast/ and EMS/.

    - FridgeTag/: today's Fridge-tag 2E on a solar fridge: a heat alarm 21 days back in a
      cloudy spell, a warm day after it (minutes, no alarm), a freeze alarm 35 days back.
    - FridgeTagPast/: an older Fridge-tag 2 report (2026-07-20) with one short warm spell.
    - EMS/: a Haier HBC-260 drive, 75 days active: three outages (80 min, 40 min and a
      16-hour cut 4 days before the read that raises HEAT) and a lid ajar for 40 minutes.
    """
    today = fridgetag.Story(
        "2E", "160600231754", datetime(2026, 10, 15, 9, 20), seed=21,
        base=4.7, swing=0.8, activated=datetime(2026, 2, 17, 10, 42),
        drift={23: 0.6, 22: 1.3, 21: 1.6, 20: 1.2, 19: 0.5},
        excursions=[
            Excursion(21, "07:30", "23:50", 11.8),  # heat alarm
            Excursion(20, "12:00", "19:20", 9.2),  # warm again, below the alarm time
            Excursion(35, "04:20", "07:20", -1.3),  # cold dawn on a full ice bank: freeze alarm
        ],
        errors=[(7, 1, "2026-02-17 10:39")],
    )
    past = fridgetag.Story(
        "2", "130400027419", datetime(2026, 7, 20, 10, 5), seed=4,
        base=4.9, swing=0.6, peak_hour=15.0, activated=datetime(2025, 11, 3, 14, 18),
        excursions=[Excursion(12, "13:10", "17:30", 9.6)],  # short, no alarm
        errors=[(12, 2, "2026-01-22 16:47")],
    )
    lines = []
    for folder, story in (("FridgeTag", today), ("FridgeTagPast", past)):
        days = fridgetag.write(story, os.path.join(out, folder))
        lines.append(f"{folder}: {story.model} {story.serial}, " + fridgetag.describe(days))
    story = ems.EmsStory(outages=[(44, "13:30", 80), (27, "19:05", 40), (4, "15:10", 16 * 60)],
                         lids=[(23, "11:05", 40)])
    lines.append("EMS: " + ems.describe(story, ems.write(story, os.path.join(out, "EMS"))))
    return "\n".join(lines)


def demo_ems(out):
    """A simple E006 drive (`SAMPLE-EMS-0001`, first-order model): 60 days of 15-minute records
    on mains, one short cut, no other alarms, a placeholder summary PDF."""
    records = ems_simple.generate({"outages": [(47.40, 47.43)]}, seed=3)
    ems_simple.write(out, "SAMPLE-EMS-0001", records)
    return ems_simple.describe(records)


def demo_ems_alarm(out):
    """The `demo-ems` fridge (`SAMPLE-EMS-0002`) with a long cut (HEAT, POWR), a thermostat fault
    (FRZE) and a door left open (DOOR)."""
    records = ems_simple.generate({
        "outages": [(21.55, 21.70), (52.30, 53.25)],
        "freeze": [(39.20, 39.33)],
        "door_open": [(56.45, 56.49)],
    }, seed=5)
    ems_simple.write(out, "SAMPLE-EMS-0002", records)
    return ems_simple.describe(records)


def parser_edge_cases(out):
    """Every damaged variant, one folder each: ems-truncated-json, ems-invalid-relt,
    ems-duplicate-records, ems-missing-sync, ems-history-case, fridgetag-truncated,
    haier-damaged-lines, plus fridgetag-unset-clock and fridgetag-fahrenheit (valid but
    unusual)."""
    lines = []
    for name in ("damaged-truncated-json", "damaged-invalid-relt", "damaged-duplicate-records",
                 "damaged-missing-sync", "damaged-history-case"):
        lines.append(_ems(name, os.path.join(out, "ems-" + name.removeprefix("damaged-"))))
    base = fridgetag.Story("2E", "160600000003", datetime(2026, 10, 15, 9, 20), seed=3)
    lines.append(_fridgetag("damaged-truncated", os.path.join(out, "fridgetag-truncated"), base))
    lines.append(_fridgetag("unset-clock", os.path.join(out, "fridgetag-unset-clock"), replace(base, serial="160600000004")))
    lines.append(_fridgetag("fahrenheit", os.path.join(out, "fridgetag-fahrenheit"), replace(base, serial="160600000005")))
    lines.append(_haier("damaged-lines", os.path.join(out, "haier-damaged-lines")))
    return "\n".join(lines)


def format_tour(out):
    """One normal download of every format: fridgetag-2, fridgetag-2E, fridgetag-2L, ems, haier."""
    lines = []
    for i, model in enumerate(("2", "2E", "2L"), start=1):
        story = fridgetag.Story(model, f"16060000001{i}", datetime(2026, 10, 15, 9, 20), seed=10 + i)
        lines.append(_fridgetag("normal", os.path.join(out, f"fridgetag-{model}"), story))
    lines.append(_ems("normal", os.path.join(out, "ems")))
    lines.append(_haier("normal", os.path.join(out, "haier")))
    return "\n".join(lines)


def alarm_tour(out):
    """One alarm of each kind per format: fridgetag-heat, fridgetag-freeze, ems-power-outage,
    ems-door-left-open, ems-freeze-event, haier-heat."""
    base = fridgetag.Story("2E", "160600000021", datetime(2026, 10, 15, 9, 20), seed=21)
    return "\n".join([
        _fridgetag("heat-excursion", os.path.join(out, "fridgetag-heat"), base),
        _fridgetag("freeze-event", os.path.join(out, "fridgetag-freeze"), replace(base, serial="160600000022")),
        _ems("power-outage", os.path.join(out, "ems-power-outage")),
        _ems("door-left-open", os.path.join(out, "ems-door-left-open")),
        _ems("freeze-event", os.path.join(out, "ems-freeze-event")),
        _haier("heat-excursion", os.path.join(out, "haier-heat")),
    ])


STORIES = {
    "screenshot-story": screenshot_story,
    "demo-ems": demo_ems,
    "demo-ems-alarm": demo_ems_alarm,
    "parser-edge-cases": parser_edge_cases,
    "format-tour": format_tour,
    "alarm-tour": alarm_tour,
}


def catalogue():
    """Text listing of every scenario, grouped by command."""
    lines = []
    for command, table in (("fridgetag", fridgetag.SCENARIOS), ("ems", ems.SCENARIOS), ("haier", haier.SCENARIOS)):
        lines.append(f"logger-generator {command} --scenario NAME")
        lines += [f"  {name:<28} {description}" for name, (description, _) in table.items()]
        lines.append("")
    lines.append("logger-generator scenario NAME --out DIR   (curated multi-file stories)")
    for name, function in STORIES.items():
        lines.append(f"  {name:<28} {' '.join(function.__doc__.split(chr(10) * 2)[0].split())}")
    return "\n".join(lines)
