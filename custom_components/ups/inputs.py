"""Normalize one selected stream; optional failures never turn into zero current."""
import math
from .models import RawSnapshot, SourceConfig, Sample, ValidatedSample

class InvalidReading(ValueError): pass

def _value(r,now,period,units):
    if r is None or r.reported_at is None: raise InvalidReading("invalid")
    age=(now-r.reported_at).total_seconds()
    if age>3*period: raise InvalidReading("stale")
    if age < -period: raise InvalidReading("future")
    if r.unit not in units: raise InvalidReading("unit")
    try: v=float(r.value)
    except (ValueError,TypeError): raise InvalidReading("invalid") from None
    if not math.isfinite(v): raise InvalidReading("invalid")
    scale,offset=units[r.unit]
    return v*scale+offset

def normalize(raw: RawSnapshot, config: SourceConfig) -> ValidatedSample:
    issues=[]
    def number(key,units,optional=False):
        period=config.auxiliary_interval_s if key in ('temperature','humidity') else config.bms_interval_s if key in ('battery_temperature','min_cell_voltage','max_cell_voltage','min_cell_index','max_cell_index','bms_soc','link_quality') else config.expected_interval_s
        try: return _value(raw.readings.get(key),raw.utc,period,units)
        except InvalidReading as e:
            if not optional or key in raw.readings: issues.append(f"{key}_{e}" if optional else str(e))
            return None
    amps=number("current",{"A":(1,0),"mA":(.001,0)})
    volts=number("voltage",{"V":(1,0),"mV":(.001,0)})
    if amps is not None:
        calibrated=config.sign*(amps*config.scale-config.offset_a)
        def outside(i): return i<=config.min_current_a*.98 or i>=config.max_current_a*.98
        # Hardware clipping is determined before software calibration. The
        # reference correction changes units, never the ADC input range.
        if outside(amps): issues.append("range")
        amps=calibrated
    if volts is not None and not 0<volts<=1000: issues.append("voltage_range")
    required_ok=not issues
    optional={}
    for key,field,units in [("temperature","temperature_c",{"°C":(1,0),"°F":(5/9,-160/9)}),("humidity","humidity_percent",{"%":(1,0)}),("load_power","load_power_w",{"W":(1,0),"kW":(1000,0)}),("min_cell_voltage","min_cell_voltage_v",{"V":(1,0),"mV":(.001,0)}),("bms_soc","bms_soc_percent",{"%":(1,0)})]:
        v=number(key,units,True)
        if v is not None and ((key in {"humidity","bms_soc"} and not 0<=v<=100) or (key=="temperature" and not -80<=v<=150) or (key in {"load_power","min_cell_voltage"} and v<0)):
            issues.append(key+"_range");v=None
        optional[field]=v
    for key,field,units in [('battery_temperature','battery_temperature_c',{'°C':(1,0),'°F':(5/9,-160/9)}),('max_cell_voltage','max_cell_voltage_v',{'V':(1,0),'mV':(.001,0)}),('min_cell_index','min_cell_index',{None:(1,0)}),('max_cell_index','max_cell_index',{None:(1,0)}),('link_quality','link_quality_percent',{'%':(1,0)})]:
        v=number(key,units,True)
        if v is not None and ((key=='battery_temperature' and not -80<=v<=150) or (key=='max_cell_voltage' and not 0<=v<=10) or (key=='link_quality' and not 0<=v<=100) or (key.endswith('_index') and (not 0<=v<=256 or v!=int(v)))):
            issues.append(key+'_range');v=None
        optional[field]=v
    battery_temp=optional.pop('battery_temperature_c')
    optional['ambient_temperature_c']=optional['temperature_c'] if config.temperature_is_ambient else None
    optional['temperature_is_ambient']=config.temperature_is_ambient
    if battery_temp is not None:
        optional['temperature_c']=battery_temp;optional['temperature_is_ambient']=False
    if optional['max_cell_voltage_v'] is not None and optional['min_cell_voltage_v'] is not None and optional['max_cell_voltage_v']<optional['min_cell_voltage_v']:
        optional['max_cell_voltage_v']=None;issues.append('cell_order')
    for key in ["grid_failed","battery_fault","charge_blocked","full_flag","cutoff_flag","charge_mosfet","discharge_mosfet"]:
        r=raw.readings.get(key)
        if r is None: optional[key]=None;continue
        # HA binary states are latched until an explicit change or unavailable.
        # Their timestamp is not a periodic numeric measurement timestamp.
        if r.reported_at is not None and r.value in ("on","off",True,False):optional[key]=r.value in ("on",True)
        else:optional[key]=None;issues.append(key+"_invalid")
    r=raw.readings.get("charge_stage")
    optional["charge_stage"]=None
    if r is not None:
        if r.reported_at is not None and r.value in {"constant_current","finishing","idle"}: optional["charge_stage"]=r.value
        else: issues.append("charge_stage_invalid")
    r=raw.readings.get('protection_reason');optional['protection_reason']=None
    if r is not None:
        if r.reported_at is not None and isinstance(r.value,str) and r.value not in ('unknown','unavailable') and 0<= (raw.utc-r.reported_at).total_seconds() <=3*config.bms_interval_s:
            optional['protection_reason']=''.join(ch for ch in r.value if ch.isprintable())[:256]
        else:issues.append('protection_reason_invalid')
    s=Sample(raw.utc,raw.monotonic_s,raw.run_id,config.source_id,amps,volts,**optional) if required_ok else None
    return ValidatedSample(s,raw.utc,raw.monotonic_s,raw.run_id,tuple(dict.fromkeys(issues)))
