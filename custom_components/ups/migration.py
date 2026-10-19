"""Explicit v1 additions only; missing old fields and unknown fields still fail."""
from copy import deepcopy

SOURCE_ADDITIONS = {}
CONFIG_ADDITIONS = {'load_max_age_s':604800.0, 'calibration_max_age_s':2592000.0}
PASSPORT = {'charge_ah':0.0,'discharge_ah':0.0,'charge_wh':0.0,'discharge_wh':0.0,
            'min_voltage_v':None,'max_charge_a':0.0,'max_discharge_a':0.0,
            'full_count':0,'last_full_at':None,'monitoring_started_at':None,
            'history_partial':True}
STATE_ADDITIONS = {'capacity_history':[], 'last_verified_discharge_at':None,
                   'termination_status':'unknown','termination_at':None,
                   'meter_checked_at':None}

def upgrade_config(value):
    result = deepcopy(value)
    for key, default in CONFIG_ADDITIONS.items():result.setdefault(key, deepcopy(default))
    for key, default in SOURCE_ADDITIONS.items():result['source'].setdefault(key, deepcopy(default))
    return result

def upgrade_v1(value):
    result = deepcopy(value)
    result['config'] = upgrade_config(result['config'])
    for key, default in STATE_ADDITIONS.items():result[key] = deepcopy(default)
    passport = deepcopy(PASSPORT)
    if not result['archives']:
        for key in ('charge_ah','discharge_ah','charge_wh','discharge_wh'):
            passport[key] = result[key+'_total']
    result['passport'] = passport
    if result['last_discharge']:
        result['last_verified_discharge_at'] = result['last_discharge']['ended_at']
    for archive in result['archives']:
        archive['config'] = upgrade_config(archive['config'])
        archive['passport'] = deepcopy(PASSPORT)
        archive['capacity_history'] = []
    return result
