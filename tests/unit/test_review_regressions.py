"""Regression scenarios from the independent release review."""
from dataclasses import replace
import pytest
from custom_components.ups.engine import advance, set_known_soc, resume
from custom_components.ups.forecast import forecast
from custom_components.ups.profiles import initial_state
from .helpers import *


def stopped_at_cutoff():
    s=set_known_soc(initial_state(profile()),Anchor(utc(),.5,"manual",False)).state
    for t in range(0,31,5):
        s=advance(s,reading(t,-2,10.4 if t>=25 else 12)).state
    for t in range(35,56,5):s=advance(s,reading(t,0)).state
    return s


def test_cutoff_idle_does_not_forecast_phantom_runtime():
    s=stopped_at_cutoff()
    assert s.mode=="idle" and s.usable_empty
    f=forecast(s,s.last_sample,now=utc(55))
    assert f.remaining_ah==0
    assert f.time_remaining_s==0


def test_small_recharge_after_cutoff_only_unlocks_measured_charge(tmp_path):
    from custom_components.ups.persistence import CheckpointStore
    s=stopped_at_cutoff()
    charge_before=s.charge_ah_total
    s=advance(s,reading(60,2)).state
    added=(s.charge_ah_total-charge_before)*s.config.charge_efficiency
    store=CheckpointStore(tmp_path,"review")
    store.save(s)
    s=store.load().state
    f=forecast(s,s.last_sample,now=utc(60))
    assert 0<f.remaining_ah<=added+1e-12
    assert f.time_remaining_s<=added/2*3600+1e-9


def test_float_to_discharge_zero_crossing_still_learns_capacity():
    s=initial_state(profile(full_voltage_v=14.2,tail_current_a=.5))
    for t in range(0,201,5):s=advance(s,reading(t,.2,14.3,temperature_c=25)).state
    charge_before=s.charge_ah_total
    for t in range(205,266,5):
        s=advance(s,reading(t,-2,10.4 if t>=260 else 12,temperature_c=25)).state
    assert s.charge_ah_total>charge_before  # Keep the positive terminal lobe.
    assert s.working_capacity is not None
    assert not s.last_observation.mixed_direction
    assert s.working_capacity.ah==pytest.approx(s.discharge_ah_total)
    assert s.last_observation.start.utc==utc(200+5*.2/2.2)
    assert s.remaining_charge_ah==0


@pytest.mark.parametrize("field,value",[
    ("charge_stage","idle"),
    ("charge_stage",None),
    ("charge_blocked",None),
    ("battery_fault",None),
    ("grid_failed",None),
    ("full_flag",None),
])
def test_full_requires_valid_configured_confirmation(field,value):
    config=profile(full_voltage_v=14.2,tail_current_a=.5)
    config=replace(config,source=replace(config.source,**{field+"_entity_id":"sensor.confirmation"}))
    s=initial_state(config)
    for t in range(0,186,5):s=advance(s,reading(t,0,14.3,**{field:value})).state
    assert s.last_anchor is None
    assert s.remaining_charge_ah is None


def test_known_idle_charger_never_confirms_full():
    s=initial_state(profile(full_voltage_v=14.2,tail_current_a=.5))
    for t in range(0,186,5):s=advance(s,reading(t,0,14.3,charge_stage="idle")).state
    assert s.last_anchor is None


@pytest.mark.parametrize("explicit_resume",[False,True])
def test_backwards_utc_restart_never_learns_across_unknown_interval(explicit_resume):
    s=set_known_soc(initial_state(profile()),Anchor(utc(),1,"verified_full",True)).state
    for t in range(0,61,5):s=advance(s,reading(t,-2,temperature_c=25)).state
    if explicit_resume:s=resume(s,run_id="new-process")
    for mono in range(0,61,5):
        value=sample(55+mono,-2,10.4 if mono>=55 else 12,temperature_c=25,run_id="new-process",monotonic_s=mono)
        s=advance(s,ValidatedSample(value,value.utc,mono,"new-process",())).state
    assert s.has_gap
    assert s.last_observation.has_gap
    assert s.working_capacity is None
