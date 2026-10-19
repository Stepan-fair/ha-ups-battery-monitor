from dataclasses import replace
from unittest.mock import patch
import pytest
from custom_components.ups.persistence import CheckpointWriteError
from custom_components.ups.models import CapacityEstimate,Anchor
from .conftest import tick
from tests.unit.helpers import utc

async def test_profile_form_is_atomic(hass,freezer,runtime):
    old=runtime.state.config
    with patch.object(runtime.store,"save",side_effect=CheckpointWriteError("test full")):
        with pytest.raises(CheckpointWriteError):await runtime.async_apply_config(replace(old,nominal_ah=200))
    assert runtime.state.config==old
    assert runtime.store.load().state.config==old

async def test_source_change_breaks_interval_not_totals(hass,freezer,runtime):
    for t in range(0,21,5):await tick(hass,freezer,runtime,t)
    before=runtime.state.discharge_ah_total
    old=runtime.state.config
    await runtime.async_apply_config(replace(old,source=replace(old.source,source_id="second")))
    await tick(hass,freezer,runtime,25)
    assert runtime.state.discharge_ah_total==before
    await tick(hass,freezer,runtime,30)
    assert runtime.state.discharge_ah_total==pytest.approx(before+10/3600)

async def test_nominal_change_is_not_replacement(hass,freezer,runtime):
    await tick(hass,freezer,runtime,0,amps=2)
    old=runtime.state
    cap=CapacityEstimate(40,25,6.25,10.5,utc(),1)
    runtime.state=replace(runtime.state,working_capacity=cap)
    await runtime.async_apply_config(replace(old.config,nominal_ah=200))
    assert runtime.state.config.battery_id==old.config.battery_id
    assert runtime.state.working_capacity==cap
    assert runtime.state.charge_wh_total==old.charge_wh_total
    entry=runtime.entry
    await hass.config_entries.async_reload(entry.entry_id)
    assert entry.runtime_data.state.config.nominal_ah==200

async def test_new_battery_retires_old_learning(hass,freezer,runtime):
    for t in range(0,31,5):await tick(hass,freezer,runtime,t,amps=-2)
    old=runtime.state
    new=await runtime.async_new_battery(expected_battery_id=old.config.battery_id)
    assert runtime.state.config.battery_id==new!=old.config.battery_id
    assert runtime.state.working_capacity is None
    assert runtime.state.remaining_charge_ah is None
    assert runtime.state.discharge_wh_total==old.discharge_wh_total
    assert runtime.state.archives[-1].last_discharge.end_reason=="battery_replaced"
    assert runtime.state.last_discharge is None
    with pytest.raises(ValueError):await runtime.async_reset_learning(expected_battery_id=old.config.battery_id)

async def test_ups_change_keeps_health(hass,freezer,runtime):
    cap=CapacityEstimate(40,25,6.25,10.5,utc(),1)
    runtime.state=replace(runtime.state,working_capacity=cap,health_capacity=cap)
    await runtime.async_apply_config(replace(runtime.state.config,ups_profile="meanwell",cutoff_v=11.0))
    assert runtime.state.health_capacity==cap
    # A different cutoff changes the usable range, while the historical aging
    # observation remains available with its original reference conditions.
    assert runtime.state.working_capacity is None

async def test_missing_checkpoint_after_initialization_does_not_use_seed(hass,freezer,runtime):
    entry=runtime.entry
    await hass.config_entries.async_unload(entry.entry_id)
    for path in (runtime.store.current,runtime.store.previous):path.unlink(missing_ok=True)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.runtime_data.restore_error
    assert hass.states.get("sensor.ups_charge_wh_total").state=="unavailable"
