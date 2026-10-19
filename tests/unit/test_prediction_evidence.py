from dataclasses import replace
import pytest
from custom_components.ups.models import EngineState, Session, Anchor, RawReading
from custom_components.ups.inputs import normalize
from custom_components.ups.engine import advance, reconfigure
from custom_components.ups.forecast import forecast
from .helpers import profile, source, sample, reading, raw, utc


def test_battery_temperature_precedes_room_and_missing_bms_does_not_stop_accounting():
    c=source(battery_temperature_entity_id='sensor.battery_temp',max_cell_voltage_entity_id='sensor.max_cell')
    r=raw(60,readings={'temperature':RawReading('7','°C',utc(60)),
                       'battery_temperature':RawReading('15','°C',utc(60)),
                       'min_cell_voltage':RawReading('3200','mV',utc(60)),
                       'max_cell_voltage':RawReading('3.25','V',utc(60))})
    v=normalize(r,c)
    assert v.sample.temperature_c==15
    assert v.sample.ambient_temperature_c==7
    assert v.sample.temperature_is_ambient is False
    assert v.sample.max_cell_voltage_v==3.25
    r=replace(r,readings={**r.readings,'battery_temperature':RawReading('unavailable','°C',utc(60))})
    v=normalize(r,c)
    assert v.sample is not None and v.sample.temperature_c==7
    assert v.sample.temperature_is_ambient is True
    assert 'battery_temperature_invalid' in v.issues


def test_bms_cell_conflict_does_not_corrupt_primary_and_soc_stays_separate():
    c=source(max_cell_voltage_entity_id='sensor.max_cell')
    v=normalize(raw(60,readings={'min_cell_voltage':RawReading('3.3','V',utc(60)),
                               'max_cell_voltage':RawReading('3.2','V',utc(60)),
                               'bms_soc':RawReading('99','%',utc(60))}),c)
    assert v.sample is not None
    assert v.sample.max_cell_voltage_v is None
    assert 'cell_order' in v.issues
    s=advance(EngineState(replace(profile(),source=c)),v).state
    assert s.remaining_charge_ah is None


def test_charge_mosfet_off_prevents_false_full_and_charge_eta():
    p=profile(chemistry='lifepo4',full_voltage_v=14,tail_current_a=.5,full_hold_s=5)
    s=replace(EngineState(p),remaining_charge_ah=50,mode='charging')
    for t in (0,5,10):s=advance(s,reading(t,.1,14.2,charge_mosfet=False,charge_stage='constant_current')).state
    assert not s.full_latched
    assert forecast(s,s.last_sample,now=utc(10)).time_to_full_s is None


def test_meter_two_point_calibration_is_explicit_and_does_not_invent_soc():
    from custom_components.ups.evidence import verify_meter
    s=replace(EngineState(profile()),charge_ah_total=12)
    with pytest.raises(ValueError):verify_meter(s,zero_raw_a=.02,reference_raw_a=.52,reference_a=1,confirmed=False,now=utc(10))
    s=verify_meter(s,zero_raw_a=.02,reference_raw_a=.52,reference_a=-1,confirmed=True,now=utc(10)).state
    assert s.config.source.scale==pytest.approx(2)
    assert s.config.source.offset_a==pytest.approx(.04)
    assert s.config.source.sign==-1
    assert s.meter_checked_at==utc(10)
    assert s.remaining_charge_ah is None and s.charge_ah_total==12


def test_primary_calibration_change_invalidates_learned_capacity():
    from custom_components.ups.models import CapacityEstimate
    cap=CapacityEstimate(80,25,2,10.5,utc(),2)
    s=replace(EngineState(profile()),working_capacity=cap,health_capacity=cap,remaining_charge_ah=40)
    s=reconfigure(s,replace(s.config,source=replace(s.config.source,scale=2)),now=utc(10)).state
    assert s.working_capacity is None and s.health_capacity is None
    assert s.remaining_charge_ah is None


def test_empirical_envelope_requires_three_distinct_clean_outcomes():
    from custom_components.ups.models import PredictionError
    from custom_components.ups.prediction import validation_summary, signature
    s=replace(EngineState(profile()),last_sample=sample(20000,-2,temperature_c=25),smoothed_discharge_a=2)
    key=signature(s.config)
    def error(session,predicted,actual):
        return PredictionError(session,utc(100),utc(100+actual),predicted,actual,key,2,25)
    same=tuple(error('one',3600,3000) for _ in range(3))
    s=replace(s,prediction_errors=same)
    assert validation_summary(s,now=utc(20000))['cycles']==1
    assert validation_summary(s,now=utc(20000))['lower_factor'] is None
    s=replace(s,prediction_errors=(error('one',3600,3000),error('two',3000,3000),error('three',2400,3000)))
    result=validation_summary(s,now=utc(20000))
    assert result['cycles']==3
    assert result['mean_absolute_error_s']==pytest.approx(400)
    assert result['lower_factor']==pytest.approx(1/1.2)
    assert result['upper_factor']==pytest.approx(1/.8)
    changed=replace(s,config=replace(s.config,cutoff_v=11))
    assert validation_summary(changed,now=utc(20000))['cycles']==0


@pytest.mark.parametrize('reason,gap,expected',[('grid_restored',0,0),('confirmed_cutoff',30,0),('confirmed_cutoff',0,1)])
def test_only_observed_clean_cutoff_validates_prediction(reason,gap,expected):
    from custom_components.ups.models import PredictionPoint
    from custom_components.ups.prediction import finish_predictions,signature
    s=EngineState(profile())
    session=Session('d1',s.config.battery_id,'discharging',utc(0),utc(3600),measured_s=3600-gap,gap_s=gap,end_reason=reason)
    point=PredictionPoint('d1',utc(0),4000,signature(s.config),2,25)
    s=replace(s,last_discharge=session,prediction_points=(point,))
    s=finish_predictions(s,session)
    assert len(s.prediction_errors)==expected
    assert s.prediction_points==()


def test_calibration_age_and_bms_difference_are_diagnostic_only():
    from custom_components.ups.prediction import assessment
    p=profile(calibration_max_age_s=3600)
    s=replace(EngineState(p),remaining_charge_ah=62.5,last_anchor=Anchor(utc(0),1,'auto_full',True),
              last_sample=sample(4000,-2,bms_soc_percent=90),mode='discharging',smoothed_discharge_a=2)
    f=forecast(s,s.last_sample,now=utc(4000))
    a=assessment(s,f,now=utc(4000))
    assert 'calibration_due' in a['reasons']
    assert a['bms_difference_percent']==40
    assert f.soc_percent==50


def test_real_reducer_records_accuracy_only_after_observed_cutoff():
    from custom_components.ups.engine import set_known_soc
    from custom_components.ups.prediction import validation_summary
    p=profile(chemistry='lifepo4',nominal_ah=2,peukert_k=1,mode_hold_s=0)
    s=set_known_soc(EngineState(p),Anchor(utc(0),1,'test_independent',True)).state
    for t in range(0,3601,5):
        s=advance(s,reading(t,-2,10.5 if t>=3595 else 12.8,temperature_c=25)).state
    assert s.termination_status=='confirmed_cutoff'
    assert len(s.prediction_errors)>=1
    assert validation_summary(s,now=utc(3600))['cycles']==1
    assert validation_summary(s,now=utc(3600))['mean_absolute_error_s']<10


def test_replay_uses_measured_intervals_and_never_bridges_gaps(tmp_path):
    from tools.replay import replay
    trace=tmp_path/'trace.csv'
    trace.write_text('timestamp,current_a,voltage_v,temperature_c\n'
                     '2026-10-19T00:00:00+00:00,-2,12,25\n'
                     '2026-10-19T00:00:05+00:00,-2,12,25\n'
                     '2026-10-19T00:05:00+00:00,-2,12,25\n')
    s=replay(profile(),trace)
    assert s.discharge_ah_total==pytest.approx(2*5/3600)
    assert s.passport.discharge_ah==pytest.approx(2*5/3600)
    assert s.has_gap and not s.prediction_errors
