from .conftest import tick

async def test_sensor_contract_units_and_availability(hass,freezer,runtime):
    await tick(hass,freezer,runtime,0)
    wh=hass.states.get("sensor.ups_charge_wh_total")
    assert wh.attributes['state_class']=='total_increasing'
    assert wh.attributes['device_class']=='energy'
    ah=hass.states.get("sensor.ups_discharge_ah_total")
    assert 'device_class' not in ah.attributes
    assert ah.attributes['unit_of_measurement']=='Ah'
    assert hass.states.get("sensor.ups_expected_empty_at").attributes['device_class']=='timestamp'
    assert hass.states.get("sensor.ups_soc").state=='unavailable'
    assert 'state_class' not in hass.states.get("sensor.ups_charge_duration").attributes
    assert hass.states.get("sensor.ups_battery_mode").attributes['device_class']=='enum'

async def test_graph_uses_selected_normalized_current(hass,freezer,runtime):
    await tick(hass,freezer,runtime,0)
    assert hass.states.get("sensor.ups_current").state=="-2.0"
    assert hass.states.get("sensor.ups_current").attributes['unit_of_measurement']=='A'
    assert hass.states.get("sensor.ups_voltage").state=="12.0"

async def test_latched_grid_remains_visible_when_current_is_clipped(hass,freezer,runtime):
    from dataclasses import replace
    from tests.unit.helpers import utc
    await runtime.async_apply_config(replace(runtime.state.config,source=replace(runtime.state.config.source,grid_failed_entity_id="binary_sensor.grid_fault")))
    freezer.move_to(utc(0))
    hass.states.async_set("binary_sensor.grid_fault","on")
    await tick(hass,freezer,runtime,0,amps=20)
    await tick(hass,freezer,runtime,60,amps=20)
    assert hass.states.get("binary_sensor.ups_on_battery").state=="on"
