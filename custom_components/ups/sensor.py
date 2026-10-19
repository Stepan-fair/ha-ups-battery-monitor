"""Standard HA sensor contract. Rounding is limited to publication."""
from homeassistant.components.sensor import SensorEntity,SensorEntityDescription,SensorDeviceClass as DC,SensorStateClass as SC
from .const import DOMAIN
from .persistence import _encode

MODES=['unknown','idle','charging','discharging','restore_error']
QUALITIES=['restore_error','storage_error','limited_meter','unavailable','no_initial_anchor','capacity_conflict','data_gap','nominal','manual_estimate','observed']
LABELS={'current':'Ток АКБ','voltage':'Напряжение АКБ','temperature':'Температура','humidity':'Влажность','bms_soc':'Заряд BMS (отдельный)','soc':'Заряд АКБ','usable_soc':'Доступный запас','remaining_ah':'Осталось А·ч','remaining_wh':'Осталось энергии','time_remaining':'Автономность','expected_empty_at':'Ожидаемое окончание','time_to_full':'До полного заряда','capacity_ah':'Рабочая ёмкость','health':'Сохранение ёмкости','battery_mode':'Режим АКБ','charge_ah_total':'Принято А·ч','discharge_ah_total':'Отдано А·ч','charge_wh_total':'Принято энергии','discharge_wh_total':'Отдано энергии','charge_started_at':'Начало заряда','discharge_started_at':'Начало разряда','last_charge_ended_at':'Окончание последнего заряда','last_discharge_ended_at':'Окончание последнего разряда','charge_duration':'Длительность заряда','discharge_duration':'Длительность разряда','last_charge_duration':'Последний заряд','last_discharge_duration':'Последний разряд','data_quality':'Достоверность','last_sample_at':'Последнее измерение'}

def sensor_descriptions():
    result=[]
    for key,name in LABELS.items():
        kw={'key':key,'name':name}
        if key in ('current','voltage','temperature','humidity'):
            units={'current':'A','voltage':'V','temperature':'°C','humidity':'%'}
            classes={'current':DC.CURRENT,'voltage':DC.VOLTAGE,'temperature':DC.TEMPERATURE,'humidity':DC.HUMIDITY}
            kw.update(native_unit_of_measurement=units[key],device_class=classes[key],state_class=SC.MEASUREMENT)
        elif key in ('soc','usable_soc','health','bms_soc'):kw.update(native_unit_of_measurement='%',device_class=DC.BATTERY,state_class=SC.MEASUREMENT)
        elif key.endswith('_at'):kw.update(device_class=DC.TIMESTAMP)
        elif 'duration' in key or key in ('time_remaining','time_to_full'):kw.update(native_unit_of_measurement='s',device_class=DC.DURATION)
        elif key=='battery_mode':kw.update(device_class=DC.ENUM,options=MODES,translation_key=key)
        elif key=='data_quality':kw.update(device_class=DC.ENUM,options=QUALITIES,translation_key=key)
        elif '_ah' in key:kw.update(native_unit_of_measurement='Ah',state_class=SC.TOTAL_INCREASING if key.endswith('_total') else SC.MEASUREMENT)
        elif '_wh' in key:kw.update(native_unit_of_measurement='Wh',device_class=DC.ENERGY if key.endswith('_total') else DC.ENERGY_STORAGE,state_class=SC.TOTAL_INCREASING if key.endswith('_total') else SC.MEASUREMENT)
        result.append(SensorEntityDescription(**kw))
    return tuple(result)

def snapshot_values(s,f):
    cap=s.working_capacity.ah if s.working_capacity else s.config.nominal_ah
    health=s.health_capacity.ah/s.config.nominal_ah*100 if s.health_capacity else None
    issues=f.quality
    quality='restore_error' if 'restore_error' in issues else 'storage_error' if 'storage_error' in issues else 'limited_meter' if 'range' in issues else 'unavailable' if any(i in issues for i in ('stale','invalid','future','unit','voltage_range')) else 'no_initial_anchor' if f.soc_percent is None else 'capacity_conflict' if s.capacity_conflict else 'data_gap' if s.has_gap else 'manual_estimate' if 'manual_estimate' in issues else 'nominal' if s.working_capacity is None else 'observed'
    values={'soc':f.soc_percent,'usable_soc':f.usable_soc_percent,'remaining_ah':f.remaining_ah,'remaining_wh':f.remaining_wh,'time_remaining':f.time_remaining_s,'expected_empty_at':f.expected_empty_at,'time_to_full':f.time_to_full_s,'capacity_ah':cap,'health':min(100,max(0,health)) if health is not None else None,'battery_mode':s.mode,'data_quality':quality,'last_sample_at':s.last_sample.utc if s.last_sample else None}
    valid=not any(i in s.issues for i in ('range','invalid','stale','future','unit','voltage_range'))
    sample=s.last_sample if valid else None
    for key,field in [('current','current_a'),('voltage','voltage_v'),('temperature','temperature_c'),('humidity','humidity_percent'),('bms_soc','bms_soc_percent')]:values[key]=getattr(sample,field) if sample else None
    for key in ['charge_ah_total','discharge_ah_total','charge_wh_total','discharge_wh_total']:values[key]=getattr(s,key)
    for kind in ('charge','discharge'):
        mode='charging' if kind=='charge' else 'discharging'
        active=s.active_session if s.active_session and s.active_session.kind==mode else None
        last=getattr(s,'last_'+kind)
        values[kind+'_started_at']=(active or last).started_at if active or last else None
        values['last_'+kind+'_ended_at']=last.ended_at if last else None
        values[kind+'_duration']=active.measured_s if active else None
        values['last_'+kind+'_duration']=last.measured_s if last else None
    for key,v in values.items():
        if isinstance(v,(int,float)):
            precision=3 if '_ah' in key or key in ('current','voltage') else 2 if '_wh' in key else 1 if key in ('soc','usable_soc','health','temperature','humidity','bms_soc') else 0
            values[key]=round(v,precision)
    return values

def snapshot_attributes(s,f):
    cap=s.working_capacity
    attrs={'data_quality':{'issues':list(f.quality),'generation':s.generation,'battery_id':s.config.battery_id,'source':s.config.source.source_id,'has_gap':s.has_gap},'capacity_ah':{'origin':'observed' if cap else 'nominal','conditions':_encode(cap),'battery_name':s.config.name},'health':{'raw_percent':s.health_capacity.ah/s.config.nominal_ah*100 if s.health_capacity else None,'conditions':_encode(s.health_capacity)},'time_remaining':{'context':f.context,'reserve_percent':s.config.reserve*100},'soc':{'last_anchor':_encode(s.last_anchor)},'battery_mode':{'active_session':_encode(s.active_session),'battery_name':s.config.name}}
    attrs['temperature']={'ambient':s.config.source.temperature_is_ambient}
    attrs['battery_mode'].update({'grid_failed':s.last_sample.grid_failed if s.last_sample else None,'battery_fault':s.last_sample.battery_fault if s.last_sample else None,'charge_blocked':s.last_sample.charge_blocked if s.last_sample else None,'min_cell_voltage_v':s.last_sample.min_cell_voltage_v if s.last_sample else None})
    for kind in ('charge','discharge'):
        last=getattr(s,'last_'+kind)
        attrs['last_'+kind+'_duration']={'session':_encode(last)}
        attrs[kind+'_duration']={'session':_encode(s.active_session) if s.active_session and s.active_session.kind==('charging' if kind=='charge' else 'discharging') else None}
    return attrs

async def async_setup_entry(hass,entry,async_add_entities):
    async_add_entities(UpsSensor(entry.runtime_data,d) for d in sensor_descriptions())

class UpsSensor(SensorEntity):
    _attr_should_poll=False
    _attr_has_entity_name=True
    def __init__(self,runtime,description):
        self.runtime=runtime;self.entity_description=description
        self._attr_unique_id=f'{runtime.entry.entry_id}_{description.key}'
        self.entity_id=f'sensor.ups_{description.key}'
        self._attr_device_info={'identifiers':{(DOMAIN,runtime.entry.entry_id)},'name':'ИБП','manufacturer':'UPS Battery Monitor','model':'Расчёт АКБ','entry_type':'service'}
    async def async_added_to_hass(self):
        self.async_on_remove(self.runtime.async_add_listener(self.async_write_ha_state))
    @property
    def native_value(self):return self.runtime.values.get(self.entity_description.key)
    @property
    def available(self):return self.native_value is not None
    @property
    def extra_state_attributes(self):return self.runtime.attributes.get(self.entity_description.key)
