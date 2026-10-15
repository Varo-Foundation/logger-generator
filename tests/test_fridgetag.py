"""Fridge-tag format invariants and a round trip from the text back to the simulation."""
from datetime import date, datetime, timedelta

import pytest

from fridgetag_text import outline
from logger_generator import fridgetag
from logger_generator.cli import main

HEADER_ORDER = ["Device", "Vers", "Fw Vers", "Sensor"]
CONF_ORDER = ["Serial", "PCB", "CID", "Lot", "Zone", "Measurement delay", "Moving Avrg", "User Alarm Config"]


def generate(tmp_path, *args):
    out = tmp_path / "ft"
    main(["fridgetag", *args, "--out", str(out)])
    txt = next(out.glob("*.txt"))
    return txt, txt.read_bytes()


@pytest.mark.parametrize("model", ["2", "2E", "2L"])
def test_crlf_ascii_and_field_order(tmp_path, model):
    path, data = generate(tmp_path, "--model", model)
    data.decode("ascii")
    assert data.endswith(b"\r\n") and data.count(b"\n") == data.count(b"\r\n")
    lines = data.decode().split("\r\n")
    assert [line.split(":")[0] for line in lines[:4]] == HEADER_ORDER
    conf = [line.strip().split(":")[0] for line in lines[lines.index("Conf:") + 1:][:8]]
    assert conf == CONF_ORDER
    top = [line.rstrip(":") for line in lines if line and not line.startswith(" ")]
    expected = HEADER_ORDER + (["Ext Sensor"] if model == "2L" else []) + ["Conf", "Hist", "Cert", "Sig Cert", "Sig"]
    assert [key.split(":")[0] for key in top] == expected
    tree = outline(data.decode())
    assert ("User Clock Config" in tree["Conf"]) == (model != "2")
    assert ("Ext Sensor" in tree["Conf"]) == (model == "2L")
    assert tree["Conf"]["Use ext devices"] == ("1" if model == "2L" else "0")


@pytest.mark.parametrize("scenario", list(fridgetag.SCENARIOS))
def test_round_trip_days_match_simulation(tmp_path, scenario):
    """Every day block agrees with the simulated summary and with the alarm rules."""
    if scenario == "damaged-truncated":
        pytest.skip("damaged on purpose")
    path, data = generate(tmp_path, "--scenario", scenario, "--seed", "5")
    tree = outline(data.decode())
    hist = tree["Hist"]
    days = [hist[str(i)] for i in range(1, 61)]
    assert str(61) not in hist
    dates = [date.fromisoformat(d["Date"]) for d in days]
    assert all(a - b == timedelta(days=1) for a, b in zip(dates, dates[1:])), "newest first, consecutive"
    unit_f = tree["Conf"]["Temp unit"] == "F"
    for d in days:
        lo, hi, mean = float(d["Min T"]), float(d["Max T"]), float(d["Avrg T"])
        assert lo <= mean <= hi
        for key in ("0", "1"):
            alarm = d["Alarm"][key]
            assert int(alarm["t Acc"]) >= 0
            if "TS A" in alarm:
                assert int(alarm["t Acc"]) > 0 and alarm["C A"] == "0"
        if not unit_f:
            limit = float(tree["Conf"]["Alarm"]["1"]["T AL"])
            assert (int(d["Alarm"]["1"]["t Acc"]) > 0) == (hi > limit)
    name_stamp = path.stem.split("_")[1]
    created = tree["Hist"]["TS Report Creation"]
    assert datetime.strptime(created, "%Y-%m-%d %H:%M").strftime("%Y%m%d%H%M") == name_stamp
    assert dates[0].isoformat() == created[:10]


def test_alarm_scenarios_trigger(tmp_path):
    expectations = {"heat-excursion": ("1", 1), "heat-across-midnight": ("1", 1), "freeze-event": ("0", 1),
                    "heat-no-alarm": ("1", 0), "normal": ("1", 0)}
    for scenario, (key, count) in expectations.items():
        for seed in (1, 2, 3):
            _, data = generate(tmp_path, "--scenario", scenario, "--seed", str(seed))
            hist = outline(data.decode())["Hist"]
            alarmed = [i for i in range(1, 61) if "TS A" in hist[str(i)]["Alarm"][key]]
            assert len(alarmed) == count, (scenario, seed)


def test_alarm_carried_across_midnight_shows_on_second_day(tmp_path):
    _, data = generate(tmp_path, "--scenario", "heat-across-midnight")
    hist = outline(data.decode())["Hist"]
    first, second = hist["7"]["Alarm"]["1"], hist["6"]["Alarm"]["1"]
    assert int(first["t Acc"]) > 0 and "TS A" not in first
    assert "TS A" in second and int(first["t Acc"]) + int(second["t Acc"]) >= 600


def test_fahrenheit_converts_limits_and_readings(tmp_path):
    _, data = generate(tmp_path, "--scenario", "fahrenheit")
    tree = outline(data.decode())
    assert tree["Conf"]["Temp unit"] == "F"
    assert tree["Conf"]["Alarm"]["0"]["T AL"] == "+31.1" and tree["Conf"]["Alarm"]["1"]["T AL"] == "+46.4"
    assert 35 < float(tree["Hist"]["1"]["Avrg T"]) < 46


def test_unset_clock_dates_count_from_2000(tmp_path):
    path, data = generate(tmp_path, "--scenario", "unset-clock")
    tree = outline(data.decode())
    assert tree["Hist"]["TS Actv"].startswith("2000-01-01")
    assert path.stem.split("_")[1].startswith("2000")
    assert tree["Hist"]["1"]["Date"].startswith("2000-")


def test_truncated_report_is_cut_inside_the_history(tmp_path):
    _, data = generate(tmp_path, "--scenario", "damaged-truncated")
    text = data.decode()
    assert "Hist:" in text and "Sig:" not in text and not text.endswith("\r\n")


def test_pdf_beside_text(tmp_path):
    path, _ = generate(tmp_path)
    pdf = path.with_suffix(".pdf").read_bytes()
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
