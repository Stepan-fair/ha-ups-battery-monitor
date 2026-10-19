"""Regressions for persisted evidence, battery identity and honest predictions."""
from dataclasses import replace
from pathlib import Path
import json
import pytest
from custom_components.ups.models import EngineState, Anchor
from custom_components.ups.engine import advance, resume, new_battery, reconfigure
from custom_components.ups.forecast import forecast
from custom_components.ups.persistence import decode_state, encode_state, CheckpointStore
from .helpers import profile, source, sample, reading, utc, run_constant


def test_v1_checkpoint_preserves_inventory_identity_and_totals():
    s = decode_state(json.loads((Path(__file__).parents[1]/'fixtures/checkpoint-v1.json').read_text()))
    assert s.generation == 23
    assert s.config.battery_id == 'battery-1'
    assert s.remaining_charge_ah == 42.5
    assert s.charge_ah_total == 7.25
    assert s.discharge_ah_total == 3.5
    assert s.passport.discharge_ah == 3.5
    assert s.passport.history_partial
    assert s.last_verified_discharge_at is None


def test_passport_counts_partial_cycles_and_replacement_archives_them(tmp_path):
    s = run_constant(EngineState(profile(nominal_ah=4)), seconds=3600, amps=-2)
    assert s.passport.discharge_ah == pytest.approx(2)
    assert s.passport.min_voltage_v == 12
    assert s.passport.max_discharge_a == 2
    store = CheckpointStore(tmp_path, 'test')
    store.save(s)
    restored = store.load().state
    n = new_battery(restored, battery_id='next', now=utc(4000)).state
    assert n.passport.discharge_ah == 0
    assert n.archives[-1].passport.discharge_ah == pytest.approx(2)
    assert n.discharge_ah_total == pytest.approx(2)


def test_restart_never_confirms_empty():
    s = run_constant(EngineState(profile()), seconds=60, amps=-2)
    s = resume(s, run_id='next')
    r = reading(120, -.2)
    r = replace(r, run_id='next', sample=replace(r.sample, run_id='next'))
    s = advance(s, r).state
    assert s.termination_status == 'unconfirmed_stop'
    assert not s.usable_empty
    assert s.last_anchor is None


def test_cutoff_changes_invalidate_working_learning_without_faking_aging():
    from custom_components.ups.models import CapacityEstimate
    cap = CapacityEstimate(80,25,6.25,10.5,utc(),2)
    s = replace(EngineState(profile()),working_capacity=cap,health_capacity=cap,
                last_anchor=Anchor(utc(),1,'auto_full',True),remaining_charge_ah=40)
    s = reconfigure(s,replace(s.config,cutoff_v=11),now=utc(60)).state
    assert s.working_capacity is None
    assert s.health_capacity == cap
    assert s.remaining_charge_ah is None
    assert s.last_anchor is None


def test_old_load_expires_and_reserve_is_distinct_from_cutoff():
    c = profile(chemistry='lifepo4',peukert_k=1,nominal_ah=100,
                reserve=.1,load_max_age_s=3600)
    s = replace(EngineState(c),remaining_charge_ah=50,mode='idle',
                last_verified_discharge_a=2,last_verified_discharge_at=utc(0))
    f = forecast(s,sample(1800,.1),now=utc(1800))
    assert f.time_remaining_s == pytest.approx(72000)
    assert f.time_to_cutoff_s == pytest.approx(90000)
    f = forecast(s,sample(4000,.1),now=utc(4000))
    assert f.time_remaining_s is None
    assert 'load_expired' in f.quality
