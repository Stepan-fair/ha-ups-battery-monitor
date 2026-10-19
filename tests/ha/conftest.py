from dataclasses import replace
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from homeassistant.util import dt as dt_util
from custom_components.ups.persistence import _encode
from tests.unit.helpers import profile,utc

@pytest.fixture(autouse=True)
def custom_enabled(enable_custom_integrations):yield

@pytest.fixture
async def runtime(hass,freezer,monkeypatch):
    # Manual ticks control the clock; prevent the real scheduler from creating
    # an unrelated second timeline when the wall-clock freezer moves.
    handlers=[]
    def timer(hass,handler,interval):
        handlers.append(handler)
        def cancel():handlers.remove(handler)
        return cancel
    monkeypatch.setattr("custom_components.ups.runtime.async_track_time_interval",timer)
    freezer.move_to(utc(0))
    entry=MockConfigEntry(domain="ups",title="ИБП",data={"seed":_encode(profile())})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert len(handlers)==1
    yield entry.runtime_data
    if entry.state.name=="LOADED":
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

async def tick(hass,freezer,runtime,t,amps=-2,volts=12):
    freezer.move_to(utc(t))
    hass.states.async_set("sensor.current",str(amps),{"unit_of_measurement":"A"},force_update=True)
    hass.states.async_set("sensor.voltage",str(volts),{"unit_of_measurement":"V"},force_update=True)
    await runtime.async_tick(utc(t),float(t))
    await hass.async_block_till_done()
