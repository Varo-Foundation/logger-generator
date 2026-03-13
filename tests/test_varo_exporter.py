"""Tests for the Varo exporter module."""

import datetime as dt
import re

import pytest

from utils.simulator import SimulatedRecordSet
from utils.simulator.config import SimulationConfig, default_config
from utils.schemas import EmsReport
from exporters.varo_exporter import (
    ems_report_to_varo,
    varo_filename,
    _seconds_to_relt,
    _map_alarm,
)


# Regex from Varo's RelativeTimestamp.kt
VARO_RELT_REGEX = re.compile(
    r"P(\d+D)?(T(\d+H)(\d+M)?(\d+S)?)"
    r"|P(\d+D)?(T(\d+H)?(\d+M)(\d+S)?)"
    r"|P(\d+D)?(T(\d+H)?(\d+M)?(\d+S))"
    r"|^P(\d+D)",
    re.IGNORECASE,
)


def _make_report(batch_size: int = 10, interval: int = 900) -> EmsReport:
    """Generate a small EmsReport for testing."""
    config = default_config(power_type="mains")
    config.random_seed = 42
    config.power.outage_probability_per_hour = 0.0

    start = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
    rs = SimulatedRecordSet.generate(config, batch_size, start, interval)
    ems_records = rs.to_ems(powersource="mains")

    return EmsReport(
        LSER="TEST001",
        LSV="v1.0",
        AMFR="TestMfr",
        AMOD="TestModel",
        ASER="TEST-A001",
        APQS="E003/001",
        LPQS="E006/001",
        ADOP=dt.date(2024, 1, 1),
        LDOP=dt.date(2024, 1, 1),
        LMFR="TestLogger",
        LMOD="TL-1000",
        EDOP=dt.date(2024, 1, 1),
        EMFR="TestLogger",
        EMOD="TL-EMD-1000",
        EPQS="E006/001",
        ESER="TEST-E001",
        EMSV="v1.0",
        CID="NG",
        records=ems_records,
    )


class TestReltFormat:
    """Verify RELT strings match Varo's RelativeTimestamp regex."""

    @pytest.mark.parametrize("seconds,expected", [
        (0, "P0DT0H0M0S"),
        (900, "P0DT0H15M0S"),
        (86400, "P1DT0H0M0S"),
        (90061, "P1DT1H1M1S"),
        (60 * 86400, "P60DT0H0M0S"),
    ])
    def test_relt_format_values(self, seconds, expected):
        assert _seconds_to_relt(seconds) == expected

    @pytest.mark.parametrize("seconds", [0, 900, 3600, 86400, 5184000])
    def test_relt_matches_varo_regex(self, seconds):
        relt = _seconds_to_relt(seconds)
        assert VARO_RELT_REGEX.match(relt), f"RELT '{relt}' doesn't match Varo regex"


class TestAlarmMapping:
    def test_none_alarm(self):
        assert _map_alarm(None) is None

    def test_heat_alarm(self):
        assert _map_alarm("HEAT") == "HEAT"

    def test_freeze_alarm(self):
        assert _map_alarm("FREEZE") == "FRZE"

    def test_unknown_passthrough(self):
        assert _map_alarm("UNKNOWN") == "UNKNOWN"


class TestVaroExport:
    """Verify the full export produces valid Varo JSON structure."""

    def test_top_level_keys(self):
        report = _make_report()
        varo = ems_report_to_varo(report)

        required_keys = {"LSER", "LSV", "AMFR", "AMOD", "ASER", "APQS", "LPQS", "ACAT", "records"}
        assert required_keys.issubset(varo.keys())

    def test_record_keys(self):
        report = _make_report()
        varo = ems_report_to_varo(report)

        record = varo["records"][0]
        expected_keys = {"RELT", "RTCW", "TVC", "TAMB", "SVA", "ACSV", "ACCD", "DORV", "CMPR", "BLOG", "ALRM", "LERR"}
        assert expected_keys.issubset(record.keys())

    def test_sva_range(self):
        """SVA must be in 0–900 range for 900s intervals."""
        report = _make_report(batch_size=100)
        varo = ems_report_to_varo(report, sample_interval=900)

        for rec in varo["records"]:
            assert 0 <= rec["SVA"] <= 900, f"SVA {rec['SVA']} out of range"

    def test_first_record_relt_is_zero(self):
        report = _make_report()
        varo = ems_report_to_varo(report)
        assert varo["records"][0]["RELT"] == "P0DT0H0M0S"

    def test_relt_is_monotonically_increasing(self):
        report = _make_report(batch_size=20)
        varo = ems_report_to_varo(report)

        relts = [r["RELT"] for r in varo["records"]]
        for i in range(1, len(relts)):
            assert relts[i] > relts[i - 1] or relts[i] != relts[i - 1]

    def test_all_relts_match_regex(self):
        report = _make_report(batch_size=50)
        varo = ems_report_to_varo(report)

        for rec in varo["records"]:
            assert VARO_RELT_REGEX.match(rec["RELT"]), \
                f"RELT '{rec['RELT']}' doesn't match Varo regex"
            assert VARO_RELT_REGEX.match(rec["RTCW"]), \
                f"RTCW '{rec['RTCW']}' doesn't match Varo regex"

    def test_no_freeze_alarm_code(self):
        """Varo uses FRZE, not FREEZE."""
        report = _make_report(batch_size=200)
        varo = ems_report_to_varo(report)

        for rec in varo["records"]:
            if rec["ALRM"] is not None:
                assert "FREEZE" not in rec["ALRM"], \
                    f"Found FREEZE alarm code — should be FRZE"

    def test_metadata_passthrough(self):
        report = _make_report()
        varo = ems_report_to_varo(report)

        assert varo["LSER"] == "TEST001"
        assert varo["AMFR"] == "TestMfr"
        assert varo["AMOD"] == "TestModel"


class TestFilename:
    def test_filename_format(self):
        name = varo_filename("SIM001", 60 * 86400)
        assert name == "SIM001_CURRENT_DATA_P60DT0H0M0S.json"

    def test_filename_matches_ems_device_pattern(self):
        """Filename must match EmsDevice.CURRENT_DATA_FILE_PATTERN regex."""
        pattern = re.compile(r"^([^._]*)_CURRENT_DATA_(P[A-Z0-9]+.*)\.json$", re.IGNORECASE)
        name = varo_filename("SIM001", 60 * 86400)
        assert pattern.match(name), f"Filename '{name}' doesn't match EmsDevice pattern"
