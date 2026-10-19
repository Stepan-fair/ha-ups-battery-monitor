"""One conservative forecast from the same charge inventory."""
from datetime import timedelta
from .models import *

def _factor(table,temp):
    if temp<=table[0][0]:return table[0][1]
    if temp>=table[-1][0]:return table[-1][1]
    for (t0,f0),(t1,f1) in zip(table,table[1:]):
        if t0<=temp<=t1:return f0+(f1-f0)*(temp-t0)/(t1-t0)
    return 1.0

def forecast(state: EngineState,sample: Sample,*,now) -> Forecast:
    c=state.config;estimate=state.working_capacity;capacity=estimate.ah if estimate else c.nominal_ah
    issues=list(state.issues)
    if state.has_gap:issues.append("data_gap")
    if estimate is None:issues.append("nominal_estimate")
    if state.remaining_charge_ah is None:
        return Forecast(None,None,None,None,None,None,None,tuple(dict.fromkeys(issues+["no_initial_anchor"])),"unknown")
    if state.last_anchor and not state.last_anchor.independently_verified:issues.append("manual_estimate")
    raw_soc=state.remaining_charge_ah/capacity
    soc=max(0,min(1,raw_soc))
    available=min(max(0,state.remaining_charge_ah),state.post_cutoff_charge_ah) if state.post_cutoff_charge_ah is not None else max(0,state.remaining_charge_ah)
    usable=max(0,min(1,available/capacity)-c.reserve)
    if not 0<=raw_soc<=1:issues.append("model_mismatch")
    if state.capacity_conflict:issues.append("capacity_conflict")
    cutoff_compatible=estimate is None or (c.cutoff_v is not None and abs(estimate.cutoff_v-c.cutoff_v)<=.05)
    if not cutoff_compatible:issues.append("cutoff_changed")
    valid=not any(i in issues for i in ("range","invalid","stale","future","unit","voltage_range","storage_error","restore_error")) and abs((now-sample.utc).total_seconds())<=3*c.source.expected_interval_s
    drain=state.mode=="discharging" and sample.current_a< -c.mode_exit_a
    context="discharging" if drain else "unknown_load"
    current=state.smoothed_discharge_a if drain else None
    if not drain:
        if c.load_is_complete and sample.load_power_w is not None and sample.voltage_v>0:
            current=sample.load_power_w/(sample.voltage_v*c.load_efficiency);context="complete_load"
        elif state.last_verified_discharge_a is not None:
            age=(now-state.last_verified_discharge_at).total_seconds() if state.last_verified_discharge_at else None
            if age is not None and 0<=age<=c.load_max_age_s:
                current=state.last_verified_discharge_a;context="last_discharge_load"
            else:issues.append('load_expired')
    ref_t=estimate.reference_temperature_c if estimate else 25
    ref_i=estimate.reference_current_a if estimate else capacity/20
    ft=fi=1.0
    if sample.temperature_c is not None:
        if c.temperature_factors:
            ft=_factor(c.temperature_factors,sample.temperature_c)/_factor(c.temperature_factors,ref_t)
        elif abs(sample.temperature_c-ref_t)>5:issues.append("temperature_uncompensated")
    else:issues.append("temperature_unknown")
    if c.source.temperature_is_ambient:issues.append("ambient_temperature")
    if current is not None and current>c.mode_exit_a and c.chemistry!="lifepo4":fi=(ref_i/current)**(c.peukert_k-1)
    remaining=capacity*usable*ft*fi
    if state.post_cutoff_charge_ah is not None:
        remaining=min(remaining,max(0,state.post_cutoff_charge_ah-capacity*c.reserve))
    seconds=None;cutoff_seconds=None;empty_at=None;full=None
    if valid and current is not None and current>c.mode_exit_a and not state.capacity_conflict and cutoff_compatible and c.cutoff_v is not None:
        seconds=remaining/current*3600
        cutoff_remaining=capacity*max(0,min(1,available/capacity))*ft*fi
        if state.post_cutoff_charge_ah is not None:cutoff_remaining=min(cutoff_remaining,state.post_cutoff_charge_ah)
        cutoff_seconds=cutoff_remaining/current*3600
        if drain:empty_at=now+timedelta(seconds=seconds)
    if state.mode_observed_s<30:issues.append("preliminary")
    if state.usable_empty:
        usable=0;remaining=0
        seconds=0 if valid else None
        cutoff_seconds=seconds
        empty_at=now if drain and valid else None
    if c.cutoff_v is None:issues.append("cutoff_unconfigured")
    if c.reserve:context+="_to_reserve"
    if state.mode=="charging" and valid and sample.current_a>c.mode_exit_a and sample.charge_blocked is not True:
        if sample.charge_stage=="constant_current":
            full=max(0,capacity-available)/(c.charge_efficiency*sample.current_a)*3600
            issues.append("charge_eta_preliminary")
        elif sample.charge_stage=="finishing" and state.last_finishing_s is not None and state.finishing_started_at is not None and not state.anchor_has_gap:
            if sample.temperature_c is not None and state.last_finishing_temperature_c is not None and abs(sample.temperature_c-state.last_finishing_temperature_c)<=5 and state.last_finishing_current_a and abs(sample.current_a/state.last_finishing_current_a-1)<=.2:
                full=max(0,state.last_finishing_s-state.finishing_measured_s)
    return Forecast(soc*100,usable*100,remaining,remaining*c.nominal_voltage,seconds,empty_at,full,tuple(dict.fromkeys(issues)),context,cutoff_seconds)
