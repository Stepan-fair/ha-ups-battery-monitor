"""Executed only as a child pytest process with disposable HA data."""
import json,os
from pathlib import Path
from pytest_homeassistant_custom_component.common import MockConfigEntry
from homeassistant.core import callback
from custom_components.ups.models import Anchor
from custom_components.ups.profiles import initial_state
from custom_components.ups.persistence import _encode
from tests.unit.helpers import profile,utc
from .conftest import tick

async def test_power_worker(hass,freezer,monkeypatch):
    root=Path(os.environ['UPS_TEST_POWER_DIR']).resolve()
    assert root.is_relative_to(Path('/tmp'))
    phase=os.environ['UPS_TEST_POWER_PHASE']
    hass.config.config_dir=str(root/'ha')
    Path(hass.config.config_dir).mkdir(exist_ok=True)
    monkeypatch.setattr('custom_components.ups.runtime.async_track_time_interval',lambda *args:lambda:None)
    calls=[]
    @callback
    def service(event):calls.append(event.data)
    hass.bus.async_listen('call_service',service)
    freezer.move_to(utc(0))
    data={'seed':_encode(profile())}
    if phase=='restore':data['initialized']=True
    entry=MockConfigEntry(domain='ups',title='Test power loss',entry_id='powerentry',data=data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    runtime=entry.runtime_data
    if phase=='write':
        await runtime.async_set_known_soc(Anchor(utc(),.8,'manual_estimate',False),expected_battery_id=runtime.state.config.battery_id)
        for t in range(0,61,5):await tick(hass,freezer,runtime,t)
        await runtime.async_checkpoint()
        before={'total':runtime.state.discharge_ah_total,'session_id':runtime.state.active_session.session_id}
        with (root/'before.json').open('w') as f:json.dump(before,f);f.flush();os.fsync(f.fileno())
        # Abruptly stop this child, without any integration unload or HA stop hook.
        os._exit(77)
    before=json.loads((root/'before.json').read_text())
    await tick(hass,freezer,runtime,240)
    for t in range(245,301,5):await tick(hass,freezer,runtime,t)
    result={'session_preserved':runtime.state.active_session.session_id==before['session_id'],'gap_s':runtime.state.active_session.gap_s,'measured_added_ah':runtime.state.discharge_ah_total-before['total'],'power_service_calls':calls}
    (root/'worker-result.json').write_text(json.dumps(result))
    for t in range(305,341,5):await tick(hass,freezer,runtime,t,amps=2)
    for t in range(345,381,5):await tick(hass,freezer,runtime,t,amps=0)
    assert runtime.state.last_discharge.session_id==before['session_id']
    assert runtime.state.last_charge is not None
    assert runtime.state.working_capacity is None
