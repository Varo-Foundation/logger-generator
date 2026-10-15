"""WHO PQS E006 EMS drives: CURRENT_DATA, SYNC, DATA_HISTORY/ and the 60DTR summary PDF.

    logger-generator ems --scenario power-outage --seed 3 --out DIR
    logger-generator ems --outage 4,15:10,960 --lid-ajar 23,11:05,40 --out DIR

Also importable: build an `EmsStory` and call `write(story, folder)`; `describe(story, records)`
summarizes.

The default appliance is a Haier HBC-260 ice-lined refrigerator on mains with its
integrated EMS (a commercially sold, PQS-prequalified fridge), indoor ambient about
18-25 C. The physics:

- Ambient: a daily cosine (warmest mid-afternoon) plus noise and a slow day-to-day
  weather drift.
- Door openings: a Poisson process during clinic hours with a small off-hours rate; the
  presets in `DOOR_PATTERNS` (best practice, normal, frequent short, busy, few but long)
  were tuned so their opening counts and open seconds per day span what deployed fleets
  show, from well-run clinics to staff leaving the door open.
- Chamber: a two-node model (the air the probe reads, the bulk contents) with an ice bank
  at 0 C, Euler-integrated in 10 s steps. The compressor cycles on the ice bank's charge
  (on below 60 %, off when full), so CMPR shows real cycling, and the air-to-ice coupling
  weakens with the square root of the charge, so the chamber warms gradually as the
  lining melts.
- Faults: grid outages (POWR), a lid left ajar (DOOR), a compressor failure (cooling stops
  while mains stays on), a thermostat fault (compressor stuck on with a subcooled lining:
  FRZE) and a refrigerant leak (cooling capacity decays exponentially, so the chamber
  creeps up over days).

The ice reserve is deliberately small (the lining only partly frozen): a fully frozen
HBC-260 lining rides out a 16-hour cut at this ambient without an excursion.

The drive follows the PQS E006 layout: `<LSER>_CURRENT_DATA_<RELT>.json`,
`<LSER>_SYNC_<RELT>.json` and `<LSER>_60DTR_SUMMARY_<RELT>.pdf` at the root (named with the
read's relative time, with seconds), and `DATA_HISTORY/<LSER>_DATA_<RELT>.json` per completed
60-day block (named with the block's end, without seconds). Records every 15 minutes on the
activation grid, RELT like `P74DT22H30M`. SYNC holds a reading at the read time plus the
newest record. Files are printed the way the logger's cJSON does (tab indents, `},{`
between records); `--compact` writes minified JSON instead. Times are relative to
activation, so apps date the records from the moment the drive is read.
"""
import json
import math
import os
import random
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from . import damage, pdf
from .util import clear, parse_event, relt

INTERVAL = 900
SUB_STEP = 10
BLOCK = 60 * 86400  # one DATA_HISTORY file per 60 days

HAIER_HBC260 = [
    ("ACAT", "RF03"), ("ADOP", "2026-05-18"), ("AMFR", "Haier Biomedical"), ("AMOD", "HBC-260"),
    ("APQS", "E003/087"), ("ASER", None), ("CNAM", "Embraco"), ("CSER", "51962XXXX"),
    ("LDOP", "2026-05-18"), ("LMFR", "Haier Biomedical"), ("LMOD", "Haier-EMS"), ("LPQS", "E006/0XX"),
    ("LSER", None), ("LSV", "v01.02.011"), ("EDOP", "2026-05-18"), ("EMFR", "Haier Biomedical"),
    ("EMOD", "Haier-EMS"), ("EPQS", "E006/0XX"), ("ESER", None), ("EMSV", "V1.0.2"),
]


@dataclass(frozen=True)
class DoorPattern:
    """Poisson door openings: `rate` per hour in clinic hours, `off_rate` outside them,
    durations ~ N(mean, std) seconds (at least 4 s)."""
    rate: float
    off_rate: float
    mean: float
    std: float
    hours: tuple
    description: str


DOOR_PATTERNS = {
    "best-practice": DoorPattern(0.25, 0.0125, 25.0, 10.0, (8, 17), "about 2 short openings a day (well-run clinic)"),
    "normal": DoorPattern(0.7, 0.035, 25.0, 10.0, (8, 17), "4-8 openings of about 25 s a day"),
    "frequent-short": DoorPattern(1.2, 0.06, 25.0, 10.0, (8, 17), "about 10 brief openings a day"),
    "busy": DoorPattern(1.2, 0.18, 25.0, 10.0, (6, 20), "16+ openings a day over long hours (campaign days)"),
    "few-but-long": DoorPattern(0.3, 0.03, 180.0, 120.0, (8, 17), "about 3 openings a day of several minutes each"),
}


@dataclass
class EmsStory:
    seed: int = 26
    appliance_serial: str = "BE0H26A1T00LM4K70216"
    header: list = field(default_factory=lambda: list(HAIER_HBC260))
    read_at: datetime = datetime(2026, 10, 15, 9, 20)  # wall clock, for the day/night cycle only
    active_days: int = 75  # days since activation at the read
    ambient_mean: float = 21.5
    ambient_swing: float = 3.0
    door: str = "normal"
    # Events in days before the read, as (days_ago, "HH:MM", minutes).
    outages: list = field(default_factory=list)
    lids: list = field(default_factory=list)
    compressor_failures: list = field(default_factory=list)
    thermostat_faults: list = field(default_factory=list)
    leak: tuple = None  # (days_ago, rate per hour): cooling capacity x exp(-rate * hours)
    compact: bool = False

    @property
    def serial(self):
        return self.appliance_serial + "EMS"

    @property
    def now(self):
        """Read time in seconds since activation (a little after 02:13 into the last day)."""
        return (self.active_days * 24 + 2) * 3600 + 13 * 60 + 37

    def header_fields(self):
        ids = {"ASER": self.appliance_serial, "ESER": self.appliance_serial, "LSER": self.serial}
        return [(k, ids.get(k, v)) for k, v in self.header]

    def wall(self, t):
        return self.read_at - timedelta(seconds=self.now - t)

    def window(self, events):
        spans = []
        for days_ago, start, minutes in events:
            h, m = map(int, start.split(":"))
            begin = self.read_at.replace(hour=h, minute=m) - timedelta(days=days_ago)
            t0 = self.now - (self.read_at - begin).total_seconds()
            spans.append((t0, t0 + minutes * 60))
        return spans


class Thermal:
    """Two-node chamber (air the probe reads, contents) with an ice bank."""

    R = 1.63  # chamber to ambient, K/W
    C = 30000.0  # chamber air + contents, J/K
    C_AIR = 5000.0  # chest: little air exchange
    R_AIR_CONTENTS = 0.6
    R_DOOR = 0.24  # chest lid
    R_ICE = 0.375
    ICE_J = 150_000.0  # usable latent heat left in the lining
    Q_COMPRESSOR = 32.0  # effective ice-building rate, W
    SOC_ON, SOC_OFF = 0.6, 1.0
    SUBCOOLED_ICE = -7.0  # lining temperature with the compressor stuck on

    def __init__(self):
        self.air = self.contents = 4.0
        self.soc = 1.0
        self.compressor = False

    def step(self, ambient, powered, door_open, cooling=1.0, can_run=True, stuck_on=False):
        if not powered or not can_run:
            self.compressor = False
        elif stuck_on or self.soc <= self.SOC_ON:
            self.compressor = True
        elif self.soc >= self.SOC_OFF:
            self.compressor = False
        q_ambient = (ambient - self.air) / self.R
        q_door = (ambient - self.air) / self.R_DOOR if door_open else 0.0
        q_contents = (self.contents - self.air) / self.R_AIR_CONTENTS
        # Less ice left, less ice surface: the coupling weakens as the lining melts, so the
        # chamber creeps up through the lining instead of jumping when the last ice goes.
        air_to_ice = self.air - self.SUBCOOLED_ICE if stuck_on and self.compressor else self.air
        q_ice = air_to_ice * math.sqrt(self.soc) / self.R_ICE
        self.air += (q_ambient + q_door + q_contents - q_ice) / self.C_AIR * SUB_STEP
        self.contents += -q_contents / (self.C - self.C_AIR) * SUB_STEP
        melt = q_ice - (self.Q_COMPRESSOR * cooling if self.compressor else 0.0)
        self.soc = min(1.0, max(0.0, self.soc - melt * SUB_STEP / self.ICE_J))
        return self.compressor


def simulate(story):
    """15-minute records from activation to the read."""
    rnd = random.Random(story.seed)
    thermal = Thermal()
    pattern = DOOR_PATTERNS[story.door]
    outages, lids = story.window(story.outages), story.window(story.lids)
    failures, stuck = story.window(story.compressor_failures), story.window(story.thermostat_faults)
    leak_start = story.window([(story.leak[0], "00:00", 0)])[0][0] if story.leak else None
    records = []
    heat_since = freeze_since = None
    blog = 12.6
    weather = 0.0
    for k in range(1, story.now // INTERVAL + 1):
        t_end = k * INTERVAL
        t0 = t_end - INTERVAL
        clock = story.wall(t0)
        hour = clock.hour + clock.minute / 60
        if k % 96 == 1:
            weather = 0.7 * weather + rnd.gauss(0, 0.5)
        ambient = (story.ambient_mean + weather + story.ambient_swing * math.cos(2 * math.pi * (hour - 14.5) / 24)
                   + rnd.gauss(0, 0.35))

        open_hours = pattern.hours[0] <= hour < pattern.hours[1] and clock.weekday() < 6
        rate = pattern.rate if open_hours else pattern.off_rate
        openings = []  # (start offset s, length s, opened in this interval)
        n, p, limit = 0, rnd.random(), math.exp(-rate * INTERVAL / 3600)
        while p > limit:
            n += 1
            p *= rnd.random()
        for _ in range(n):
            start = rnd.uniform(0, INTERVAL)
            openings.append((start, min(INTERVAL - start, max(4.0, rnd.gauss(pattern.mean, pattern.std))), True))
        for a, b in lids:
            if a < t_end and b > t0:
                openings.append((max(a, t0) - t0, min(b, t_end) - max(a, t0), a >= t0))

        # While the lid stands open, other "openings" are the same opening.
        lid_full = any(a <= t0 and b >= t_end for a, b in lids)
        powered_s = door_s = cmpr_s = 0
        for s in range(0, INTERVAL, SUB_STEP):
            t = t0 + s
            powered = not any(a <= t < b for a, b in outages)
            door = any(start <= s < start + length for start, length, _ in openings)
            cooling = math.exp(-story.leak[1] * (t - leak_start) / 3600) if leak_start is not None and t >= leak_start else 1.0
            if thermal.step(ambient, powered, door, cooling,
                            can_run=not any(a <= t < b for a, b in failures),
                            stuck_on=any(a <= t < b for a, b in stuck)):
                cmpr_s += SUB_STEP
            powered_s += SUB_STEP if powered else 0
            door_s += SUB_STEP if door else 0
        tvc = round(thermal.air, 1)

        alarms = []
        heat_since = (heat_since if heat_since is not None else t_end) if tvc > 8 else None
        if heat_since is not None and t_end - heat_since >= 10 * 3600 - INTERVAL:
            alarms.append("HEAT")
        freeze_since = (freeze_since if freeze_since is not None else t_end) if tvc <= -0.5 else None
        if freeze_since is not None and t_end - freeze_since >= 3600 - INTERVAL:
            alarms.append("FRZE")
        if any(length >= 300 for _, length, _ in openings):  # open 5 minutes in a row
            alarms.append("DOOR")
        if powered_s < INTERVAL:
            alarms.append("POWR")

        blog = min(12.7, blog + 0.05) if powered_s == INTERVAL else blog - 0.03 * (1 - powered_s / INTERVAL)
        on = powered_s > 0
        records.append({
            "BLOG": round(blog, 1), "BEMD": round(blog, 1),
            "CMPR": cmpr_s, "DORV": door_s, "DRCV": sum(1 for _, length, new in openings if new and not lid_full),
            "RELT": relt(t_end, with_seconds=False), "RTCW": "PT0S",
            "TAMB": round(ambient, 1), "TVC": tvc,
            "SVA": powered_s,
            "ACCD": round(0.03 + 0.43 * cmpr_s / INTERVAL + rnd.uniform(-0.01, 0.01), 2) if on else 0,
            "ACSV": round(rnd.gauss(236, 3.5), 1) if on else 0,
            "ALRM": " ".join(alarms) if alarms else None,
        })
    return records


def cjson_value(value):
    if value is None:
        return "null"
    if isinstance(value, str):
        return '"' + value + '"'
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return repr(value) if isinstance(value, float) else str(value)


def cjson(header, records):
    """Formats a file the way cJSON_Print does on the logger: tab indents, `},{` between records."""
    lines = ["{"] + [f'\t"{k}":\t{cjson_value(v)},' for k, v in header]
    body = []
    for record in records:
        body.append(",\n".join(f'\t"{k}":\t{cjson_value(v)}' for k, v in record.items()))
    lines.append('\t"records":\t[{\n' + "\n},{\n".join(body) + "\n}]")
    lines.append("}")
    return "\n".join(lines)


def compact_json(header, records):
    return json.dumps(dict(header, records=records), separators=(",", ":"))


def split_blocks(records, interval=INTERVAL):
    """[(block end seconds, records)] for each completed 60-day block, and the current records."""
    per_block = BLOCK // interval
    blocks = []
    while len(records) - len(blocks) * per_block > per_block:
        start = len(blocks) * per_block
        blocks.append(((len(blocks) + 1) * BLOCK, records[start:start + per_block]))
    return blocks, records[len(blocks) * per_block:]


def write(story, out):
    """Replaces the drive's JSON/PDF files with this story's; returns the records."""
    records = simulate(story)
    for sub in ("", "DATA_HISTORY"):
        clear(os.path.join(out, sub), (".json", ".pdf"))
    blocks, current = split_blocks(records)
    now = relt(story.now)
    header = story.header_fields()
    serial = story.serial

    def dump(path, recs):
        with open(path, "w") as f:
            f.write(compact_json(header, recs) if story.compact else cjson(header, recs))

    for end, recs in blocks:
        dump(os.path.join(out, "DATA_HISTORY", f"{serial}_DATA_{relt(end, with_seconds=False)}.json"), recs)
    dump(os.path.join(out, f"{serial}_CURRENT_DATA_{now}.json"), current)
    last = current[-1]
    reading = {"IDRV": 0, "RELT": now, "RTCW": "PT0S", "TVC": last["TVC"]}
    dump(os.path.join(out, f"{serial}_SYNC_{now}.json"), [reading, last])
    summary_pdf(os.path.join(out, f"{serial}_60DTR_SUMMARY_{now}.pdf"), story, records)
    return records


def daily(story, records):
    """Per-day summaries of the last 60 days, dated by the read, for the summary PDF."""
    by_day = {}
    for i, r in enumerate(records):
        by_day.setdefault(story.wall((i + 1) * INTERVAL).date(), []).append(r)
    days = []
    for day in sorted(by_day)[-60:]:
        rs = by_day[day]
        temps = [r["TVC"] for r in rs]
        high = sum(INTERVAL // 60 for r in rs if r["TVC"] > 8)
        low = sum(INTERVAL // 60 for r in rs if r["TVC"] <= -0.5)
        heat = any("HEAT" in (r["ALRM"] or "") for r in rs)
        freeze = any("FRZE" in (r["ALRM"] or "") for r in rs)
        days.append({"date": day, "min": min(temps), "max": max(temps),
                     # fsum: plain sum() changed its rounding in Python 3.12; fsum is the same everywhere.
                     "mean": round(math.fsum(temps) / len(temps), 1),
                     "low": (low, "x" if freeze else None), "high": (high, "x" if heat else None)})
    return days


def summary_pdf(path, story, records):
    fields = dict(story.header_fields())
    info = [
        ("Appliance", f"{fields.get('AMFR', '')} {fields.get('AMOD', '')}".strip()),
        ("Appliance serial", story.appliance_serial),
        ("EMS serial", story.serial), ("Software", fields.get("LSV", "")),
        ("Heat alarm", "above +8.0 °C for 10 h"), ("Freeze alarm", "-0.5 °C or below, 60 min"),
    ]
    pdf.summary_report_pdf(path, "60-day temperature summary", "Vaccine chamber (TVC), daily values", info,
                           daily(story, records), story.serial,
                           "Low/High: minutes beyond the alarm limit that day. Shaded rows: an alarm (HEAT or FRZE) was raised.")


def describe(story, records):
    """Record count, events, time above +8 C, alarm kinds and value ranges."""
    days_before = lambda t: (story.now - t) / 86400  # noqa: E731
    lines = [f"{len(records)} records over {len(records) * INTERVAL / 86400:.1f} days"]
    for label, events in (("outage", story.outages), ("lid ajar", story.lids),
                          ("compressor failure", story.compressor_failures), ("thermostat fault", story.thermostat_faults)):
        for a, b in story.window(events):
            lines.append(f"{label} {days_before(a):.2f} to {days_before(b):.2f} days before the read")
    above = sum(1 for r in records if r["TVC"] > 8)
    heat = [i for i, r in enumerate(records) if "HEAT" in (r["ALRM"] or "")]
    lines += [
        f"TVC above +8 C for {above * INTERVAL / 3600:.2f} h in total",
        f"HEAT records: {len(heat)}, first {days_before((heat[0] + 1) * INTERVAL):.2f} days before the read" if heat else "no HEAT",
        f"ALRM kinds: {sorted(set(r['ALRM'] for r in records if r['ALRM']))}",
        f"compressor duty {sum(r['CMPR'] for r in records) / (len(records) * INTERVAL):.0%}, "
        f"TVC {min(r['TVC'] for r in records)}..{max(r['TVC'] for r in records)}, "
        f"TAMB {min(r['TAMB'] for r in records)}..{max(r['TAMB'] for r in records)}",
    ]
    return "\n".join(lines)


# --- Scenarios ---------------------------------------------------------------------------

SCENARIOS = {
    "normal": ("Ordinary door openings and compressor cycling, no events, no alarms", {}),
    "power-outage": ("A 30-hour grid outage starting 2 days before the read: POWR throughout, HEAT once the "
                     "chamber has been above +8 C for 10 h", {"outages": [(2, "18:00", 1800)]}),
    "short-outages": ("Three short cuts (80, 40 and 25 minutes): POWR records, the ice lining keeps the chamber "
                      "in range", {"outages": [(44, "13:30", 80), (27, "19:05", 40), (9, "07:40", 25)]}),
    "door-left-open": ("The lid left ajar for 4 hours 3 days before the read: DOOR while open, the chamber "
                       "warms", {"lids": [(3, "10:15", 240)]}),
    "heat-excursion": ("The compressor fails for 36 hours with mains on (no POWR): the chamber warms through the "
                       "lining and raises HEAT", {"compressor_failures": [(5, "06:00", 36 * 60)]}),
    "freeze-event": ("A thermostat fault 8 days before the read keeps the compressor running for 10 hours on a "
                     "subcooled lining: FRZE", {"thermostat_faults": [(8, "01:00", 600)]}),
    "refrigerant-leak": ("A refrigerant leak from 20 days before the read: cooling capacity decays (1 %/h), the "
                         "compressor runs ever longer and the chamber creeps up to HEAT", {"leak": (20, 0.01)}),
    "busy-clinic": ("A busy facility: 16+ door openings a day over long hours (door pattern 'busy')", {"door": "busy"}),
    "few-but-long": ("Staff leave the door open for minutes at a time (door pattern 'few-but-long'): DOOR "
                     "alarms and warm spikes", {"door": "few-but-long"}),
    "no-history-yet": ("A drive read 50 days after activation: no completed 60-day block, so DATA_HISTORY is "
                       "empty", {"active_days": 50}),
    "long-history": ("A drive read 150 days after activation: two DATA_HISTORY blocks", {"active_days": 150}),
    "damaged-truncated-json": ("CURRENT_DATA cut off part-way through a record (invalid JSON)",
                               {"damage": damage.truncate_current}),
    "damaged-invalid-relt": ("Some records carry malformed or impossible relative timestamps "
                             "(`P74DT25H`, `PXDT1H`, empty, missing)", {"damage": damage.invalid_relt}),
    "damaged-duplicate-records": ("A run of records repeated in CURRENT_DATA (same RELT twice)",
                                  {"damage": damage.duplicate_records}),
    "damaged-missing-sync": ("The SYNC file is missing", {"damage": damage.missing_sync}),
    "damaged-history-case": ("The history folder is `data_history` instead of `DATA_HISTORY`",
                             {"damage": damage.history_case}),
}


def build_story(args):
    preset = dict(SCENARIOS[args.scenario][1])
    damage_step = preset.pop("damage", None)
    story = replace(EmsStory(seed=args.seed), **preset)
    if args.appliance_serial:
        story.appliance_serial = args.appliance_serial
    if args.read_at:
        story.read_at = datetime.strptime(args.read_at, "%Y-%m-%dT%H:%M")
    if args.active_days:
        story.active_days = args.active_days
    if args.door:
        story.door = args.door
    if args.ambient is not None:
        story.ambient_mean = args.ambient
    story.outages = story.outages + (args.outage or [])
    story.lids = story.lids + (args.lid_ajar or [])
    story.compressor_failures = story.compressor_failures + (args.compressor_failure or [])
    story.thermostat_faults = story.thermostat_faults + (args.thermostat_fault or [])
    if args.leak:
        days_ago, _, rate = args.leak.partition(",")
        story.leak = (int(days_ago), float(rate or 0.01))
    for spec in args.header:
        key, _, value = spec.partition("=")
        if key in ("ASER", "ESER", "LSER"):
            raise SystemExit(f"set {key} with --appliance-serial")
        fields = dict(story.header)
        fields[key] = value
        story.header = list(fields.items())
    story.compact = args.compact
    return story, damage_step


def add_arguments(parser):
    parser.add_argument("--scenario", choices=list(SCENARIOS), default="normal", metavar="NAME",
                        help="preset story: " + ", ".join(SCENARIOS) + " (default: normal; descriptions: logger-generator --list-scenarios). The options below add to it")
    parser.add_argument("--seed", type=int, default=26, help="random seed; same arguments + seed = identical files (default: 26)")
    parser.add_argument("--appliance-serial", help="ASER/ESER; the logger serial LSER appends 'EMS' (default: BE0H26A1T00LM4K70216)")
    parser.add_argument("--read-at", help="wall-clock time of the read, yyyy-mm-ddTHH:MM, for the day/night and clinic-hours "
                                          "cycle (default: 2026-10-15T09:20; the files carry only relative times)")
    parser.add_argument("--active-days", type=int, help="days since activation at the read; each completed 60 days go to "
                                                        "DATA_HISTORY, the rest to CURRENT_DATA (default: 75)")
    parser.add_argument("--door", choices=list(DOOR_PATTERNS),
                        help="door-opening pattern: " + "; ".join(f"{k}: {v.description}" for k, v in DOOR_PATTERNS.items()))
    parser.add_argument("--ambient", type=float, help="mean indoor ambient in C (default: 21.5)")
    parser.add_argument("--outage", action="append", type=parse_event, metavar="DAYS_AGO,HH:MM,MINUTES",
                        help="grid power cut (repeatable)")
    parser.add_argument("--lid-ajar", action="append", type=parse_event, metavar="DAYS_AGO,HH:MM,MINUTES",
                        help="lid/door left open (repeatable)")
    parser.add_argument("--compressor-failure", action="append", type=parse_event, metavar="DAYS_AGO,HH:MM,MINUTES",
                        help="compressor can't run while mains stays on (repeatable)")
    parser.add_argument("--thermostat-fault", action="append", type=parse_event, metavar="DAYS_AGO,HH:MM,MINUTES",
                        help="compressor stuck on with a subcooled lining (repeatable)")
    parser.add_argument("--leak", metavar="DAYS_AGO[,RATE]", help="refrigerant leak from that day: cooling x exp(-RATE * hours) "
                                                                 "(default rate 0.01/h)")
    parser.add_argument("--header", action="append", default=[], metavar="KEY=VALUE",
                        help="override a header field, e.g. LSV=v01.03.000 (repeatable)")
    parser.add_argument("--compact", action="store_true", help="minified JSON instead of the logger's cJSON layout")
    parser.add_argument("--out", required=True, help="drive folder to (re)write")


def run(args):
    story, damage_step = build_story(args)
    records = write(story, args.out)
    if damage_step:
        damage_step(args.out)
    print(describe(story, records))
