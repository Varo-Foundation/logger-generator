"""A first-order EMS model behind the `demo-ems` and `demo-ems-alarm` stories.

Simpler than `ems` (no thermal nodes or ice bank: the chamber relaxes towards a set point
and towards ambient during a cut), kept because existing app demo datasets were made with
it. It writes 60 days of 15-minute records on mains, half in DATA_HISTORY and half in
CURRENT_DATA, as compact JSON with `HOLD` (holdover days) and `LERR` fields, plus a
placeholder 60DTR summary PDF. Prefer `ems` for anything new.

Events are given in days from the first record, as [(start_day, end_day)] fractions:
`outages` (POWR, slow warming), `freeze` (compressor stuck on: FRZE) and `door_open`
(DOOR after two full intervals).
"""
import json
import math
import os
import random

from . import pdf
from .util import clear, parse_relt, relt

INTERVAL = 900
DAYS = 60
ACTIVATED_DAYS_AGO = 140  # relative times count from activation


def header(serial):
    return {
        "AMFR": "Haier Biomedical", "AMOD": "HBC-260", "ASER": "BJ0123456789", "ADOP": "2023-05-02",
        "APQS": "E003/000", "ACAT": "RF03",
        "CNAM": "Secop", "CSER": "SC21-004512", "CDAT": "2023-04-11", "CSOF": "1.4.2",
        "LMFR": "Sample Logger Co", "LMOD": "EMS-1", "LSER": serial, "LDOP": "2023-05-02",
        "LPQS": "E006/000", "LSV": "2.3.1",
    }


def generate(events, seed):
    """60 days of records; see the module docstring for `events`."""
    rnd = random.Random(seed)
    count = DAYS * 86400 // INTERVAL
    start = (ACTIVATED_DAYS_AGO - DAYS) * 86400
    records = []
    temp = 4.6
    heat_secs = freeze_secs = 0
    door_streak = 0
    for i in range(count):
        t = start + (i + 1) * INTERVAL
        day = i * INTERVAL / 86400
        hour = (i * INTERVAL % 86400) / 3600
        ambient = 25 + 5 * math.sin((hour - 9) / 24 * 2 * math.pi) + rnd.uniform(-0.4, 0.4)

        outage = any(a <= day < b for a, b in events.get("outages", []))
        frozen = any(a <= day < b for a, b in events.get("freeze", []))
        door_left = any(a <= day < b for a, b in events.get("door_open", []))

        power = 0 if outage else INTERVAL
        door = 0
        if door_left:
            door = INTERVAL
        elif 8 <= hour < 17 and rnd.random() < 0.18:
            door = rnd.randint(8, 75)

        if outage:
            compressor = 0
            temp += (ambient - temp) * 0.006  # warms slowly through the ice lining
        elif frozen:
            compressor = INTERVAL
            temp += (-1.4 - temp) * 0.35
        else:
            duty = min(0.95, 0.35 + (ambient - 22) * 0.03 + (0.25 if temp > 6 else 0))
            compressor = int(INTERVAL * duty * rnd.uniform(0.85, 1.15))
            temp += (4.8 - temp) * (0.45 if temp > 6 else 0.25) + rnd.uniform(-0.18, 0.18)
        if door:
            temp += min(door, 120) / 120 * 0.9 + (0.6 if door_left else 0)
        temp = round(temp, 1)

        alarms = []
        heat_secs = heat_secs + INTERVAL if temp > 8 else 0
        freeze_secs = freeze_secs + INTERVAL if temp <= -0.5 else 0
        if heat_secs >= 10 * 3600:
            alarms.append("HEAT")
        if freeze_secs >= 3600:
            alarms.append("FRZE")
        door_streak = door_streak + 1 if door >= INTERVAL else 0
        if door_streak >= 2:
            alarms.append("DOOR")
        if outage:
            alarms.append("POWR")

        record = {
            "RELT": relt(t), "RTCW": "PT0S",
            "TVC": temp, "TAMB": round(ambient, 1),
            "SVA": power, "ACSV": 0 if outage else round(rnd.uniform(214, 228), 1),
            "ACCD": 0.0 if compressor == 0 else round(rnd.uniform(0.55, 0.7), 2),
            "CMPR": compressor, "DORV": door, "DRCV": 0 if door == 0 else (1 if door < INTERVAL else 0),
            "HOLD": round(max(0.0, 3.5 - max(0, temp - 4) * 0.4), 1),
            "LERR": "",
        }
        if alarms:
            record["ALRM"] = " ".join(alarms)
        records.append(record)
    return records


def write(folder, serial, records):
    """Replaces the drive's JSON/PDF files with these records."""
    clear(folder, (".json", ".pdf"))
    clear(os.path.join(folder, "DATA_HISTORY"), (".json", ".pdf"))
    half = len(records) // 2
    history, current = records[:half], records[half:]
    now = (ACTIVATED_DAYS_AGO * 86400) + 61

    def dump(name, recs, sub=""):
        with open(os.path.join(folder, sub, name), "w") as f:
            json.dump(dict(header(serial), records=recs), f, separators=(",", ":"))

    dump(f"{serial}_DATA_{relt(parse_relt(history[-1]['RELT']))}.json", history, "DATA_HISTORY")
    dump(f"{serial}_CURRENT_DATA_{relt(now)}.json", current)
    dump(f"{serial}_SYNC_{relt(now)}.json", [dict(current[-1], RELT=relt(now)), current[-1]])
    pdf.placeholder_pdf(os.path.join(folder, f"{serial}_60DTR_SUMMARY_{relt(now)}.pdf"), [
        (20, "SAMPLE DATA"),
        (14, "60-day temperature summary (placeholder)"),
        (11, f"Logger serial: {serial}"),
        (11, "Made up by logger-generator (github.com/Varo-Foundation/logger-generator)."),
        (11, "This is not a report from a real logger."),
    ])


def describe(records):
    kinds = sorted({r["ALRM"] for r in records if "ALRM" in r})
    return (f"{len(records)} records, TVC {min(r['TVC'] for r in records)}..{max(r['TVC'] for r in records)}, "
            f"ALRM kinds: {kinds}")
