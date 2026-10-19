from dataclasses import replace
import pytest
from custom_components.ups.forecast import forecast
from custom_components.ups.profiles import initial_state
from .helpers import *

def known(**kw):
    p=profile(chemistry="lifepo4",nominal_ah=100,nominal_voltage=12.8,peukert_k=1,cutoff_v=10.5)
    return replace(initial_state(p),remaining_charge_ah=50,smoothed_discharge_a=2,mode="discharging",mode_observed_s=180,**kw)

def test_uninitialized_never_assumes_full():
    f=forecast(initial_state(profile()),sample(5,-2),now=utc(5))
    assert f.soc_percent is None and f.time_remaining_s is None

def test_lfp_never_uses_lead_voltage_table():
    s=known();copy=s
    for v in [11,12,13.4]:
        f=forecast(s,sample(180,-2,v),now=utc(180))
        assert f.soc_percent==50 and f.time_remaining_s==pytest.approx(90000)
    assert s==copy

def test_no_double_rate_or_temperature_correction():
    cap=CapacityEstimate(40,9,2,10.5,utc(),1)
    s=replace(initial_state(profile()),remaining_charge_ah=20,working_capacity=cap,smoothed_discharge_a=2,mode="discharging",mode_observed_s=180)
    f=forecast(s,sample(180,-2,temperature_c=9),now=utc(180))
    assert f.time_remaining_s==pytest.approx(36000)

def test_charge_eta_is_unknown_when_blocked():
    s=replace(known(),mode="charging")
    assert forecast(s,sample(180,2,charge_blocked=True,charge_stage="constant_current"),now=utc(180)).time_to_full_s is None
    assert forecast(s,sample(180,2,charge_stage="finishing"),now=utc(180)).time_to_full_s is None
    f=forecast(s,sample(180,2,charge_stage="constant_current"),now=utc(180))
    assert f.time_to_full_s==pytest.approx(50/(.95*2)*3600)

def test_grid_forecast_never_uses_charge_current():
    s=replace(known(),mode="charging")
    assert forecast(s,sample(180,2,grid_failed=False),now=utc(180)).time_remaining_s is None
    s=replace(s,config=replace(s.config,load_is_complete=True,load_efficiency=.8))
    f=forecast(s,sample(180,2,12.8,grid_failed=False,load_power_w=25.6),now=utc(180))
    assert f.time_remaining_s==pytest.approx(72000)
    assert f.expected_empty_at is None

def test_invalid_conflict_or_zero_current_hides_runtime():
    for s,r in [(known(capacity_conflict=True),sample(180,-2)),(known(),sample(180,0)),(known(issues=("range",)),sample(180,-2))]:
        assert forecast(s,r,now=utc(180)).time_remaining_s is None

def test_reserve_and_confirmed_cutoff():
    s=known();s=replace(s,config=replace(s.config,reserve=.1))
    f=forecast(s,sample(180,-2),now=utc(180))
    assert f.time_remaining_s==pytest.approx(72000)
    assert forecast(replace(s,usable_empty=True),sample(180,-2),now=utc(180)).usable_soc_percent==0

def test_manual_anchor_stays_preliminary_with_learned_capacity():
    cap=CapacityEstimate(100,25,2,10.5,utc(),1)
    s=known(working_capacity=cap,last_anchor=Anchor(utc(),.5,'manual_estimate',False))
    assert 'manual_estimate' in forecast(s,sample(180,-2),now=utc(180)).quality
