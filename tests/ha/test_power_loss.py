import os,subprocess,sys,json
from pathlib import Path
import pytest
from .conftest import tick

async def test_recovery_from_previous_generation_in_real_ha(hass,freezer,runtime):
    for t in range(0,31,5):await tick(hass,freezer,runtime,t)
    await runtime.async_checkpoint()
    previous=runtime.store.load().state
    await tick(hass,freezer,runtime,35)
    await runtime.async_checkpoint()
    entry=runtime.entry
    # Discard only the temporary test runtime; never shut down production HA.
    await hass.config_entries.async_unload(entry.entry_id)
    runtime.store.current.write_text('{corrupt test data')
    assert await hass.config_entries.async_setup(entry.entry_id)
    restored=entry.runtime_data
    assert restored.state.discharge_ah_total>=previous.discharge_ah_total
    assert restored.state.has_gap
    assert restored.state.active_session.session_id==previous.active_session.session_id

def test_abrupt_real_ha_worker_process_restores(tmp_path):
    env=os.environ.copy();env['UPS_TEST_POWER_DIR']=str(tmp_path)
    worker=Path(__file__).with_name('power_worker.py')
    first=subprocess.run([sys.executable,'-m','pytest',str(worker),'-q','-p','no:cacheprovider'],env={**env,'UPS_TEST_POWER_PHASE':'write'},stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    assert first.returncode==77,first.stdout
    second=subprocess.run([sys.executable,'-m','pytest',str(worker),'-q','-p','no:cacheprovider'],env={**env,'UPS_TEST_POWER_PHASE':'restore'},stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    assert second.returncode==0,second.stdout
    result=json.loads((tmp_path/'worker-result.json').read_text())
    assert result['session_preserved'] and result['gap_s']==180
    assert result['measured_added_ah']==pytest.approx(120/3600)
    assert result['power_service_calls']==[]
