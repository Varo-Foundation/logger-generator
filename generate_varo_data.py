#!/usr/bin/env python3
"""
Generate Varo-compatible EMS fixture data using physics-based simulation.

Usage:
    python generate_varo_data.py --scenario normal --days 60 --output ./output/
    python generate_varo_data.py --scenario heat_alarm --days 60 --output ./output/
    python generate_varo_data.py --scenario freeze_alarm --days 60 --output ./output/
    python generate_varo_data.py --scenario power_outage --days 60 --output ./output/
    python generate_varo_data.py --all --days 60 --output ./output/
"""

import argparse
import datetime as dt
import os
import sys

from utils.simulator import SimulatedRecordSet, SimulatorState
from utils.simulator.config import (
    SimulationConfig,
    ThermalConfig,
    AmbientConfig,
    PowerConfig,
    EventConfig,
    FaultConfig,
    FaultType,
    default_config,
)
from utils.schemas import EmsReport
from exporters.varo_exporter import export_varo_json


# Serial numbers for each scenario
SCENARIO_SERIALS = {
    "normal": "SIM001",
    "heat_alarm": "SIM002",
    "freeze_alarm": "SIM003",
    "power_outage": "SIM004",
    "outage_and_door_event": "SIM005",
    "heat_wave": "SIM006",
    "refrigerant_leak": "SIM007",
    "bad_week": "SIM008",
}


def _base_config(seed: int = 42) -> SimulationConfig:
    """Stable mains-powered fridge baseline.

    Uses a direct-cool model (no icebank) so that door openings visibly
    affect TVC — busy immunization days show higher average temperatures.
    Weekly door rate modulation creates a realistic clinic pattern:
    busy Mon/Wed, normal Tue/Thu, quiet Fri, minimal Sat/Sun.
    """
    config = default_config(power_type="mains")
    config.random_seed = seed
    # Reduce outage probability for normal scenario
    config.power.outage_probability_per_hour = 0.0
    # Disable icebank — direct-cool fridge so door effects are visible
    config.thermal.icebank_capacity_j = 0.0
    config.thermal.compressor_targets_icebank = False
    # Direct-cool thermal params: good insulation (walls don't dominate),
    # moderate compressor (can maintain band but doors cause visible bumps)
    config.thermal.R = 0.50          # Good insulation (K/W) — wall leak ~46W
    config.thermal.C = 12000.0       # Moderate thermal mass (J/K)
    config.thermal.Q_compressor = 100.0  # Moderate cooling (W) — ~54W surplus
    config.thermal.R_door = 0.06     # Leaky door (K/W) — ~383W per open
    # Weekly clinic pattern: busy immunization days (Mon/Wed), quiet weekends
    #                        Mon  Tue  Wed  Thu  Fri  Sat  Sun
    config.events.weekly_rate_modulation = (2.0, 1.0, 2.2, 1.0, 0.7, 0.2, 0.1)
    config.events.door_rate_per_hour = 2.5  # Moderate base rate
    config.events.door_mean_duration_s = 40.0  # Vaccine retrieval duration
    return config


def scenario_normal(days: int, interval: int) -> tuple[EmsReport, SimulationConfig]:
    """Stable 2–8°C, mains power, normal door activity."""
    config = _base_config(seed=42)
    return _run_simulation(config, days, interval, SCENARIO_SERIALS["normal"])


def scenario_heat_alarm(days: int, interval: int) -> tuple[EmsReport, SimulationConfig]:
    """Compressor failure at day 40, temp rises above 8°C, ALRM=HEAT."""
    config = _base_config(seed=43)
    config.fault = FaultConfig(
        fault_type=FaultType.COMPRESSOR_FAILURE,
        fault_start_offset_s=40 * 86400,  # day 40
        fault_duration_s=0,  # permanent
    )
    return _run_simulation(config, days, interval, SCENARIO_SERIALS["heat_alarm"])


def scenario_freeze_alarm(days: int, interval: int) -> tuple[EmsReport, SimulationConfig]:
    """Thermostat fault — temp drops below 2°C at day 30.

    Simulated by lowering setpoints and disabling the icebank so the
    compressor directly overcools the chamber.
    """
    # Phase 1: normal operation for 30 days
    normal_config = _base_config(seed=44)
    batch_normal = (30 * 86400) // interval
    batch_fault = ((days - 30) * 86400) // interval

    start = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
    rs1 = SimulatedRecordSet.generate(normal_config, batch_normal, start, interval)

    # Phase 2: thermostat fault — compressor overcools
    fault_config = _base_config(seed=44)
    fault_config.thermal.T_setpoint_low = -10.0
    fault_config.thermal.T_setpoint_high = -5.0
    # Disable icebank so compressor cools chamber directly
    fault_config.thermal.icebank_capacity_j = 0.0
    fault_config.thermal.compressor_targets_icebank = False
    # Increase cooling power to drive temp down faster
    fault_config.thermal.Q_compressor = 200.0

    fault_start = start + dt.timedelta(seconds=batch_normal * interval)
    rs2 = SimulatedRecordSet.generate(fault_config, batch_fault, fault_start, interval, state=rs1.state)

    all_records = rs1.records + rs2.records
    ems_records = [_to_ems_record_mains(r) for r in all_records]

    report = _build_report(ems_records, SCENARIO_SERIALS["freeze_alarm"])
    return report, fault_config


def scenario_power_outage(days: int, interval: int) -> tuple[EmsReport, SimulationConfig]:
    """Two multi-day power outages: days 20–25, days 45–50.

    Forces the power model into outage state for outage segments so that
    SVA=0 and ACCD=0 during those periods.
    """
    lser = SCENARIO_SERIALS["power_outage"]
    start = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)

    # Run in segments: normal → outage1 → normal → outage2 → normal
    segments = [
        (0, 20, False),
        (20, 25, True),
        (25, 45, False),
        (45, 50, True),
        (50, days, False),
    ]

    all_records = []
    state = None

    for seg_start_day, seg_end_day, is_outage in segments:
        seg_days = seg_end_day - seg_start_day
        if seg_days <= 0:
            continue
        batch_size = (seg_days * 86400) // interval

        seg_config = _base_config(seed=45)

        if is_outage:
            # Force power model into permanent outage by using fault injection
            # AND setting the power state to in_outage so SVA/ACCD reflect it
            seg_config.fault = FaultConfig(
                fault_type=FaultType.POWER_OUTAGE,
                fault_start_offset_s=0,
                fault_duration_s=0,  # entire segment
            )
            # Force the power model's state into outage
            if state is not None:
                state._power_in_outage = True
                state._power_outage_end = (
                    start + dt.timedelta(days=seg_end_day + 1)  # past end of segment
                )
            else:
                state = SimulatorState()
                state._power_in_outage = True
                state._power_outage_end = start + dt.timedelta(days=seg_end_day + 1)
        else:
            # Ensure we exit outage state for normal segments
            if state is not None:
                state._power_in_outage = False
                state._power_outage_end = None

        seg_start = start + dt.timedelta(days=seg_start_day)
        rs = SimulatedRecordSet.generate(seg_config, batch_size, seg_start, interval, state=state)
        all_records.extend(rs.records)
        state = rs.state

    ems_records = [_to_ems_record_mains(r) for r in all_records]
    report = _build_report(ems_records, lser)
    return report, _base_config(seed=45)


def scenario_outage_and_door_event(days: int, interval: int) -> tuple[EmsReport, SimulationConfig]:
    """Demo: two distinct anomalies on one chart.

    13-day window (in seconds; assembled segment-by-segment with carried state):
      S1: 2.0d outage (POWER_OUTAGE + forced _power_in_outage) — opens with drama
      S2: 4.0d normal recovery — compressor pulls TVC back into band
      S3: 3.0d normal baseline
      S4: 0.5d STUCK_DOOR — door bar saturates, TVC spikes
      S5: 3.5d normal recovery — TVC returns to band
    Story: 'outage hit, we recovered. Then someone left the door open, temp
    spiked, we recovered again.'
    """
    lser = SCENARIO_SERIALS["outage_and_door_event"]
    start = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)

    # (start_seconds, end_seconds, fault_kind) where fault_kind is None, "outage", or "stuck_door"
    DAY = 86400
    segments = [
        (0,             2 * DAY,              "outage"),
        (2 * DAY,       6 * DAY,              None),
        (6 * DAY,       9 * DAY,              None),
        (9 * DAY,       9 * DAY + DAY // 2,   "stuck_door"),
        (9 * DAY + DAY // 2, days * DAY,      None),
    ]

    all_records = []
    state = None

    for seg_start_s, seg_end_s, fault_kind in segments:
        seg_seconds = seg_end_s - seg_start_s
        if seg_seconds <= 0:
            continue
        batch_size = seg_seconds // interval

        seg_config = _base_config(seed=46)

        if fault_kind == "outage":
            seg_config.fault = FaultConfig(
                fault_type=FaultType.POWER_OUTAGE,
                fault_start_offset_s=0,
                fault_duration_s=0,  # whole segment
            )
            if state is None:
                state = SimulatorState()
            state._power_in_outage = True
            state._power_outage_end = start + dt.timedelta(seconds=seg_end_s + DAY)
        elif fault_kind == "stuck_door":
            seg_config.fault = FaultConfig(
                fault_type=FaultType.STUCK_DOOR,
                fault_start_offset_s=0,
                fault_duration_s=0,  # whole segment
            )
            if state is not None:
                state._power_in_outage = False
                state._power_outage_end = None
        else:
            if state is not None:
                state._power_in_outage = False
                state._power_outage_end = None

        seg_start_dt = start + dt.timedelta(seconds=seg_start_s)
        rs = SimulatedRecordSet.generate(seg_config, batch_size, seg_start_dt, interval, state=state)
        all_records.extend(rs.records)
        state = rs.state

    ems_records = [_to_ems_record_mains(r) for r in all_records]
    report = _build_report(ems_records, lser)
    return report, _base_config(seed=46)


def scenario_heat_wave(days: int, interval: int) -> tuple[EmsReport, SimulationConfig]:
    """Demo: extreme ambient heat wave — compressor stressed but in-spec.

    13-day window stitched as 3 segments:
      S1: 4d normal ambient (T_mean=28)
      S2: 4d heat wave (T_mean=38, T_amplitude=6) — TVC sawtooth tightens
      S3: 5d cool-down back to normal
    No fault is injected; the compressor copes with hotter ambient by running
    more aggressively, so TVC stays inside the 2–8°C band but the sawtooth
    pattern visibly tightens during the middle window. Story: 'extreme heat
    day, compressor handled it.'
    """
    lser = SCENARIO_SERIALS["heat_wave"]
    start = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)

    DAY = 86400
    segments = [
        (0,         4 * DAY,  None),
        (4 * DAY,   8 * DAY,  "heat"),
        (8 * DAY,   days * DAY, None),
    ]

    all_records = []
    state = None

    for seg_start_s, seg_end_s, kind in segments:
        seg_seconds = seg_end_s - seg_start_s
        if seg_seconds <= 0:
            continue
        batch_size = seg_seconds // interval

        seg_config = _base_config(seed=47)
        if kind == "heat":
            seg_config.ambient.T_mean = 38.0
            seg_config.ambient.T_amplitude = 6.0

        seg_start_dt = start + dt.timedelta(seconds=seg_start_s)
        rs = SimulatedRecordSet.generate(seg_config, batch_size, seg_start_dt, interval, state=state)
        all_records.extend(rs.records)
        state = rs.state

    ems_records = [_to_ems_record_mains(r) for r in all_records]
    report = _build_report(ems_records, lser)
    return report, _base_config(seed=47)


def scenario_refrigerant_leak(days: int, interval: int) -> tuple[EmsReport, SimulationConfig]:
    """Demo: subtle refrigerant leak with gradual creep into HEAT alarm.

    13-day window. 3d normal, then a single 10d segment with REFRIGERANT_LEAK
    at ~0.5%/hr — compressor cooling capacity decays linearly, TVC drifts
    upward over the back half of the chart and eventually crosses the alarm
    band. Story: 'subtle creep that single-day reading would miss.'
    """
    lser = SCENARIO_SERIALS["refrigerant_leak"]
    start = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)

    DAY = 86400

    # S1: 3d normal
    normal_cfg = _base_config(seed=48)
    n1 = 3 * DAY // interval
    rs1 = SimulatedRecordSet.generate(normal_cfg, n1, start, interval)

    # S2: 10d refrigerant leak
    leak_cfg = _base_config(seed=48)
    leak_cfg.fault = FaultConfig(
        fault_type=FaultType.REFRIGERANT_LEAK,
        fault_start_offset_s=0,
        fault_duration_s=0,  # permanent for the segment
        refrigerant_leak_rate=0.005,  # 0.5% / hr of Q_compressor lost
    )
    n2 = (days - 3) * DAY // interval
    leak_start = start + dt.timedelta(days=3)
    rs2 = SimulatedRecordSet.generate(leak_cfg, n2, leak_start, interval, state=rs1.state)

    all_records = rs1.records + rs2.records
    ems_records = [_to_ems_record_mains(r) for r in all_records]
    report = _build_report(ems_records, lser)
    return report, leak_cfg


def scenario_bad_week(days: int, interval: int) -> tuple[EmsReport, SimulationConfig]:
    """Demo: 'bad week' — small individually-benign events that add up.

    13-day timeline with brief outages and a stuck door, none of them dramatic
    on their own but the chart makes the pattern visible:
      normal 2d → 6h outage → normal 2.5d → 3h stuck door → normal 2.5d
      → 6h outage → normal ~5.375d.
    Story: 'multiple small events on one chart — easy to miss individually,
    obvious in aggregate.'
    """
    lser = SCENARIO_SERIALS["bad_week"]
    start = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)

    DAY = 86400
    HOUR = 3600

    segments = [
        (0,                                            2 * DAY,                     None),
        (2 * DAY,                                      2 * DAY + 6 * HOUR,          "outage"),
        (2 * DAY + 6 * HOUR,                           2 * DAY + 6 * HOUR + int(2.5 * DAY), None),
        (2 * DAY + 6 * HOUR + int(2.5 * DAY),          2 * DAY + 9 * HOUR + int(2.5 * DAY), "stuck_door"),
        (2 * DAY + 9 * HOUR + int(2.5 * DAY),          2 * DAY + 9 * HOUR + int(5.0 * DAY), None),
        (2 * DAY + 9 * HOUR + int(5.0 * DAY),          2 * DAY + 15 * HOUR + int(5.0 * DAY), "outage"),
        (2 * DAY + 15 * HOUR + int(5.0 * DAY),         days * DAY,                  None),
    ]

    all_records = []
    state = None

    for seg_start_s, seg_end_s, fault_kind in segments:
        seg_seconds = seg_end_s - seg_start_s
        if seg_seconds <= 0:
            continue
        batch_size = seg_seconds // interval

        seg_config = _base_config(seed=49)

        if fault_kind == "outage":
            seg_config.fault = FaultConfig(
                fault_type=FaultType.POWER_OUTAGE,
                fault_start_offset_s=0,
                fault_duration_s=0,
            )
            if state is None:
                state = SimulatorState()
            state._power_in_outage = True
            state._power_outage_end = start + dt.timedelta(seconds=seg_end_s + DAY)
        elif fault_kind == "stuck_door":
            seg_config.fault = FaultConfig(
                fault_type=FaultType.STUCK_DOOR,
                fault_start_offset_s=0,
                fault_duration_s=0,
            )
            if state is not None:
                state._power_in_outage = False
                state._power_outage_end = None
        else:
            if state is not None:
                state._power_in_outage = False
                state._power_outage_end = None

        seg_start_dt = start + dt.timedelta(seconds=seg_start_s)
        rs = SimulatedRecordSet.generate(seg_config, batch_size, seg_start_dt, interval, state=state)
        all_records.extend(rs.records)
        state = rs.state

    ems_records = [_to_ems_record_mains(r) for r in all_records]
    report = _build_report(ems_records, lser)
    return report, _base_config(seed=49)


def _to_ems_record_mains(record: dict):
    """Convert a raw simulation record dict to EmsRecordMains."""
    from utils.schemas import EmsRecordMains

    fields = [
        'ABST', 'ALRM', 'BEMD', 'BLOG', 'CMPR', 'DORV',
        'HAMB', 'HOLD', 'TAMB', 'TCON', 'TVC',
        'ACCD', 'ACSV', 'SVA',
    ]
    filtered = {}
    for k in fields:
        if k in record:
            filtered[k] = record[k]
    # Map EERR to LERR
    if 'EERR' in record and record['EERR'] is not None:
        filtered['LERR'] = record['EERR']

    return EmsRecordMains(**filtered)


def _build_report(ems_records: list, lser: str) -> EmsReport:
    """Build an EmsReport with standard device metadata."""
    return EmsReport(
        LSER=lser,
        LSV="v1.0",
        AMFR="Aucma",
        AMOD="MetaFridge CF-25D",
        ASER=f"SIM-A{lser[-3:]}",
        APQS="E003/001",
        LPQS="E006/001",
        ACAT="RF",
        ADOP=dt.date(2024, 1, 1),
        LDOP=dt.date(2024, 1, 1),
        LMFR="SimLogger",
        LMOD="SIM-1000",
        EDOP=dt.date(2024, 1, 1),
        EMFR="SimLogger",
        EMOD="SIM-EMD-1000",
        EPQS="E006/001",
        ESER=f"SIM-E{lser[-3:]}",
        EMSV="v1.0",
        CID="NG",
        records=ems_records,
    )


def _run_simulation(
    config: SimulationConfig,
    days: int,
    interval: int,
    lser: str,
) -> tuple[EmsReport, SimulationConfig]:
    """Run simulation and build an EmsReport."""
    batch_size = (days * 86400) // interval
    start = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)

    rs = SimulatedRecordSet.generate(config, batch_size, start, interval)
    ems_records = rs.to_ems(powersource="mains")

    report = _build_report(ems_records, lser)
    return report, config


SCENARIOS = {
    "normal": scenario_normal,
    "heat_alarm": scenario_heat_alarm,
    "freeze_alarm": scenario_freeze_alarm,
    "power_outage": scenario_power_outage,
    "outage_and_door_event": scenario_outage_and_door_event,
    "heat_wave": scenario_heat_wave,
    "refrigerant_leak": scenario_refrigerant_leak,
    "bad_week": scenario_bad_week,
}


def main():
    parser = argparse.ArgumentParser(
        description="Generate Varo-compatible EMS fixture data."
    )
    parser.add_argument(
        "--scenario",
        choices=list(SCENARIOS.keys()),
        help="Scenario to generate.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate all scenarios.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=60,
        help="Number of days to simulate (default: 60).",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=900,
        help="Sample interval in seconds (default: 900).",
    )
    parser.add_argument(
        "--downsample",
        type=int,
        default=1,
        help="Take every Nth record (default: 1, no downsampling).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="./output/",
        help="Output directory (default: ./output/).",
    )

    args = parser.parse_args()

    if not args.scenario and not args.all:
        parser.error("Specify --scenario or --all")

    os.makedirs(args.output, exist_ok=True)

    scenarios_to_run = list(SCENARIOS.keys()) if args.all else [args.scenario]

    for name in scenarios_to_run:
        print(f"Generating scenario: {name}...")
        report, config = SCENARIOS[name](args.days, args.interval)
        filepath = export_varo_json(
            report,
            args.output,
            sample_interval=args.interval,
            downsample_factor=args.downsample,
        )
        print(f"  → {filepath} ({len(report.records)} records, "
              f"downsampled to {len(report.records) // args.downsample})")


if __name__ == "__main__":
    main()
