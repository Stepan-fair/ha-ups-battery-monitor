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
    return replace(state,passport=p,capacity_history=history)
