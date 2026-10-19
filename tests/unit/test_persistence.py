from dataclasses import replace
from pathlib import Path
import errno,json,os,subprocess,sys
import pytest
from custom_components.ups.persistence import *
from custom_components.ups.engine import resume,advance,set_known_soc
from custom_components.ups.profiles import initial_state
from .helpers import *

def checkpoint_state():
    return run_constant(set_known_soc(initial_state(profile()),Anchor(utc(),1,"manual",False)).state,seconds=60,amps=-2)

def test_roundtrip_unrounded_state_and_minute_buffer(tmp_path):
    store=CheckpointStore(tmp_path,"entry1");s=checkpoint_state()
    receipt=store.save(s);result=store.load()
    assert result.state==replace(s,generation=1)
    assert len(result.state.minute_samples)==13
    assert receipt.generation==1
    assert decode_state(encode_state(s,generation=2)).generation==2

def test_corrupt_current_restores_previous(tmp_path):
    store=CheckpointStore(tmp_path,"entry1");s=checkpoint_state()
    first=store.save(s);store.save(replace(s,generation=first.generation,discharge_ah_total=2))
    (tmp_path/'entry1/state.json').write_text('{bad')
    result=store.load()
    assert result.recovered_previous
    assert result.state.discharge_ah_total==s.discharge_ah_total
    store.save(result.state)
    (tmp_path/'entry1/state.json').write_text('bad again')
    assert store.load().state.discharge_ah_total==s.discharge_ah_total

def test_disk_full_is_reported(tmp_path,monkeypatch):
    store=CheckpointStore(tmp_path,"entry1");store.save(checkpoint_state())
    def full(*a,**kw):raise OSError(errno.ENOSPC,"test disk full")
    monkeypatch.setattr(os,"fsync",full)
    with pytest.raises(CheckpointWriteError):store.save(replace(checkpoint_state(),generation=1))
    assert store.load().state.generation==1

@pytest.mark.parametrize("damage",["both","checksum","nan","field","version"])
def test_invalid_checkpoint_is_never_silently_reset(tmp_path,damage):
    store=CheckpointStore(tmp_path,"entry1");store.save(checkpoint_state());f=tmp_path/'entry1/state.json'
    data=json.loads(f.read_text())
    if damage=="both":f.write_text('{')
    else:
        if damage=="checksum":data['checksum']='0'*64
        if damage=="nan":data['state']['charge_ah_total']=float('nan')
        if damage=="field":del data['state']['config']['battery_id']
        if damage=="version":data['version']=999
        f.write_text(json.dumps(data))
    assert store.load().state is None
    with pytest.raises(CheckpointWriteError):store.save(checkpoint_state())

@pytest.mark.parametrize("gap",[180,181])
def test_resume_does_not_integrate_three_minutes(tmp_path,gap):
    store=CheckpointStore(tmp_path,"entry1");store.save(checkpoint_state());s=store.load().state
    s=advance(resume(s,run_id="r2"),reading(60+gap,-2,run_id="r2")).state
    assert s.discharge_ah_total==pytest.approx(120/3600)
    assert s.active_session.gap_s==gap
    assert ("long_gap" in s.issues)==(gap>180)

@pytest.mark.parametrize("entry",["../outside","/absolute","a/b","a\\b",""])
def test_entry_path_cannot_escape_root(tmp_path,entry):
    with pytest.raises(ValueError):CheckpointStore(tmp_path,entry)

@pytest.mark.parametrize("stage",[1,2,3,4])
def test_kill_between_rename_steps(tmp_path,stage):
    store=CheckpointStore(tmp_path,"entry1");store.save(checkpoint_state())
    script=Path(__file__).with_name('crash_writer.py')
    r=subprocess.run([sys.executable,str(script),str(tmp_path),str(stage)],capture_output=True,text=True)
    assert r.returncode==77,r.stderr
    restored=store.load().state
    assert restored is not None
    assert restored.discharge_ah_total in (120/3600,2)
    assert restored.generation in (1,2)
