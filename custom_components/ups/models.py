"""Immutable calculation and checkpoint contracts; no HA dependencies."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime

@dataclass(frozen=True)
class SourceConfig:
    source_id: str
    current_entity_id: str
    voltage_entity_id: str
    expected_interval_s: float = 5.0
    sign: int = 1
    scale: float = 1.0
    offset_a: float = 0.0
    min_current_a: float = -0.8192
    max_current_a: float = 0.8192
    temperature_entity_id: str | None = None
    humidity_entity_id: str | None = None
    grid_failed_entity_id: str | None = None
    battery_fault_entity_id: str | None = None
    load_power_entity_id: str | None = None
    charge_blocked_entity_id: str | None = None
    full_flag_entity_id: str | None = None
    min_cell_voltage_entity_id: str | None = None
    cutoff_flag_entity_id: str | None = None
    charge_stage_entity_id: str | None = None
    bms_soc_entity_id: str | None = None
    temperature_is_ambient: bool = True
    auxiliary_interval_s: float = 300.0

@dataclass(frozen=True)
class BatteryConfig:
    battery_id: str
    name: str
    chemistry: str
    nominal_ah: float
    nominal_voltage: float
    ups_profile: str
    source: SourceConfig
    installed_at: datetime | None = None
    cutoff_v: float | None = None
    reserve: float = 0.0
    charge_efficiency: float = 0.95
    peukert_k: float = 1.20
    full_voltage_v: float | None = None
    tail_current_a: float | None = None
    full_hold_s: float = 180.0
    mode_enter_a: float = 0.05
    mode_exit_a: float = 0.025
    mode_hold_s: float = 15.0
    load_is_complete: bool = False
    load_efficiency: float = 1.0
    temperature_factors: tuple[tuple[float, float], ...] = ()

@dataclass(frozen=True)
class RawReading:
    value: str | float | bool | None
    unit: str | None
    reported_at: datetime | None

@dataclass(frozen=True)
class RawSnapshot:
    utc: datetime
    monotonic_s: float
    run_id: str
    readings: dict[str, RawReading]

@dataclass(frozen=True)
class Sample:
    utc: datetime
    monotonic_s: float
    run_id: str
    source_id: str
    current_a: float
    voltage_v: float
    temperature_c: float | None = None
    grid_failed: bool | None = None
    battery_fault: bool | None = None
    charge_blocked: bool | None = None
    full_flag: bool | None = None
    min_cell_voltage_v: float | None = None
    load_power_w: float | None = None
    humidity_percent: float | None = None
    cutoff_flag: bool | None = None
    charge_stage: str | None = None
    bms_soc_percent: float | None = None

@dataclass(frozen=True)
class ValidatedSample:
    sample: Sample | None
    utc: datetime
    monotonic_s: float
    run_id: str
    issues: tuple[str, ...]

@dataclass(frozen=True)
class IntervalCharge:
    dt_s: float = 0.0
    charge_ah: float = 0.0
    discharge_ah: float = 0.0
    charge_wh: float = 0.0
    discharge_wh: float = 0.0
    delta_stored_ah: float = 0.0

@dataclass(frozen=True)
class Session:
    session_id: str
    battery_id: str
    kind: str
    started_at: datetime
    ended_at: datetime | None = None
    measured_s: float = 0.0
    gap_s: float = 0.0
    charge_ah: float = 0.0
    discharge_ah: float = 0.0
    charge_wh: float = 0.0
    discharge_wh: float = 0.0
    min_voltage_v: float | None = None
    average_load_w: float | None = None
    max_load_w: float = 0.0
    temperature_c: float | None = None
    start_soc: float | None = None
    end_soc: float | None = None
    quality: tuple[str, ...] = ()
    end_reason: str | None = None

@dataclass(frozen=True)
class Anchor:
    utc: datetime
    soc_fraction: float
    origin: str
    independently_verified: bool

@dataclass(frozen=True)
class CapacityObservation:
    discharged_ah: float
    start: Anchor
    end: Anchor
    reference_temperature_c: float | None
    reference_current_a: float
    cutoff_v: float
    has_gap: bool = False
    has_saturation: bool = False
    source_changed: bool = False
    mixed_direction: bool = False

@dataclass(frozen=True)
class CapacityEstimate:
    ah: float
    reference_temperature_c: float
    reference_current_a: float
    cutoff_v: float
    observed_at: datetime
    observation_count: int

@dataclass(frozen=True)
class DomainEvent:
    event_id: str
    kind: str
    occurred_at: datetime
    battery_id: str
    session_id: str | None
    message: str

@dataclass(frozen=True)
class BatteryArchive:
    config: BatteryConfig
    retired_at: datetime
    working_capacity: CapacityEstimate | None
    health_capacity: CapacityEstimate | None
    last_charge: Session | None
    last_discharge: Session | None

@dataclass(frozen=True)
class EngineState:
    config: BatteryConfig
    generation: int = 0
    last_sample: Sample | None = None
    last_tick_monotonic_s: float | None = None
    run_id: str | None = None
    remaining_charge_ah: float | None = None
    charge_ah_total: float = 0.0
    discharge_ah_total: float = 0.0
    charge_wh_total: float = 0.0
    discharge_wh_total: float = 0.0
    working_capacity: CapacityEstimate | None = None
    health_capacity: CapacityEstimate | None = None
    mode: str = "unknown"
    active_session: Session | None = None
    last_charge: Session | None = None
    last_discharge: Session | None = None
    candidate_mode: str | None = None
    candidate_started_at: datetime | None = None
    candidate_started_mono: float | None = None
    candidate_session: Session | None = None
    candidate_previous_session: Session | None = None
    minute_samples: tuple[ValidatedSample, ...] = ()
    last_anchor: Anchor | None = None
    smoothed_discharge_a: float | None = None
    mode_observed_s: float = 0.0
    issues: tuple[str, ...] = ()
    pending_events: tuple[DomainEvent, ...] = ()
    activity_reserved_ids: tuple[str, ...] = ()
    has_gap: bool = False
    anchor_discharge_ah: float = 0.0
    anchor_charge_ah: float = 0.0
    anchor_has_gap: bool = False
    anchor_has_saturation: bool = False
    anchor_source_changed: bool = False
    anchor_temperature_sum: float = 0.0
    anchor_temperature_s: float = 0.0
    anchor_discharge_s: float = 0.0
    capacity_candidate: CapacityEstimate | None = None
    capacity_conflict: bool = False
    last_observation: CapacityObservation | None = None
    full_since_mono: float | None = None
    full_latched: bool = False
    cutoff_count: int = 0
    usable_empty: bool = False
    post_cutoff_charge_ah: float | None = None
    last_verified_discharge_a: float | None = None
    finishing_started_at: datetime | None = None
    finishing_measured_s: float = 0.0
    last_finishing_s: float | None = None
    last_finishing_temperature_c: float | None = None
    last_finishing_current_a: float | None = None
    archives: tuple[BatteryArchive, ...] = ()
    last_reset_at: datetime | None = None
    restored: bool = False

@dataclass(frozen=True)
class Update:
    state: EngineState
    events: tuple[DomainEvent, ...] = ()
    save_required: bool = False

@dataclass(frozen=True)
class Forecast:
    soc_percent: float | None
    usable_soc_percent: float | None
    remaining_ah: float | None
    remaining_wh: float | None
    time_remaining_s: float | None
    expected_empty_at: datetime | None
    time_to_full_s: float | None
    quality: tuple[str, ...]
    context: str
