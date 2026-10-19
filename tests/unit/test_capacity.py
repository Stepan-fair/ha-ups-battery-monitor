from dataclasses import replace
import pytest
from custom_components.ups.capacity import consider_observation,evaluate_full_anchor
from custom_components.ups.profiles import initial_state
from custom_components.ups.engine import advance,set_known_soc
from .helpers import *

def observation(**kw):
    o=CapacityObservation(20,Anchor(utc(),1,"full",True),Anchor(utc(36000),.5,"external",True),25,2,10.5)
    return replace(o,**kw)

def test_capacity_uses_independent_endpoints():
    s=initial_state(profile())
    assert consider_observation(s,observation()).working_capacity.ah==pytest.approx(40)
    bad=observation(end=Anchor(utc(36000),.5,"own_soc",False))
    assert consider_observation(s,bad).working_capacity is None

@pytest.mark.parametrize('field',["has_gap","has_saturation","source_changed","mixed_direction"])
def test_bad_segments_do_not_learn(field):
    s=initial_state(profile())
    assert consider_observation(s,observation(**{field:True})).working_capacity is None

def test_temperature_is_not_aging():
    s=consider_observation(initial_state(profile()),observation(reference_temperature_c=9))
    assert s.working_capacity.ah==40
    assert s.health_capacity is None

def test_low_rate_lead_observation_does_not_claim_rated_health():
    s=consider_observation(initial_state(profile()),observation())
    assert s.health_capacity is None
    s=consider_observation(initial_state(profile()),observation(reference_current_a=6.25))
    assert s.health_capacity.ah==40

def test_conflict_requires_second_independent_observation():
    s=consider_observation(initial_state(profile()),observation())
    o=observation(discharged_ah=10,end=Anchor(utc(50000),.5,"external",True))
    s=consider_observation(s,o)
    assert s.working_capacity.ah==40 and s.capacity_conflict
    assert consider_observation(s,o).capacity_conflict
    second=replace(o,start=Anchor(utc(60000),1,"full",True),end=Anchor(utc(80000),.5,"external",True),discharged_ah=10.5)
    s=consider_observation(s,second)
    assert s.working_capacity.ah==pytest.approx(20.5)
    assert not s.capacity_conflict

def test_full_requires_voltage_tail_hold_and_no_block():
    s=initial_state(profile(full_voltage_v=14.2,tail_current_a=.5))
    for t in range(0,181,5):s=advance(s,reading(t,.2,14.3)).state
    assert s.last_anchor.independently_verified
    assert s.remaining_charge_ah==pytest.approx(125)
    assert evaluate_full_anchor(s,sample(185,.2,14.3,charge_blocked=True)) is None
    assert evaluate_full_anchor(initial_state(profile()),sample(500,0,14.5)) is None

def test_one_low_voltage_does_not_zero_charge():
    s=set_known_soc(initial_state(profile()),Anchor(utc(),.5,"manual",False)).state
    s=advance(s,reading(0,-2,10.4)).state
    assert not s.usable_empty
    s=advance(s,reading(5,-2,10.4)).state
    assert s.usable_empty
    assert s.remaining_charge_ah>62

def test_full_to_cutoff_learning_reanchors_inventory_without_phantom_charge():
    s=set_known_soc(initial_state(profile()),Anchor(utc(),1,'verified_full',True)).state
    for t in range(0,61,5):
        s=advance(s,reading(t,-2,10.4 if t>=55 else 12,temperature_c=25)).state
    assert s.working_capacity.ah==pytest.approx(120/3600)
    assert s.remaining_charge_ah==0
    assert s.discharge_ah_total==pytest.approx(120/3600)

def test_verified_anchor_replaces_old_inventory_gap():
    s=replace(initial_state(profile()),has_gap=True,anchor_has_gap=True)
    s=set_known_soc(s,Anchor(utc(),1,'verified_full',True)).state
    assert not s.has_gap

def test_confirmed_float_does_not_create_phantom_stored_charge():
    s=initial_state(profile(full_voltage_v=14.2,tail_current_a=.5))
    for t in range(0,601,5):s=advance(s,reading(t,.2,14.3)).state
    assert s.remaining_charge_ah==125
    assert s.charge_ah_total==pytest.approx(.2*600/3600)
    assert s.mode=="idle" and s.active_session is None
    assert s.last_charge.ended_at==utc(180)
