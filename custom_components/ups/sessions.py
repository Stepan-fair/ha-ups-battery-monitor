"""Session accounting and deterministic identities."""
from dataclasses import replace
from uuid import uuid5,NAMESPACE_URL
from .models import Session,DomainEvent

def start_session(config,sample,kind,soc):
    identity=f"{config.battery_id}/{sample.run_id}/{sample.monotonic_s}/{kind}"
    return Session(str(uuid5(NAMESPACE_URL,identity)),config.battery_id,kind,sample.utc,min_voltage_v=sample.voltage_v,temperature_c=sample.temperature_c,start_soc=soc)

def add_interval(session,interval,sample):
    if session is None:return None
    measured=session.measured_s+interval.dt_s
    load=max(0,-sample.current_a*sample.voltage_v)
    average=(session.discharge_wh+interval.discharge_wh)*3600/measured if measured>0 else None
    return replace(session,measured_s=measured,charge_ah=session.charge_ah+interval.charge_ah,discharge_ah=session.discharge_ah+interval.discharge_ah,charge_wh=session.charge_wh+interval.charge_wh,discharge_wh=session.discharge_wh+interval.discharge_wh,min_voltage_v=min(session.min_voltage_v or sample.voltage_v,sample.voltage_v),average_load_w=average,max_load_w=max(session.max_load_w,load),temperature_c=sample.temperature_c if sample.temperature_c is not None else session.temperature_c)

def event(session,kind,now,message):
    return DomainEvent(f"{session.battery_id}/{session.session_id}/{kind}",kind,now,session.battery_id,session.session_id,message)

def close_session(session,now,reason,soc=None):
    return replace(session,ended_at=now,end_reason=reason,end_soc=soc)
