"""Independent review reproductions, with literal physical expectations."""
from dataclasses import replace
from pathlib import Path
import hashlib,json
import pytest
from custom_components.ups.models import EngineState,PredictionError,Session
from custom_components.ups.forecast import forecast
from custom_components.ups.prediction import signature,validation_summary
from custom_components.ups.persistence import decode_state,_encode
from custom_components.ups.evidence import verify_meter
from custom_components.ups.engine import advance
from .helpers import profile,source,sample,reading,utc


@pytest.mark.parametrize('power,last_current,last_at',[(96,2,0),(None,None,None),(None,2,-700000)])
def test_historical_errors_require_the_forecasts_actual_current_load(power,last_current,last_at):
    c=profile(chemistry='lifepo4',nominal_ah=100,peukert_k=1,load_is_complete=True)
    s=replace(EngineState(c),mode='idle',remaining_charge_ah=10,
              last_verified_discharge_a=last_current,last_verified_discharge_at=utc(last_at) if last_at is not None else None,
              last_sample=sample(20000,.1,12,temperature_c=25,load_power_w=power))
    errors=tuple(PredictionError(str(i),utc(0),utc(3600),3600,3600,signature(c),2,25) for i in range(3))
    s=replace(s,prediction_errors=errors)
    assert validation_summary(s,now=utc(20000))['cycles']==0


def test_v1_rejected_session_does_not_refresh_an_unrelated_retained_load():
    data=json.loads((Path(__file__).parents[1]/'fixtures/checkpoint-v1.json').read_text())
    data['state']['last_verified_discharge_a']=2
    recent=Session('recent','battery-1','discharging',utc(800000),utc(801000),
                   measured_s=900,gap_s=100,discharge_ah=.5,end_reason='grid_restored',quality=('data_gap',))
    data['state']['last_discharge']=_encode(recent)
    body={k:v for k,v in data.items() if k!='checksum'}
    data['checksum']=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    s=decode_state(data)
    assert s.last_verified_discharge_at is None
    f=forecast(replace(s,mode='idle'),sample(801005,.1),now=utc(801005))
    assert f.time_remaining_s is None and 'load_expired' in f.quality


@pytest.mark.parametrize('zero',[-.8192,.8192])
def test_clipped_zero_cannot_verify_or_reconfigure_meter(zero):
    s=EngineState(replace(profile(),source=source(min_current_a=-.8192,max_current_a=.8192)))
    with pytest.raises(ValueError):
        verify_meter(s,zero_raw_a=zero,reference_raw_a=.2,reference_a=1,confirmed=True,now=utc())
    assert s.meter_checked_at is None and s.config.source.scale==1


def test_new_partial_discharge_replaces_old_confirmed_cutoff_status():
    s=EngineState(profile(mode_hold_s=0))
    for t,amps,volts,grid in [(0,-1,10.5,True),(5,-1,10.5,True),(10,1,13,False),
                              (15,1,13,False),(20,-1,12,True),(25,-1,12,True),(30,.1,13,False)]:
        s=advance(s,reading(t,amps,volts,grid_failed=grid)).state
    assert s.last_discharge.end_reason=='grid_restored'
    assert s.termination_status=='grid_restored'
    assert s.termination_at==utc(30)
