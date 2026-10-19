from dataclasses import replace
import pytest
from custom_components.ups.accounting import integrate
from .helpers import *

def test_half_hour_signed_current():
    positive=integrate(sample(0,2),sample(1800,2),.95)
    negative=integrate(sample(0,-2),sample(1800,-2),.95)
    assert positive.charge_ah==pytest.approx(1)
    assert positive.delta_stored_ah==pytest.approx(.95)
    assert negative.discharge_wh==pytest.approx(12)
    assert negative.delta_stored_ah==pytest.approx(-1)

def test_zero_crossing_split():
    cross=integrate(sample(0,-2),sample(3600,2),.95)
    assert (cross.charge_ah,cross.discharge_ah,cross.delta_stored_ah)==pytest.approx((.5,.5,-.025))
    cross=integrate(sample(0,-2,10),sample(3600,2,14),1)
    assert (cross.charge_wh,cross.discharge_wh)==pytest.approx((7,5))

@pytest.mark.parametrize("end",[sample(0,2),sample(-5,2),sample(5,2,run_id="other"),sample(5,2,source_id="other")])
def test_boundaries_never_add_charge(end):
    assert integrate(sample(0,2),end,.95).charge_ah==0
