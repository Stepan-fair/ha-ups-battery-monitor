from dataclasses import replace
import pytest
from custom_components.ups.profiles import validate_profile,profile_form_data
from custom_components.ups.persistence import _encode
from custom_components.ups.models import Anchor
from tests.unit.helpers import profile,utc

async def test_initial_profile_flow(hass):
    result=await hass.config_entries.flow.async_init("ups",context={"source":"user"})
    assert result['type']=='form'
    result=await hass.config_entries.flow.async_configure(result['flow_id'],{"chemistry":"lifepo4","ups_profile":"meanwell","nominal_ah":200,"name":"LiFePO4"})
    assert result['step_id']=='profile'
    data=profile_form_data(profile(chemistry="lifepo4",nominal_ah=200,nominal_voltage=12.8,cutoff_v=None,peukert_k=1))
    result=await hass.config_entries.flow.async_configure(result['flow_id'],data)
    assert result['type']=='create_entry'
    assert result['data']['seed']['chemistry']=='lifepo4'

async def test_maintenance_needs_explicit_confirmation(hass,runtime):
    entry=runtime.entry;before=runtime.state
    result=await hass.config_entries.options.async_init(entry.entry_id)
    result=await hass.config_entries.options.async_configure(result['flow_id'],{"next_step_id":"new_battery"})
    assert result['step_id']=='confirm'
    assert runtime.state==before
    result=await hass.config_entries.options.async_configure(result['flow_id'],{"confirm":False})
    assert runtime.state==before
    assert result['errors']['base']=='confirmation_required'
    result=await hass.config_entries.options.async_configure(result['flow_id'],{"confirm":True})
    assert result['type']=='create_entry'
    assert runtime.state.config.battery_id!=before.config.battery_id
    assert entry.options=={}

def test_missing_lfp_limits_disable_auto_full():
    c=validate_profile(_encode(profile(chemistry="lifepo4",cutoff_v=None,full_voltage_v=None,tail_current_a=None)))
    assert c.cutoff_v is None and c.full_voltage_v is None

@pytest.mark.parametrize('change',[{"nominal_ah":0},{"reserve":1},{"charge_efficiency":0},{"source":{"max_current_a":0}},{"source":{"sign":0}},{"temperature_factors":[[25,1],[0,.8]]}])
def test_invalid_profile_is_rejected(change):
    data=_encode(profile())
    if 'source' in change:data['source'].update(change.pop('source'))
    data.update(change)
    with pytest.raises(ValueError):validate_profile(data)
