from dataclasses import replace
from datetime import datetime, timedelta, timezone
from custom_components.ups.models import *
from custom_components.ups.profiles import make_profile

def utc(t=0): return datetime(2026,10,19,tzinfo=timezone.utc)+timedelta(seconds=t)
def source(**changes): return replace(SourceConfig("synthetic", "sensor.current", "sensor.voltage",min_current_a=-10,max_current_a=10),**changes)
def profile(**changes):
    p=make_profile("flooded","smartec",battery_id="battery-1",nominal_ah=125)
    return replace(p,source=source(),**changes)
def sample(t,amps=0.0,volts=12.0,**changes):
    return replace(Sample(utc(t),t,"run-1","synthetic",amps,volts),**changes)
def reading(t,amps=0.0,volts=12.0,**changes):
    return ValidatedSample(sample(t,amps,volts,**changes),utc(t),t,"run-1",())
def raw(t,amps="0",volts="12",**changes):
    reported=changes.pop("reported_t",t); changes.pop("changed_t",None)
    cu=changes.pop("current_unit","A"); vu=changes.pop("voltage_unit","V")
    readings={"current":RawReading(amps,cu,utc(reported)),"voltage":RawReading(volts,vu,utc(reported))}
    readings.update(changes.pop("readings",{}))
    return RawSnapshot(utc(t),t,"run-1",readings,**changes)

def run_constant(state,*,seconds,amps,volts=12.0,step_s=5):
    from custom_components.ups.engine import advance
    for t in range(0,seconds+1,step_s): state=advance(state,reading(t,amps,volts)).state
    return state
