"""Explicit v1 additions only; missing old fields and unknown fields still fail."""
from copy import deepcopy

SOURCE_ADDITIONS = {key:None for key in (
    'battery_temperature_entity_id','max_cell_voltage_entity_id',
    'min_cell_index_entity_id','max_cell_index_entity_id','charge_mosfet_entity_id',
    'discharge_mosfet_entity_id','protection_reason_entity_id','link_quality_entity_id')}
SOURCE_ADDITIONS['bms_interval_s']=30.0
SAMPLE_ADDITIONS={key:None for key in ('ambient_temperature_c','temperature_is_ambient',
    'max_cell_voltage_v','min_cell_index','max_cell_index','charge_mosfet',
    'discharge_mosfet','protection_reason','link_quality_percent')}
CONFIG_ADDITIONS = {'load_max_age_s':604800.0, 'calibration_max_age_s':2592000.0}
PASSPORT = {'charge_ah':0.0,'discharge_ah':0.0,'charge_wh':0.0,'discharge_wh':0.0,
            'min_voltage_v':None,'max_charge_a':0.0,'max_discharge_a':0.0,
            'full_count':0,'last_full_at':None,'monitoring_started_at':None,
            'history_partial':True}
STATE_ADDITIONS = {'capacity_history':[], 'last_verified_discharge_at':None,
                   'termination_status':'unknown','termination_at':None,
                   'meter_checked_at':None,'prediction_points':[],'prediction_errors':[]}

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
    if result['last_sample']:result['last_sample'].update(SAMPLE_ADDITIONS)
    for reading in result['minute_samples']:
        if reading['sample']:reading['sample'].update(SAMPLE_ADDITIONS)
    session=result['last_discharge'];retained=result['last_verified_discharge_a']
    # v1 may retain an older clean load when the latest discharge was rejected.
    # Only a clean matching session can establish the retained value's age.
    if session and retained is not None and not session['gap_s'] and not session['quality'] and session['measured_s']>=30 and not result['anchor_has_saturation']:
        measured=session['discharge_ah']*3600/session['measured_s']
        if abs(measured-retained)<=1e-9*max(1,abs(retained)):
            result['last_verified_discharge_at']=session['ended_at']
    for archive in result['archives']:
        archive['config'] = upgrade_config(archive['config'])
        archive['passport'] = deepcopy(PASSPORT)
        archive['capacity_history'] = []
    return result
