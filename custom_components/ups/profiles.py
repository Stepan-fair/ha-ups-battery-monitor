"""Initial assumptions are explicit; no voltage-to-SOC table."""
from .models import BatteryConfig, EngineState, SourceConfig

def make_profile(chemistry: str, ups_profile: str, *, battery_id: str, nominal_ah: float) -> BatteryConfig:
    if chemistry not in {"flooded","agm","gel","lifepo4"}: raise ValueError("chemistry")
    if ups_profile not in {"smartec","meanwell","custom"}: raise ValueError("ups_profile")
    if not 0 < nominal_ah <= 10000: raise ValueError("nominal_ah")
    lfp=chemistry=="lifepo4"
    s=SourceConfig("ina226","sensor.ibp_akb_tok","sensor.ibp_akb_napriazhenie",temperature_entity_id="sensor.temperatura_2_temperature",humidity_entity_id="sensor.temperatura_2_humidity",grid_failed_entity_id="binary_sensor.ibp_neispravnost_seti_220v",battery_fault_entity_id="binary_sensor.ibp_neispravnost_akb")
    return BatteryConfig(battery_id,"АКБ",chemistry,nominal_ah,12.8 if lfp else 12.0,ups_profile,s,cutoff_v=10.5 if ups_profile=="smartec" and not lfp else None,charge_efficiency=.99 if lfp else .95,peukert_k=1.0 if lfp else 1.2)

def initial_state(config: BatteryConfig) -> EngineState:
    return EngineState(config)


def validate_profile(data: dict) -> BatteryConfig:
    from .persistence import _decode
    c=_decode(BatteryConfig,data);s=c.source
    if c.chemistry not in {"flooded","agm","gel","lifepo4"} or c.ups_profile not in {"smartec","meanwell","custom"}:raise ValueError("profile")
    if not c.battery_id or not c.name.strip() or not 0<c.nominal_ah<=10000 or not 0<c.nominal_voltage<=1000:raise ValueError("battery")
    if not 0<=c.reserve<1 or not 0<c.charge_efficiency<=1 or not 0<c.load_efficiency<=1 or not 1<=c.peukert_k<=2:raise ValueError("efficiency")
    if not 0<=c.mode_exit_a<c.mode_enter_a or c.mode_hold_s<0 or c.full_hold_s<0:raise ValueError("hysteresis")
    if c.cutoff_v is not None and not 0<c.cutoff_v<c.nominal_voltage*1.5:raise ValueError("cutoff")
    if c.full_voltage_v is not None and not 0<c.full_voltage_v<=c.nominal_voltage*1.7:raise ValueError("full_voltage")
    if c.tail_current_a is not None and c.tail_current_a<=0:raise ValueError("tail_current")
    if c.cutoff_v and c.full_voltage_v and c.full_voltage_v<=c.cutoff_v:raise ValueError("voltage thresholds")
    if not 1<=s.expected_interval_s<=3600 or s.sign not in (-1,1) or not 0<s.scale<=1000 or not s.min_current_a<0<s.max_current_a:raise ValueError("source")
    import re
    for key in s.__dataclass_fields__:
        v=getattr(s,key)
        if key.endswith('_entity_id') and v is not None and not re.fullmatch(r'[a-z_]+[.][a-z0-9_]+',v):raise ValueError("entity_id")
    if not 1<=s.auxiliary_interval_s<=86400:raise ValueError("auxiliary_interval")
    if not 1<=s.bms_interval_s<=86400:raise ValueError('bms_interval')
    if not 60<=c.load_max_age_s<=31536000 or not 3600<=c.calibration_max_age_s<=31536000:raise ValueError('evidence_age')
    if not s.source_id.strip():raise ValueError("source_id")
    last=-float('inf')
    for t,f in c.temperature_factors:
        if t<=last or not -80<=t<=150 or not 0<f<=2:raise ValueError("temperature_factors")
        last=t
    return c

def profile_form_data(c: BatteryConfig) -> dict:
    from .persistence import _encode
    import json
    data=_encode(c);source=data.pop('source');data.pop('battery_id')
    battery_keys=['name','chemistry','nominal_ah','nominal_voltage','installed_at','ups_profile','cutoff_v','full_voltage_v','tail_current_a']
    battery={k:data.pop(k) for k in battery_keys}
    data['reserve_percent']=data.pop('reserve')*100
    data['temperature_factors_json']=json.dumps(data.pop('temperature_factors'))
    return {'battery':{k:v for k,v in battery.items() if v is not None},'measurements':{k:v for k,v in source.items() if v is not None},'advanced':data}

def profile_from_form(form: dict,base: BatteryConfig) -> BatteryConfig:
    from .persistence import _encode
    import json
    data=_encode(base)
    data.update(form.get('battery',{}));advanced=dict(form.get('advanced',{}))
    data['reserve']=float(advanced.pop('reserve_percent',base.reserve*100))/100
    data['temperature_factors']=json.loads(advanced.pop('temperature_factors_json','[]'))
    data.update(advanced)
    for key in ['installed_at','cutoff_v','full_voltage_v','tail_current_a']:
        data[key]=form.get('battery',{}).get(key) or None
    if data['installed_at'] and len(data['installed_at'])==10:data['installed_at']+='T00:00:00+00:00'
    source=data['source'];incoming=form.get('measurements',{})
    source.update(incoming)
    for key in source:
        if key.endswith('_entity_id') and key not in ['current_entity_id','voltage_entity_id']:source[key]=incoming.get(key) or None
    return validate_profile(data)
