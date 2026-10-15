"""Haier HETL-01 CSV invariants, checked with the reading pattern Varo iOS parses with."""
import re
from datetime import datetime, timedelta

import pytest

from logger_generator.cli import main

# HaierParser.readingPattern in Packages/VaroCore/Sources/VaroCore/Haier/HaierReport.swift
READING = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2}):(\d{2})\s+(-?\d+(?:\.\d+)?)$")
HEADER = ["Note: All temperature are in degree ceslsius", "", "Device Information", "*" * 40, "Device:HETL-01",
          "Version: V1.0"]


def export(tmp_path, *args):
    out = tmp_path / "haier"
    main(["haier", *args, "--out", str(out)])
    (path,) = out.iterdir()
    return path, path.read_bytes()


def readings(text):
    lines = text.split("\r\n")
    start = next(i for i, line in enumerate(lines) if line.startswith("MM.DD.YYYY")) + 1
    return lines[:start], [line for line in lines[start:] if line]


@pytest.mark.parametrize("scenario,state", [("normal", "Normal"), ("heat-excursion", "High Alarm"),
                                            ("freeze-event", "Low Alarm"), ("room-temperature", "High Alarm")])
def test_layout_and_alarm_state(tmp_path, scenario, state):
    path, data = export(tmp_path, "--scenario", scenario)
    assert path.name == "HE09900000001.CSV"
    assert data.endswith(b"\r\n") and data.count(b"\n") == data.count(b"\r\n")
    header, rows = readings(data.decode("ascii"))
    assert header[:6] == HEADER
    assert "Serial Number:HE09900000001" in header and "Record Interval:  6 min" in header
    assert "Alarm Temperature High: +8  Delay 10 h" in header and "Alarm Temperature Low: -0.5 Delay 1 h" in header
    assert f"Alarm State: {state}" in header
    assert header[-1] == "MM.DD.YYYY  HH:MM:SS   T"
    times = []
    for row in rows:
        m = READING.match(row)
        assert m, row
        times.append(datetime(int(m[3]), int(m[1]), int(m[2]), int(m[4]), int(m[5]), int(m[6])))
    assert all(b - a == timedelta(minutes=6) for a, b in zip(times, times[1:]))
    assert len(rows) <= 8192 and times[-1] <= datetime(2026, 10, 15, 9, 20)


def test_damaged_lines_are_the_only_unparseable_ones(stories):
    path = next((stories["parser-edge-cases"] / "haier-damaged-lines").glob("*.CSV"))
    _, rows = readings(path.read_bytes().decode("ascii"))
    bad = [row for row in rows if not READING.match(row) or ".2225 " in row]
    assert len(bad) == 3


def test_capacity_is_enforced(tmp_path):
    with pytest.raises(SystemExit):
        export(tmp_path, "--days", "40")


def test_serial_must_look_like_haier(tmp_path):
    with pytest.raises(SystemExit):
        export(tmp_path, "--serial", "XX123")
