from dataclasses import replace
import pytest
from custom_components.ups.engine import advance,resume,set_known_soc
from custom_components.ups.profiles import initial_state
from .helpers import *

def test_modes_do_not_filter_real_charge():
    s=run_constant(initial_state(profile()),seconds=1800,amps=.032)
    assert s.charge_ah_total==pytest.approx(.016)
    assert s.active_session is None
    for t in range(1805,1900,5):s=advance(s,reading(t,(-1 if t%10 else 1)*.01)).state
    assert s.active_session is None

def test_utc_jump_uses_monotonic_time():
    for jump in [-3600,3600]:
        s=advance(initial_state(profile()),reading(0,-2)).state
        r=reading(5,-2);r=replace(r,utc=utc(5+jump),sample=replace(r.sample,utc=utc(5+jump)))
        assert advance(s,r).state.discharge_ah_total==pytest.approx(10/3600)

def test_duplicate_tick_is_ignored():
    s=run_constant(initial_state(profile()),seconds=20,amps=-2)
    assert advance(s,reading(20,-2)).state==s
    assert len(s.minute_samples)==5

def test_partial_sessions_keep_original_id():
    s=run_constant(initial_state(profile()),seconds=60,amps=-2)
    ident=s.active_session.session_id
    assert s.active_session.started_at==utc(0)
    assert s.active_session.discharge_ah==pytest.approx(120/3600)
    restored=resume(s,run_id="run-2")
    restored=advance(restored,reading(240,-2,run_id="run-2")).state
    assert restored.active_session.session_id==ident
    assert restored.discharge_ah_total==s.discharge_ah_total
    assert restored.active_session.gap_s==180
    assert len(restored.minute_samples)==13

def test_gap_breaks_interval_and_keeps_last_valid():
    s=run_constant(initial_state(profile()),seconds=20,amps=-2)
    s=advance(s,ValidatedSample(None,utc(25),25,"run-1",("range",))).state
    assert s.last_sample.utc==utc(20)
    s=advance(s,reading(30,-2)).state
    assert s.discharge_ah_total==pytest.approx(40/3600)
    assert s.anchor_has_gap and s.anchor_has_saturation
    assert s.active_session.gap_s==10

def test_charge_to_idle_finishes_once_after_hold():
    s=run_constant(initial_state(profile()),seconds=60,amps=2)
    for t in range(65,85,5): s=advance(s,reading(t,0)).state
    assert s.active_session is None
    assert s.last_charge.ended_at==utc(65)
    assert len([e for e in s.pending_events if e.kind=="session_ended"])==1

def test_manual_estimate_is_not_independent_learning():
    s=set_known_soc(initial_state(profile()),Anchor(utc(),.5,"manual_estimate",False)).state
    assert s.remaining_charge_ah==62.5
    assert s.charge_ah_total==0
