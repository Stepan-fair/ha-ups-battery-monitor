from copy import deepcopy
import json
import pytest
from tools.dashboard_patch import patch_ibp_view

def original():
    return {'title':'Техник','views':[{'path':'other','cards':[{'type':'entities','entities':['sensor.other']} ]},{'path':'ibp','type':'sections','max_columns':4,'icon':'mdi:power','badges':['input_boolean.rabotal_ot_ibp',{'entity':'input_number.vremia_raboty_ot_ibp'},'sensor.ibp_akb_tok'],'sections':[{'type':'grid','cards':[{'type':'entities','entities':['sensor.router','sensor.camera']}]}]}]}

def replacement():return {'path':'ibp','sections':[{'type':'grid','cards':[{'type':'entities','entities':['sensor.ups_soc']}]}]}

def test_dashboard_patch_preserves_other_views_and_consumers():
    old=original();copy=deepcopy(old);patched=patch_ibp_view(old,replacement())
    assert patched is not old and old==copy
    assert patched['views'][0]==old['views'][0]
    assert patched['views'][1]['sections'][-1]==old['views'][1]['sections'][0]
    assert patched['views'][1]['icon']=='mdi:power'
    assert patched['views'][1]['badges']==['sensor.ibp_akb_tok']
    assert 'input_boolean.rabotal_ot_ibp' not in json.dumps(patched)
    with pytest.raises(ValueError):patch_ibp_view(patched,replacement())

@pytest.mark.parametrize('views',[[],[{'path':'ibp'},{'path':'ibp'}]])
def test_ambiguous_or_missing_view_is_rejected(views):
    with pytest.raises(ValueError):patch_ibp_view({'views':views},replacement())
