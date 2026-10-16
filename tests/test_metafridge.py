"""MetaFridge CFD-50 30 DTR invariants, read the way Varo Android and iOS parse the CSV.

Android (`data/parser/metafridge/MetaFridgeParser.kt`) skips the title, takes the serial from
the second line's third column, skips three more lines and parses every following row with
`yyyy-MM-dd` dates and `hh:mm` durations, dropping rows that fail. iOS
(`Packages/VaroCore/Sources/VaroCore/MetaFridge/MetaFridgeReport.swift`) finds the `DayNum,`
header and also accepts `M/d/yyyy` dates and `h:mm:ss` durations.
"""
import re
from datetime import date, datetime

import pytest

from logger_generator.cli import main

ANDROID_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DURATION = re.compile(r"^(\d+):(\d{2})(?::(\d{2}))?$")


def report(tmp_path, *args):
    out = tmp_path / "metafridge"
    main(["metafridge", *args, "--out", str(out)])
    csv = next(out.glob("*.csv"))
    assert sorted(p.name for p in out.iterdir()) == [csv.name, csv.stem + ".pdf"]
    return csv, csv.read_bytes()


def minutes(text):
    m = DURATION.match(text)
    assert m, text
    return int(m[1]) * 60 + int(m[2])


def android_rows(text):
    """Android's reading: serial from line 2, rows from line 6, unparseable rows dropped."""
    lines = text.splitlines()
    serial = lines[1].split(",")[2]
    rows = []
    for line in lines[5:]:
        cells = line.split(",")
        if ANDROID_DATE.match(cells[1]) and cells[2].strip():
            rows.append(cells)
    return serial, rows


@pytest.mark.parametrize("scenario,alarm_days", [("normal", 0), ("heat-excursion", 1), ("freeze-event", 1),
                                                 ("cloudy-week", 0), ("not-cooling", 60)])
def test_current_layout(tmp_path, scenario, alarm_days):
    path, data = report(tmp_path, "--scenario", scenario)
    assert path.name == "99S-0001_20260817_20261015.csv"
    assert data.startswith(b"\xef\xbb\xbfCFD50 30 DTR REPORT\r\n")
    assert data.endswith(b"\r\n") and data.count(b"\n") == data.count(b"\r\n")
    text = data.decode("utf-8-sig")
    lines = text.split("\r\n")
    assert lines[1:4] == ["Fridge Serial Number:, ,99S-0001", "Report Creation Date:, ,2026-10-15",
                          "Report Creation Time:, ,09:20:00"]
    assert lines[4].startswith("DayNum,Date,Average Temperature (°C),Status,") and lines[4].endswith(",Faults")
    serial, rows = android_rows(text)
    assert serial == "99S-0001" and len(rows) == 60
    assert [r[0] for r in rows] == [f"{n:02d}" for n in range(1, 61)]
    assert rows[0][1] == "2026-10-15" and rows[-1][1] == "2026-08-17"
    alarms = 0
    for r in rows:
        assert len(r) == 14
        mean, low, high = float(r[2]), float(r[4]), float(r[7])
        assert low <= mean <= high
        below, low_alarm, above, high_alarm = (minutes(r[i]) for i in (5, 6, 8, 9))
        assert below == low_alarm and above == high_alarm and below + above <= 1440
        assert (below > 0) == (low < 2.0) and (above > 0) == (high > 8.0)
        assert r[3] == ("ALARM" if below or above else "OK")
        alarms += r[3] == "ALARM"
    assert alarms == alarm_days
    assert minutes(rows[0][9]) <= 9 * 60 + 20  # the report day only runs to its creation time


def test_not_cooling_has_no_power_or_holdover(tmp_path):
    _, data = report(tmp_path, "--scenario", "not-cooling")
    _, rows = android_rows(data.decode("utf-8-sig"))
    assert {(r[10], r[11], r[12]) for r in rows} == {("0", "", "0.0")}
    assert all(r[8] == "24:00" for r in rows[1:])


def test_cloudy_week_lowers_power_and_holdover(tmp_path):
    _, data = report(tmp_path, "--scenario", "cloudy-week")
    _, rows = android_rows(data.decode("utf-8-sig"))
    cloudy = [r for r in rows if r[0] in ("08", "09", "10")]
    clear = [r for r in rows if r[0] not in ("08", "09", "10")]
    assert max(float(r[12]) for r in cloudy) < min(float(r[12]) for r in clear)
    assert max(float(r[11]) for r in cloudy) < min(float(r[11]) for r in clear)


def test_recently_installed_keeps_blank_rows(tmp_path):
    _, data = report(tmp_path, "--scenario", "recently-installed")
    lines = data.decode("utf-8-sig").split("\r\n")
    assert lines[5 + 59] == "60,2026-08-17, , , , , , , , , , , ,"
    _, rows = android_rows("\n".join(lines))
    assert len(rows) == 28


def test_legacy_layout(tmp_path):
    _, data = report(tmp_path, "--scenario", "legacy-layout")
    assert not data.startswith(b"\xef\xbb\xbf") and b"\r" not in data and data.endswith(b"\n")
    lines = data.decode("utf-8").split("\n")[:-1]
    assert lines[:4] == ["CFD50 30 DTR REPORT,,,,,,,,,", "Fridge Serial Number:, ,,,,,,,,",
                         "Report Creation Date:, ,10/15/2026,,,,,,,", "Report Creation Time:, ,09:20:00,,,,,,,"]
    assert lines[4].endswith("Total High Alarm Time (hh:mm)") and lines[4].count(",") == 9
    rows = [line.split(",") for line in lines[5:]]
    assert len(rows) == 60 and all(len(r) == 10 for r in rows)
    assert rows[0][:2] == ["1", "10/15/2026"] and rows[-1][:2] == ["60", "8/17/2026"]
    for r in rows:
        datetime.strptime(r[1], "%m/%d/%Y")
        assert all(DURATION.match(r[i]) and not r[i].startswith("0") or r[i] == "0:00" for i in (5, 6, 8, 9))


def test_legacy_whole_days_are_24_00_00(tmp_path):
    _, data = report(tmp_path, "--scenario", "not-cooling", "--legacy")
    rows = [line.split(",") for line in data.decode("utf-8").split("\n")[5:-1]]
    assert all(r[8] == "24:00:00" for r in rows[1:])


def test_truncated_csv_keeps_the_pdf(stories):
    folder = stories["parser-edge-cases"] / "metafridge-truncated"
    csv = next(folder.glob("*.csv"))
    assert (folder / (csv.stem + ".pdf")).exists()
    _, rows = android_rows(csv.read_bytes().decode("utf-8-sig"))
    assert 0 < len(rows) < 60


def test_window_and_file_name_follow_the_options(tmp_path):
    path, data = report(tmp_path, "--days", "30", "--created", "2026-03-02T17:05:09", "--serial", "12A-3456")
    assert path.name == "12A-3456_20260201_20260302.csv"
    serial, rows = android_rows(data.decode("utf-8-sig"))
    assert serial == "12A-3456" and len(rows) == 30 and rows[-1][1] == date(2026, 2, 1).isoformat()


def test_serial_must_fit_the_file_name_pattern(tmp_path):
    with pytest.raises(SystemExit):
        report(tmp_path, "--serial", "bad serial")


def test_active_days_must_fit_the_window(tmp_path):
    with pytest.raises(SystemExit):
        report(tmp_path, "--active-days", "61")
