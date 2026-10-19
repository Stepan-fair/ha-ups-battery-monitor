"""Per-battery evidence derived from the same accepted electrical intervals."""
from dataclasses import replace

def track_evidence(old, state, sample, interval):
    p=state.passport
    if sample is not None:
        p=replace(p,charge_ah=p.charge_ah+interval.charge_ah,
                  discharge_ah=p.discharge_ah+interval.discharge_ah,
                  charge_wh=p.charge_wh+interval.charge_wh,
                  discharge_wh=p.discharge_wh+interval.discharge_wh,
                  min_voltage_v=min(p.min_voltage_v,sample.voltage_v) if p.min_voltage_v is not None else sample.voltage_v,
                  max_charge_a=max(p.max_charge_a,sample.current_a),
                  max_discharge_a=max(p.max_discharge_a,-sample.current_a),
                  monitoring_started_at=p.monitoring_started_at or sample.utc)
    if state.full_latched and not old.full_latched and sample is not None:
        p=replace(p,full_count=p.full_count+1,last_full_at=sample.utc)
    history=state.capacity_history
    if state.working_capacity is not None and state.working_capacity!=old.working_capacity:
        history=(history+(state.working_capacity,))[-64:]
    state=replace(state,passport=p,capacity_history=history)
    from .prediction import track_predictions
    return track_predictions(old,state,sample)


def verify_meter(state,*,zero_raw_a,reference_raw_a,reference_a,confirmed,now):
    """Two explicitly observed points. Never infer zero from idle or send commands."""
    import math
    from .engine import reconfigure
    from .models import DomainEvent,Update
    values=(zero_raw_a,reference_raw_a,reference_a)
    if not confirmed or any(not math.isfinite(v) for v in values):raise ValueError('confirmation_required')
    source=state.config.source
    if not source.min_current_a*.98<reference_raw_a<source.max_current_a*.98:raise ValueError('range')
    delta=reference_raw_a-zero_raw_a
    if abs(delta)<.01 or abs(reference_a)<.05:raise ValueError('reference_too_small')
    ratio=reference_a/delta
    scale=abs(ratio)
    if not 0<scale<=1000:raise ValueError('scale')
    config=replace(state.config,source=replace(source,scale=scale,sign=1 if ratio>0 else -1,offset_a=zero_raw_a*scale))
    result=reconfigure(state,config,now=now).state
    ev=DomainEvent(f'{config.battery_id}/meter/{now.isoformat()}','meter_verified',now,config.battery_id,None,'Измеритель проверен по явно заданным нулю и контрольному току; требуется новая опорная точка заряда.')
    return Update(replace(result,meter_checked_at=now,pending_events=result.pending_events+(ev,)),(ev,),True)
