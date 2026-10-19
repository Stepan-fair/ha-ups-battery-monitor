from dataclasses import replace
from pathlib import Path
import json
from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.ups.persistence import _encode
from tests.unit.helpers import profile,utc
from .conftest import tick


async def test_new_sensor_contract_and_separate_bms_diagnostics(hass,freezer,runtime):
    c=runtime.state.config
    await runtime.async_apply_config(replace(c,source=replace(c.source,
        battery_temperature_entity_id='sensor.batt_temp',
        min_cell_voltage_entity_id='sensor.cell_min',max_cell_voltage_entity_id='sensor.cell_max')))
    hass.states.async_set('sensor.batt_temp','15',{'unit_of_measurement':'°C'})
    hass.states.async_set('sensor.cell_min','3.2',{'unit_of_measurement':'V'})
    hass.states.async_set('sensor.cell_max','3.25',{'unit_of_measurement':'V'})
    for t in range(0,31,5):await tick(hass,freezer,runtime,t)
    assert hass.states.get('sensor.ups_cell_delta').state=='0.05'
    assert hass.states.get('sensor.ups_temperature').state=='15.0'
    assert hass.states.get('sensor.ups_equivalent_cycles').state!='unavailable'
    assert hass.states.get('sensor.ups_forecast_status').state=='no_estimate'
    assert hass.states.get('sensor.ups_time_to_cutoff').attributes['unit_of_measurement']=='s'
    assert hass.states.get('sensor.ups_calibration_status').state=='no_anchor'


async def test_meter_flow_waits_for_review_confirmation(hass,runtime):
    result=await hass.config_entries.options.async_init(runtime.entry.entry_id)
    result=await hass.config_entries.options.async_configure(result['flow_id'],{'next_step_id':'meter'})
    assert result['step_id']=='meter'
    before=runtime.state
    result=await hass.config_entries.options.async_configure(result['flow_id'],{
        'zero_raw_a':.02,'reference_raw_a':.52,'reference_a':-1,
        'zero_physically_verified':True,'range_physically_verified':True})
    assert result['step_id']=='meter_confirm' and runtime.state==before
    result=await hass.config_entries.options.async_configure(result['flow_id'],{'confirm':False})
    assert runtime.state==before and result['errors']
    result=await hass.config_entries.options.async_configure(result['flow_id'],{'confirm':True})
    assert result['type']=='create_entry'
    assert runtime.state.config.source.sign==-1
    assert runtime.store.load().state.meter_checked_at==utc(0)


async def test_runtime_loads_actual_v1_seed_and_checkpoint(hass,freezer):
    freezer.move_to(utc(65))
    payload=json.loads((Path(__file__).parents[1]/'fixtures/checkpoint-v1.json').read_text())
    entry=MockConfigEntry(domain='ups',title='old',data={'seed':payload['state']['config'],'initialized':True})
    entry.add_to_hass(hass)
    directory=Path(hass.config.path('.storage','ups',entry.entry_id))
    directory.mkdir(parents=True)
    (directory/'state.json').write_text(json.dumps(payload))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    runtime=entry.runtime_data
    assert runtime.state.config.battery_id=='battery-1'
    assert runtime.state.charge_ah_total==7.25 and runtime.state.passport.discharge_ah==3.5
    await hass.config_entries.async_unload(entry.entry_id)
    restored=json.loads((directory/'state.json').read_text())
    assert restored['version']==2 and restored['state']['remaining_charge_ah']==42.5
