"""Glue between the page and logger-generator, run in the browser by Pyodide (see worker.js).

Every download is made by the same command-line entry point a user would run, so the
command the page shows reproduces the files byte for byte.
"""
import contextlib
import glob
import io
import json
import math
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timedelta

from logger_generator import __version__, ems, fridgetag, haier, library, metafridge
from logger_generator.cli import main
from logger_generator.util import parse_relt

FORMATS = [
    ("fridgetag", "Berlinger Fridge-tag 2 / 2E / 2L", "History report .txt and its PDF", fridgetag),
    ("ems", "WHO PQS E006 EMS", "A full drive: CURRENT_DATA, SYNC, DATA_HISTORY and the 60-day summary PDF", ems),
    ("haier", "Haier HETL-01", "The 30-day recorder's CSV export", haier),
    ("metafridge", "Aucma MetaFridge CFD-50 SDD", "The 30 DTR daily report CSV and its PDF", metafridge),
]
SETS = [  # (story or "library", title, description); built once by site/build.sh, not in the browser
    ("format-tour", "Format tour", "One normal download from every logger and model."),
    ("alarm-tour", "Alarm tour", "A heat, freeze, power-cut or door alarm from each kind of logger."),
    ("parser-edge-cases", "Damaged and unusual files",
     "Cut-off reports, corrupted records, missing files and older layouts, for checking that software copes."),
    ("library", "Test library",
     "{cases} cases, each with the result an app should show, plus manifest.json for automated tests."),
]


def catalogue():
    """JSON for the page: the formats with their scenarios, the ready-made sets and the version."""
    return json.dumps({
        "version": __version__,
        "formats": [{"command": command, "name": name, "detail": detail,
                     "scenarios": [{"name": key, "description": text} for key, (text, _) in module.SCENARIOS.items()]}
                    for command, name, detail, module in FORMATS],
        "fridgetagModels": sorted(fridgetag.MODELS),
        "sets": [{"title": title, "description": text.format(cases=len(library.CASES)),
                  "file": f"sets/{_set_folder(name)}.zip", "argv": _set_argv(name), "folder": _set_folder(name)}
                 for name, title, text in SETS],
    })


def _set_argv(name):
    return ["library"] if name == "library" else ["scenario", name]


def _set_folder(name):
    return "test-library" if name == "library" else name


def build_sets(out):
    """Writes every ready-made set as `<out>/<folder>.zip` (run with CPython by site/build.sh)."""
    os.makedirs(out, exist_ok=True)
    for name, _, _ in SETS:
        data, _, zip_name, _ = run(json.dumps(_set_argv(name) + [_set_folder(name)]))
        with open(os.path.join(out, zip_name), "wb") as f:
            f.write(data)
        print(f"{zip_name}: {len(data) // 1024} KB")


def _zip(folder, top):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for root, dirs, files in os.walk(folder):
            dirs.sort()
            for name in sorted(files):
                path = os.path.join(root, name)
                archive.write(path, os.path.join(top, os.path.relpath(path, folder)))
    return buffer.getvalue()


def run(argv_json):
    """Runs `logger-generator <argv> --out <name>`; returns (zip bytes, printed summary, zip name,
    chart JSON or "null")."""
    argv = json.loads(argv_json)
    name = argv.pop()  # the folder name, also the zip name
    work = tempfile.mkdtemp()
    try:
        out = io.StringIO()
        folder = os.path.join(work, name)
        with contextlib.redirect_stdout(out):
            main(argv + ["--out", folder])
        readers = {"fridgetag": _fridgetag, "ems": _ems, "haier": _haier, "metafridge": _metafridge}
        chart = _chart(readers[argv[0]], folder) if argv[0] in readers else None
        return _zip(folder, name), out.getvalue().strip(), name + ".zip", json.dumps(chart)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# --- Charts --------------------------------------------------------------------------------
# Each reader parses the files it just wrote the way an app would, so the chart shows what is
# in the download (deliberately damaged files included: whatever still parses is shown, and a
# note says what didn't). Times are wall-clock local times sent as seconds since 1970 "UTC".

EPOCH = datetime(1970, 1, 1)
DAY = 86400


def _ts(when):
    return int((when - EPOCH).total_seconds())


def _chart(reader, folder):
    try:
        return reader(folder)
    except Exception as error:  # a damaged file the reader can't get anything from
        return {"kind": "none", "notes": [f"Nothing in this download could be charted ({type(error).__name__})."]}


def _daily_table(x, low, mean, high):
    """Per-day rows (date, min, mean, max) from a high-resolution series."""
    days = {}
    for t, v in zip(x, mean):
        if v is not None:
            days.setdefault(t // DAY, []).append(v)
    return [[(EPOCH + timedelta(days=d)).date().isoformat(), min(v), round(math.fsum(v) / len(v), 1), max(v)]
            for d, v in sorted(days.items(), reverse=True)]


def _ems(folder):
    names = sorted(glob.glob(os.path.join(folder, "*.json")) + glob.glob(os.path.join(folder, "*", "*.json")))
    read = [re.search(r"_(P\d+DT\d+H\d+M\d+S)\.json$", n) for n in names if "_CURRENT_DATA_" in n or "_SYNC_" in n]
    read_relt = max(parse_relt(m.group(1)) for m in read if m)
    read_at = ems.EmsStory().read_at  # the page always uses the default read time
    records, notes, skipped = {}, [], 0
    for name in names:
        if "_SYNC_" in name:
            continue
        try:
            with open(name) as f:
                body = json.load(f)
        except ValueError:
            notes.append(f"{os.path.basename(name)} is not valid JSON, so its records are missing here.")
            continue
        for record in body.get("records", []):
            try:
                records[parse_relt(record["RELT"])] = record
            except (KeyError, TypeError, ValueError):
                skipped += 1
    if skipped:
        notes.append(f"{skipped} record(s) with a missing or invalid RELT were skipped.")
    relts = sorted(records)
    x = [_ts(read_at - timedelta(seconds=read_relt - r)) for r in relts]
    tvc = [records[r].get("TVC") for r in relts]
    spans = []
    for kind in ("POWR", "HEAT", "FRZE", "DOOR"):
        start = None
        for t, r in zip(x, relts):
            on = kind in (records[r].get("ALRM") or "").split()
            if on and start is None:
                start = t - 900
            if not on and start is not None:
                spans.append({"kind": kind, "start": start, "end": prev})
                start = None
            prev = t
        if start is not None:
            spans.append({"kind": kind, "start": start, "end": prev})
    return {
        "kind": "series", "unit": "C", "x": x,
        "series": [{"key": "tvc", "label": "Vaccine chamber (TVC)", "values": tvc},
                   {"key": "tamb", "label": "Ambient (TAMB)", "values": [records[r].get("TAMB") for r in relts]}],
        "limits": {"low": -0.5, "high": 8.0, "source": "E006 alarm rules: FRZE at or below -0.5 C for 60 min, HEAT above +8 C for 10 h"},
        "spans": spans, "notes": notes, "table": _daily_table(x, None, tvc, None),
    }


HAIER_READING = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2}):(\d{2})\s+(-?\d+(?:\.\d+)?)$")


def _haier(folder):
    (name,) = glob.glob(os.path.join(folder, "*.CSV"))
    with open(name, newline="") as f:
        lines = f.read().split("\r\n")
    limit = lambda key: float(re.search(key + r":\s*([+-]?[\d.]+)", "\n".join(lines)).group(1))  # noqa: E731
    x, values, bad = [], [], 0
    started = False
    for line in lines:
        if line.startswith("MM.DD.YYYY"):
            started = True
            continue
        if not started or not line:
            continue
        m = HAIER_READING.match(line)
        try:
            when = datetime(int(m[3]), int(m[1]), int(m[2]), int(m[4]), int(m[5]), int(m[6]))
            if x and not 0 < _ts(when) - x[-1] <= DAY:  # readings are minutes apart
                raise ValueError("out of sequence")
            x.append(_ts(when))
            values.append(float(m[7]))
        except (TypeError, ValueError):
            bad += 1
    return {
        "kind": "series", "unit": "C", "x": x,
        "series": [{"key": "temp", "label": "Temperature", "values": values}],
        "limits": {"low": limit("Alarm Temperature Low"), "high": limit("Alarm Temperature High"), "source": "the logger's alarm settings"},
        "spans": [], "notes": [f"{bad} unreadable reading line(s) were skipped."] if bad else [],
        "table": _daily_table(x, None, values, None),
    }


def _number(text):
    return float(text.split(",")[0].strip())


def _fridgetag(folder):
    (name,) = glob.glob(os.path.join(folder, "*.txt"))
    with open(name, newline="") as f:
        lines = [line.rstrip("\r") for line in f.read().split("\n")]
    unit, limits, days, day, alarm, in_hist, in_conf_alarm = "C", {}, [], None, None, False, None
    for line in lines:
        text = line.strip()
        if text.startswith("Temp unit:"):
            unit = text.split(":")[1].strip()
        if not in_hist:
            if text in ("0:", "1:"):
                in_conf_alarm = text[0]
            elif in_conf_alarm and text.startswith("T AL:"):
                limits["low" if in_conf_alarm == "0" else "high"] = _number(text.split(":", 1)[1])
                in_conf_alarm = None
            if text == "Hist:":
                in_hist = True
            continue
        if text.startswith("Date:"):
            day = {"date": text.split(":", 1)[1].strip(), "low": [0, False], "high": [0, False]}
            days.append(day)
        elif day is None:
            continue
        elif text.startswith("Min T:"):
            day["min"] = _number(text[6:])
        elif text.startswith("Max T:"):
            day["max"] = _number(text[6:])
        elif text.startswith("Avrg T:"):
            day["mean"] = _number(text[7:])
        elif text in ("0:", "1:"):
            alarm = "low" if text == "0:" else "high"
        elif text.startswith("t Acc:") and alarm:
            day[alarm] = [int(text.split(",")[0].split(":")[1]), "TS A" in text]
            alarm = None
    complete = [d for d in days if {"min", "max", "mean"} <= d.keys()]
    notes = [] if len(complete) == len(days) else [f"The report is cut off: {len(days) - len(complete)} day(s) at the end are incomplete."]
    return _daily(complete, unit, limits, "the tag's alarm settings", notes)


def _daily(days, unit, limits, source, notes):
    days = sorted(days, key=lambda d: d["date"])
    return {
        "kind": "daily", "unit": unit, "x": [_ts(datetime.fromisoformat(d["date"])) for d in days],
        "min": [d["min"] for d in days], "mean": [d["mean"] for d in days], "max": [d["max"] for d in days],
        "low": [d["low"] for d in days], "high": [d["high"] for d in days],
        "limits": {**limits, "source": source}, "notes": notes,
        "table": [[d["date"], d["min"], d["mean"], d["max"]] for d in reversed(days)],
    }


def _metafridge(folder):
    (name,) = glob.glob(os.path.join(folder, "*.csv"))
    with open(name, encoding="utf-8-sig", newline="") as f:
        lines = [line for line in f.read().replace("\r\n", "\n").split("\n") if line]
    start = next(i for i, line in enumerate(lines) if line.lower().startswith("daynum,")) + 1

    def minutes(text):
        parts = [int(p) for p in text.split(":")]
        return parts[0] * 60 + parts[1]

    days, bad = [], 0
    for line in lines[start:]:
        cells = [c.strip() for c in line.split(",")]
        if len(cells) >= 3 and not cells[2]:
            continue  # a day before installation: date only
        if len(cells) < 10:
            bad += 1
            continue
        try:
            date = cells[1] if "-" in cells[1] else datetime.strptime(cells[1], "%m/%d/%Y").date().isoformat()
            below, above = minutes(cells[5]), minutes(cells[8])
            days.append({"date": date, "mean": float(cells[2]), "min": float(cells[4]), "max": float(cells[7]),
                         "low": [below, below > 0], "high": [above, above > 0]})
        except ValueError:
            bad += 1
    notes = [f"{bad} unreadable row(s) were skipped."] if bad else []
    return _daily(days, "C", {"low": 2.0, "high": 8.0}, "time below +2 C and above +8 C, as the fridge counts it", notes)
