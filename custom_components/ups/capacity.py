"""Learn only from independent endpoints, retaining reference conditions."""
from dataclasses import replace
from .models import *

def _comparable(a,b):
    return abs(a.reference_temperature_c-b.reference_temperature_c)<=5 and abs(a.cutoff_v-b.cutoff_v)<=.05 and abs(a.reference_current_a/b.reference_current_a-1)<=.2

def consider_observation(state: EngineState,observation: CapacityObservation) -> EngineState:
    o=observation;drop=o.start.soc_fraction-o.end.soc_fraction
    if state.last_observation==o:return state
    s=replace(state,last_observation=o)
    if not (o.start.independently_verified and o.end.independently_verified) or drop<.30 or o.end.utc<=o.start.utc or any((o.has_gap,o.has_saturation,o.source_changed,o.mixed_direction)) or o.discharged_ah<=0 or o.reference_current_a<=0 or o.reference_temperature_c is None:return s
    ah=o.discharged_ah/drop
    if not 0<ah<=state.config.nominal_ah*3:return s
    new=CapacityEstimate(ah,o.reference_temperature_c,o.reference_current_a,o.cutoff_v,o.end.utc,1)
    old=state.working_capacity
    if old is not None and _comparable(old,new):
        if abs(new.ah/old.ah-1)>.25:
            candidate=state.capacity_candidate
            if candidate and _comparable(candidate,new) and new.observed_at>candidate.observed_at and abs(new.ah/candidate.ah-1)<=.1:
                new=replace(new,ah=(new.ah+candidate.ah)/2,observation_count=2)
            else:return replace(s,capacity_candidate=new,capacity_conflict=True)
        else:new=replace(new,ah=.8*old.ah+.2*new.ah,observation_count=old.observation_count+1)
    health=state.health_capacity
    rated=state.config.nominal_ah/20
    if abs(new.reference_temperature_c-25)<=5 and (state.config.chemistry=="lifepo4" or abs(new.reference_current_a/rated-1)<=.2):health=new
    return replace(s,working_capacity=new,health_capacity=health,capacity_candidate=None,capacity_conflict=False)

def full_conditions(state,sample):
    c=state.config
    # An omitted optional signal is different from a configured signal that
    # is currently unavailable. Only verified safe values may confirm full.
    for key,expected in (("charge_blocked",False),("battery_fault",False),("grid_failed",False),("full_flag",True)):
        if getattr(c.source,key+"_entity_id") and getattr(sample,key) is not expected:return False
    if sample.charge_stage=="idle":return False
    if c.source.charge_stage_entity_id and sample.charge_stage not in ("constant_current","finishing"):return False
    return c.full_voltage_v is not None and c.tail_current_a is not None and c.full_hold_s>0 and sample.voltage_v>=c.full_voltage_v and 0<=sample.current_a<=c.tail_current_a and sample.charge_blocked is not True and sample.battery_fault is not True and sample.grid_failed is not True and sample.full_flag is not False and not (c.chemistry=="lifepo4" and sample.temperature_c is not None and sample.temperature_c<=0)

def evaluate_full_anchor(state: EngineState,sample: Sample) -> Anchor | None:
    if not full_conditions(state,sample) or state.full_since_mono is None:return None
    if sample.monotonic_s-state.full_since_mono<state.config.full_hold_s:return None
    return Anchor(sample.utc,1.0,"auto_full",True)
