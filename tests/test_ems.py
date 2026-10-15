"""EMS drive invariants: valid JSON, record cadence, header and record fields, alarm rules,
SYNC content, history blocks and every damaged variant."""
import json
import re

import pytest

from logger_generator import ems
from logger_generator.cli import main
from logger_generator.util import parse_relt

HEADER_KEYS = ["ACAT", "ADOP", "AMFR", "AMOD", "APQS", "ASER", "CNAM", "CSER", "LDOP", "LMFR", "LMOD", "LPQS",
               "LSER", "LSV", "EDOP", "EMFR", "EMOD", "EPQS", "ESER", "EMSV"]
RECORD_KEYS = ["BLOG", "BEMD", "CMPR", "DORV", "DRCV", "RELT", "RTCW", "TAMB", "TVC", "SVA", "ACCD", "ACSV", "ALRM"]
ALARMS = {"HEAT", "FRZE", "DOOR", "POWR"}


def drive(tmp_path, *args, name="ems"):
    out = tmp_path / name
    main(["ems", *args, "--out", str(out)])
    return out


def load(path):
    return json.loads(path.read_text())


def records_of(out):
    history = sorted((out / "DATA_HISTORY").glob("*.json"), key=lambda p: parse_relt(p.stem.rsplit("_", 1)[1]))
    current = next(out.glob("*_CURRENT_DATA_*.json"))
    return [r for path in history + [current] for r in load(path)["records"]]


@pytest.fixture(scope="module")
def outage(tmp_path_factory):
    return drive(tmp_path_factory.mktemp("ems"), "--scenario", "power-outage")


def test_cjson_layout(outage):
    text = next(outage.glob("*_CURRENT_DATA_*.json")).read_text()
    assert text.startswith('{\n\t"ACAT":\t"RF03",\n') and "\n},{\n" in text and text.endswith("}]\n}")
    assert "\r" not in text


def test_header_and_record_fields(outage):
    body = load(next(outage.glob("*_CURRENT_DATA_*.json")))
    assert list(body)[:-1] == HEADER_KEYS and list(body)[-1] == "records"
    assert body["LSER"] == body["ASER"] + "EMS" == body["ESER"] + "EMS"
    for r in body["records"]:
        assert list(r) == RECORD_KEYS
        assert 0 <= r["SVA"] <= 900 and 0 <= r["CMPR"] <= 900 and 0 <= r["DORV"] <= 900
        assert r["ALRM"] is None or set(r["ALRM"].split()) <= ALARMS


def test_cadence_and_alarm_rules(outage):
    records = records_of(outage)
    times = [parse_relt(r["RELT"]) for r in records]
    assert times[0] == 900 and all(b - a == 900 for a, b in zip(times, times[1:]))
    heat_run = 0
    for r in records:
        alarms = set((r["ALRM"] or "").split())
        assert ("POWR" in alarms) == (r["SVA"] < 900)
        heat_run = heat_run + 1 if r["TVC"] > 8 else 0
        assert ("HEAT" in alarms) == (heat_run >= 40), r["RELT"]  # 10 h of 15-minute records
        if r["SVA"] == 0:
            assert r["ACSV"] == 0 and r["CMPR"] == 0
    kinds = {a for r in records for a in (r["ALRM"] or "").split()}
    assert {"HEAT", "POWR"} <= kinds


def test_sync_and_names(outage):
    sync = next(outage.glob("*_SYNC_*.json"))
    read = sync.stem.rsplit("_", 1)[1]
    assert re.fullmatch(r"P75DT2H13M37S", read)
    reading, last = load(sync)["records"]
    current = load(next(outage.glob("*_CURRENT_DATA_*.json")))["records"]
    assert reading == {"IDRV": 0, "RELT": read, "RTCW": "PT0S", "TVC": last["TVC"]} and last == current[-1]
    for path in outage.iterdir():
        if path.is_file():
            assert path.stem.rsplit("_", 1)[1] == read
    (history,) = (outage / "DATA_HISTORY").iterdir()
    assert history.name.endswith("_DATA_P60DT0H0M.json") and len(load(history)["records"]) == 5760


@pytest.mark.parametrize("days,blocks", [(50, 0), (75, 1), (150, 2)])
def test_history_blocks(tmp_path, days, blocks):
    out = drive(tmp_path, "--active-days", str(days), "--compact")
    names = sorted(p.name for p in (out / "DATA_HISTORY").iterdir())
    assert len(names) == blocks
    records = records_of(out)
    assert len(records) == (days * 24 + 2) * 4 + 0  # 02:13 into the last day: 8 full intervals
    assert len(load(next(out.glob("*_CURRENT_DATA_*.json")))["records"]) == len(records) - blocks * 5760


@pytest.mark.parametrize("scenario,expected", [
    ("normal", set()), ("short-outages", {"POWR"}), ("door-left-open", {"DOOR"}), ("heat-excursion", {"HEAT"}),
    ("freeze-event", {"FRZE"}), ("refrigerant-leak", {"HEAT"}), ("few-but-long", {"DOOR"}),
])
def test_scenario_alarms(tmp_path, scenario, expected):
    out = drive(tmp_path, "--scenario", scenario, "--compact")
    kinds = {a for r in records_of(out) for a in (r["ALRM"] or "").split()}
    assert kinds == expected


def test_compact_and_cjson_carry_the_same_data(tmp_path):
    a = drive(tmp_path, "--active-days", "61", name="a")
    b = drive(tmp_path, "--active-days", "61", "--compact", name="b")
    assert records_of(a) == records_of(b)
    assert next(b.glob("*_CURRENT_DATA_*.json")).read_text().startswith('{"ACAT":"RF03",')


def test_header_override(tmp_path):
    out = drive(tmp_path, "--active-days", "61", "--header", "LSV=v9", "--appliance-serial", "XY12")
    body = load(next(out.glob("*_CURRENT_DATA_*.json")))
    assert body["LSV"] == "v9" and body["LSER"] == "XY12EMS" and next(out.glob("XY12EMS_SYNC_*"))


def test_damaged_variants(stories):
    root = stories["parser-edge-cases"]
    with pytest.raises(json.JSONDecodeError):
        load(next((root / "ems-truncated-json").glob("*_CURRENT_DATA_*.json")))

    bad = load(next((root / "ems-invalid-relt").glob("*_CURRENT_DATA_*.json")))["records"]
    assert "RELT" not in bad[40]
    for i in (10, 20, 30):
        with pytest.raises(ValueError):
            seconds = parse_relt(bad[i]["RELT"])
            if bad[i]["RELT"].split("DT")[1].startswith("25H"):
                raise ValueError("hour 25")
            assert seconds

    dup = load(next((root / "ems-duplicate-records").glob("*_CURRENT_DATA_*.json")))["records"]
    relts = [r["RELT"] for r in dup]
    assert len(relts) - len(set(relts)) == 4 and relts[100:104] == relts[104:108]

    assert not list((root / "ems-missing-sync").glob("*_SYNC_*"))
    names = {p.name for p in (root / "ems-history-case").iterdir()}
    assert "data_history" in names and "DATA_HISTORY" not in names


def test_demo_drives_use_the_simple_layout(stories):
    for name, serial in (("demo-ems", "SAMPLE-EMS-0001"), ("demo-ems-alarm", "SAMPLE-EMS-0002")):
        out = stories[name]
        body = load(out / f"{serial}_CURRENT_DATA_P140DT0H1M1S.json")
        assert body["LSER"] == serial and {"HOLD", "LERR"} <= set(body["records"][0])
        assert (out / "DATA_HISTORY" / f"{serial}_DATA_P110DT0H0M0S.json").exists()
    kinds = {a for r in records_of(stories["demo-ems-alarm"]) for a in r.get("ALRM", "").split()}
    assert kinds == ALARMS


def test_door_patterns_differ_in_openings(tmp_path):
    counts = {}
    for pattern in ("best-practice", "busy"):
        out = drive(tmp_path, "--active-days", "61", "--door", pattern, "--compact", name=pattern)
        counts[pattern] = sum(r["DRCV"] for r in records_of(out)) / 61
    assert counts["best-practice"] < 3 < 12 < counts["busy"]
    assert set(ems.DOOR_PATTERNS) >= {"best-practice", "normal", "frequent-short", "busy", "few-but-long"}
