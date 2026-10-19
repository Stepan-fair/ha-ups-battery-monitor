from dataclasses import replace
import pytest
from custom_components.ups.inputs import normalize
from custom_components.ups.profiles import initial_state,make_profile
from custom_components.ups.models import RawReading
from .helpers import *

def test_normalizes_units_and_sign():
    result=normalize(raw(10,amps="-250",current_unit="mA",volts="12000",voltage_unit="mV",readings={"temperature":RawReading("68","°F",utc(10)),"load_power":RawReading("0.1","kW",utc(10))}),source(sign=-1))
    assert result.sample.current_a==0.25
    assert result.sample.voltage_v==12
    assert result.sample.temperature_c==20
    assert result.sample.load_power_w==100

def test_fresh_constant_value():
    assert normalize(raw(10,reported_t=10,changed_t=0),source()).sample is not None

@pytest.mark.parametrize("r,issue",[(raw(16,reported_t=0),"stale"),(raw(0,reported_t=6),"future"),(raw(0,amps="unknown"),"invalid"),(raw(0,amps="unavailable"),"invalid"),(raw(0,amps="nan"),"invalid"),(raw(0,amps="inf"),"invalid"),(raw(0,current_unit=None),"unit"),(raw(16,readings={"voltage":RawReading("12","V",utc(0))}),"stale")])
def test_rejects_stale_nonfinite_and_saturation(r,issue):
    result=normalize(r,source())
    assert result.sample is None
    assert issue in result.issues

def test_physical_range_before_and_after_calibration():
    for s in [source(max_current_a=.8192),source(max_current_a=.8192,scale=.1),source(max_current_a=1,scale=2)]:
        assert "range" in normalize(raw(10,amps="0.8185"),s).issues

def test_optional_failure_preserves_accounting():
    result=normalize(raw(10,readings={"temperature":RawReading("nan","°C",utc(10))}),source())
    assert result.sample is not None
    assert "temperature_invalid" in result.issues

def test_profiles_do_not_assume_full():
    assert initial_state(profile()).remaining_charge_ah is None
    old=make_profile("flooded","smartec",battery_id="b",nominal_ah=125)
    assert old.source.max_current_a==pytest.approx(.8192)
    assert old.cutoff_v==10.5
    lfp=make_profile("lifepo4","meanwell",battery_id="b",nominal_ah=200)
    assert lfp.cutoff_v is None
    assert lfp.full_voltage_v is None
    assert lfp.peukert_k==1

def test_latched_binary_status_is_not_a_stale_measurement():
    result=normalize(raw(600,readings={"grid_failed":RawReading("on",None,utc(0))}),source())
    assert result.sample.grid_failed is True

def test_room_temperature_has_its_own_reporting_period():
    result=normalize(raw(600,readings={"temperature":RawReading("20","°C",utc(0))}),source())
    assert result.sample.temperature_c==20
    result=normalize(raw(901,readings={"temperature":RawReading("20","°C",utc(0))}),source())
    assert result.sample.temperature_c is None and 'temperature_stale' in result.issues
