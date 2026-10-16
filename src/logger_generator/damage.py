"""Deliberately broken variants of generated files, for parser tests.

Each function takes the folder a generator just wrote and damages it in place, the way
files get damaged in the field (a USB stick pulled while copying, a logger with corrupted
flash, files copied by hand). They are deterministic: no randomness, fixed positions.
"""
import glob
import json
import os


def _one(folder, pattern):
    matches = sorted(glob.glob(os.path.join(folder, pattern)))
    if not matches:
        raise FileNotFoundError(f"no {pattern} in {folder}")
    return matches[0]


def _cut(path, fraction):
    with open(path, "rb") as f:
        data = f.read()
    with open(path, "wb") as f:
        f.write(data[:int(len(data) * fraction)])


def truncate_fridgetag(folder):
    """Cuts the Fridge-tag `.txt` at 55 % of its bytes (mid-line, inside the history)."""
    _cut(_one(folder, "*.txt"), 0.55)


def truncate_metafridge(folder):
    """Cuts the MetaFridge `.csv` at 55 % of its bytes (mid-row, inside the day rows)."""
    _cut(_one(folder, "*.csv"), 0.55)


def truncate_current(folder):
    """Cuts CURRENT_DATA at 60 % of its bytes: no closing brackets, a record cut in half."""
    _cut(_one(folder, "*_CURRENT_DATA_*.json"), 0.6)


def _rewrite_records(path, change):
    """Loads an EMS file, lets `change(records)` edit the list, writes it back in the same style."""
    from .ems import cjson  # late import: ems imports this module
    with open(path) as f:
        text = f.read()
    body = json.loads(text)
    records = body.pop("records")
    change(records)
    with open(path, "w") as f:
        if text.startswith("{\n\t"):
            f.write(cjson(list(body.items()), records))
        else:
            f.write(json.dumps(dict(body, records=records), separators=(",", ":")))


def invalid_relt(folder):
    """In CURRENT_DATA: record 10 gets hour 25 (`P74DT25H0M`), 20 a garbled `PXDT1H`, 30 an empty
    string and 40 no RELT at all."""
    def change(records):
        days = records[10]["RELT"].split("DT")[0]
        records[10]["RELT"] = f"{days}DT25H0M"
        records[20]["RELT"] = "PXDT1H"
        records[30]["RELT"] = ""
        del records[40]["RELT"]
    _rewrite_records(_one(folder, "*_CURRENT_DATA_*.json"), change)


def duplicate_records(folder):
    """In CURRENT_DATA: records 100-103 appear twice in a row (identical RELT and values)."""
    def change(records):
        records[104:104] = [dict(r) for r in records[100:104]]
    _rewrite_records(_one(folder, "*_CURRENT_DATA_*.json"), change)


def missing_sync(folder):
    """Removes the SYNC file."""
    os.remove(_one(folder, "*_SYNC_*.json"))


def history_case(folder):
    """Renames `DATA_HISTORY` to `data_history` (case-only rename, safe on case-insensitive disks)."""
    source = os.path.join(folder, "DATA_HISTORY")
    temporary = os.path.join(folder, "data_history.tmp")
    os.rename(source, temporary)
    os.rename(temporary, os.path.join(folder, "data_history"))


def haier_lines(folder):
    """In the Haier CSV: reading 50 gets the year 2225, reading 120 a garbled `2..9`
    temperature and reading 200 is cut off after the minutes."""
    path = _one(folder, "*.CSV")
    with open(path, newline="") as f:
        lines = f.read().split("\r\n")
    first = next(i for i, line in enumerate(lines) if line.startswith("MM.DD.YYYY")) + 1
    date, time, value = lines[first + 50].split()
    lines[first + 50] = f"{date[:6]}2225  {time}  {value}"
    date, time, _ = lines[first + 120].split()
    lines[first + 120] = f"{date}  {time}  2..9"
    lines[first + 200] = lines[first + 200][:17]
    with open(path, "w", newline="") as f:
        f.write("\r\n".join(lines))
