"""
Varo Exporter: converts EmsReport → Varo RawEmsData JSON format.

The Varo Android app reads EMS data from USB sticks with a flat JSON
structure that differs from the CCDX EmsReport format:

  - Timestamps are ISO 8601 durations (RELT) relative to the first record,
    not absolute datetimes (ABST).
  - Device metadata lives at the root level (no nested wrappers).
  - Alarm codes use abbreviated forms: FRZE/HEAT (not FREEZE).
  - SVA = per-interval powered seconds (0–900), not nominal voltage.
"""

import datetime as dt
import json
from typing import Any

from utils.schemas import EmsReport


# Map simulator alarm strings → Varo alarm codes
_ALARM_MAP = {
    "HEAT": "HEAT",
    "FREEZE": "FRZE",
}


def _seconds_to_relt(total_seconds: float) -> str:
    """Convert seconds to Varo RELT format: P{d}DT{h}H{m}M{s}S.

    Always includes all components to match RelativeTimestamp.kt init block:
      P${days}DT${hours}H${minutes}M${seconds}S
    """
    total = int(round(total_seconds))
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"P{days}DT{hours}H{minutes}M{seconds}S"


def _map_alarm(alarm: str | None) -> str | None:
    """Map simulator alarm codes to Varo format."""
    if alarm is None:
        return None
    return _ALARM_MAP.get(alarm, alarm)


def ems_report_to_varo(
    report: EmsReport,
    rtc_drift_seconds: float = 3 * 86400,
    sample_interval: int = 900,
) -> dict[str, Any]:
    """Convert an EmsReport to Varo RawEmsData dict.

    Args:
        report: The simulator EmsReport to convert.
        rtc_drift_seconds: Offset subtracted from RELT to produce RTCW,
            simulating real-time clock drift. Default: 3 days.
        sample_interval: Expected sample interval in seconds (for SVA cap).

    Returns:
        Dict matching the Varo RawEmsData JSON structure.
    """
    records = report.records
    if not records:
        return _build_metadata(report, [])

    # Get the first timestamp as the reference point
    first_abst = records[0].ABST

    varo_records = []
    for rec in records:
        # Compute elapsed seconds from first record
        elapsed = (rec.ABST - first_abst).total_seconds()

        relt = _seconds_to_relt(elapsed)
        rtcw_seconds = max(0, elapsed - rtc_drift_seconds)
        rtcw = _seconds_to_relt(rtcw_seconds)

        # SVA: per-interval powered seconds (0–sample_interval)
        # Simulator's ACCD is per-interval powered seconds
        accd = getattr(rec, 'ACCD', None)
        if accd is not None:
            sva = min(int(round(accd)), sample_interval)
        else:
            sva = sample_interval  # assume full power if no data

        varo_rec: dict[str, Any] = {
            "RELT": relt,
            "RTCW": rtcw,
            "TVC": round(rec.TVC, 1),
            "TAMB": round(rec.TAMB, 1),
            "SVA": sva,
            "ACSV": round(getattr(rec, 'ACSV', 0.0), 1),
            "ACCD": round(accd, 1) if accd is not None else 0.0,
            "DORV": rec.DORV,
            "CMPR": rec.CMPR,
            "BLOG": round(rec.BLOG, 1),
            "ALRM": _map_alarm(rec.ALRM),
            "LERR": getattr(rec, 'LERR', None),
        }
        varo_records.append(varo_rec)

    return _build_metadata(report, varo_records)


def _build_metadata(report: EmsReport, records: list[dict]) -> dict[str, Any]:
    """Build the top-level Varo RawEmsData dict with device metadata."""
    return {
        "LSER": report.LSER,
        "LSV": report.LSV,
        "AMFR": report.AMFR,
        "AMOD": report.AMOD,
        "ASER": report.ASER,
        "APQS": report.APQS,
        "LPQS": report.LPQS,
        "ACAT": report.ACAT or "RF",
        "records": records,
    }


def varo_filename(lser: str, total_duration_seconds: float) -> str:
    """Generate filename matching EmsDevice.CURRENT_DATA_FILE_PATTERN.

    Format: {LSER}_CURRENT_DATA_P{duration}.json
    """
    duration = _seconds_to_relt(total_duration_seconds)
    return f"{lser}_CURRENT_DATA_{duration}.json"


def export_varo_json(
    report: EmsReport,
    output_path: str,
    sample_interval: int = 900,
    downsample_factor: int = 1,
) -> str:
    """Export an EmsReport as Varo-compatible JSON file.

    Args:
        report: The EmsReport to export.
        output_path: Directory to write the output file.
        sample_interval: Sample interval in seconds.
        downsample_factor: Take every Nth record to reduce file size.

    Returns:
        Path to the written file.
    """
    varo_data = ems_report_to_varo(report, sample_interval=sample_interval)

    # Downsample if requested
    if downsample_factor > 1:
        varo_data["records"] = varo_data["records"][::downsample_factor]

    # Compute total duration from last record
    if varo_data["records"]:
        last_relt = varo_data["records"][-1]["RELT"]
        filename = f"{varo_data['LSER']}_CURRENT_DATA_{last_relt}.json"
    else:
        filename = f"{varo_data['LSER']}_CURRENT_DATA_P0DT0H0M0S.json"

    import os
    filepath = os.path.join(output_path, filename)
    with open(filepath, 'w') as f:
        json.dump(varo_data, f, indent=2)

    return filepath
