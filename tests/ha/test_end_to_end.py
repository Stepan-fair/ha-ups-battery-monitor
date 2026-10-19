import pytest
from custom_components.ups.models import Anchor
from .conftest import tick
from tests.unit.helpers import utc

async def test_restore_mid_discharge_keeps_totals_and_session(hass,freezer,runtime):
    await runtime.async_set_known_soc(Anchor(utc(),.8,'manual_estimate',False),expected_battery_id=runtime.state.config.battery_id)
    for t in range(0,61,5):await tick(hass,freezer,runtime,t)
    before=runtime.state
    entry=runtime.entry
    await hass.config_entries.async_reload(entry.entry_id)
    current=entry.runtime_data
    await tick(hass,freezer,current,240)
    for t in range(245,301,5):await tick(hass,freezer,current,t)
    assert current.state.discharge_ah_total==pytest.approx(before.discharge_ah_total+120/3600)
    assert current.state.active_session.session_id==before.active_session.session_id
    assert current.state.active_session.gap_s==180
    for t in range(305,341,5):await tick(hass,freezer,current,t,amps=2)
    for t in range(345,381,5):await tick(hass,freezer,current,t,amps=0)
    assert current.state.last_discharge.session_id==before.active_session.session_id
    assert current.state.last_charge is not None
    assert current.state.working_capacity is None
