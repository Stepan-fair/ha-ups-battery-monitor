import asyncio
from dataclasses import replace
from unittest.mock import patch
import pytest
from custom_components.ups.persistence import CheckpointWriteError
from .conftest import tick
from tests.unit.helpers import utc

async def test_only_primary_source_is_integrated(hass,freezer,runtime):
    await tick(hass,freezer,runtime,0)
    before=runtime.state.discharge_ah_total
    for i in range(100):hass.states.async_set("sensor.secondary_bms_current",str(i),{"unit_of_measurement":"A"})
    await tick(hass,freezer,runtime,5)
    assert runtime.state.discharge_ah_total==pytest.approx(before+10/3600)

async def test_tick_reads_fresh_unchanged_state(hass,freezer,runtime):
    for t in range(0,61,5):await tick(hass,freezer,runtime,t)
    assert runtime.state.discharge_ah_total==pytest.approx(120/3600)
    assert len(runtime.state.minute_samples)==13

async def test_delayed_ticks_do_not_overlap(hass,freezer,runtime):
    await tick(hass,freezer,runtime,0)
    freezer.move_to(utc(5))
    hass.states.async_set("sensor.current","-2",{"unit_of_measurement":"A"},force_update=True)
    hass.states.async_set("sensor.voltage","12",{"unit_of_measurement":"V"},force_update=True)
    gate=asyncio.Event();entered=asyncio.Event()
    original=runtime._checkpoint_locked
    async def delayed():entered.set();await gate.wait();return await original()
    runtime._last_checkpoint_mono=-30
    with patch.object(runtime,"_checkpoint_locked",delayed):
        a=asyncio.create_task(runtime.async_tick(utc(5),5));await entered.wait()
        b=asyncio.create_task(runtime.async_tick(utc(5),5));await b
        gate.set();await a
    assert runtime.state.discharge_ah_total==pytest.approx(10/3600)

async def test_unload_cancels_timers_and_flushes(hass,freezer,runtime):
    for t in range(0,31,5):await tick(hass,freezer,runtime,t)
    before=runtime.state.generation
    await runtime.async_stop()
    assert runtime._unsubscribe is None
    assert runtime.state.generation>before
    assert runtime.store.load().state.discharge_ah_total==runtime.state.discharge_ah_total

async def test_write_failure_is_visible(hass,freezer,runtime):
    with patch.object(runtime.store,"save",side_effect=CheckpointWriteError("test full")):
        await tick(hass,freezer,runtime,0)
    assert "storage_error" in hass.states.get("sensor.ups_data_quality").attributes["issues"]
    await tick(hass,freezer,runtime,30)
    assert "storage_error" not in runtime.state.issues

async def test_noncritical_publication_is_bounded(hass,freezer,runtime):
    for t in range(0,31,5):await tick(hass,freezer,runtime,t,amps=.032)
    before=hass.states.get("sensor.ups_charge_ah_total")
    for t in range(35,60,5):await tick(hass,freezer,runtime,t,amps=.032)
    assert hass.states.get("sensor.ups_charge_ah_total").last_updated==before.last_updated
    await tick(hass,freezer,runtime,60,amps=.032)
    assert hass.states.get("sensor.ups_last_sample_at").state.startswith("2026-10-19T00:01:00")

async def test_checkpoint_after_timestamped_sample(hass,freezer,runtime):
    await tick(hass,freezer,runtime,0)
    receipt=await runtime.async_checkpoint()
    assert receipt.generation>=2

async def test_regular_ha_stop_flushes_checkpoint(hass,freezer,runtime):
    await tick(hass,freezer,runtime,0)
    before=runtime.state.generation
    await hass.async_stop()
    assert runtime.store.load().state.generation>before
