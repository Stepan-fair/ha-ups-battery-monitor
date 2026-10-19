"""Pure and intentionally narrow dashboard patch; no direct .storage writes."""
from copy import deepcopy
import json

LEGACY_BADGES={'input_boolean.rabotal_ot_ibp','input_number.vremia_raboty_ot_ibp'}

def patch_ibp_view(config: dict,replacement: dict) -> dict:
    matches=[i for i,v in enumerate(config.get('views',[])) if v.get('path')=='ibp']
    if len(matches)!=1:raise ValueError('expected exactly one ibp view')
    if replacement.get('path')!='ibp' or not isinstance(replacement.get('sections'),list):raise ValueError('invalid replacement')
    old=config['views'][matches[0]]
    if old.get('type','sections')!='sections':raise ValueError('ibp view is not sections; explicit conversion required')
    serialized=json.dumps(old)
    if 'sensor.ups_' in serialized:raise ValueError('UPS block already present; refuse duplicate insertion')
    result=deepcopy(config);view=result['views'][matches[0]]
    view['sections']=deepcopy(replacement['sections'])+view.get('sections',[])
    badges=[b for b in view.get('badges',[]) if (b if isinstance(b,str) else b.get('entity')) not in LEGACY_BADGES]
    view['badges']=deepcopy(replacement.get('badges',[]))+badges
    return result
