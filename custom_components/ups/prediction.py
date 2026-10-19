"""Bounded forecast evidence; observed error envelopes are not probabilities."""
from dataclasses import replace
from hashlib import sha256
import json
from .models import PredictionPoint,PredictionError


def electrical_signature(source):
    return tuple(getattr(source,key) for key in ('source_id','current_entity_id','voltage_entity_id','sign','scale','offset_a','min_current_a','max_current_a'))


def signature(config):
    fields=('battery_id','chemistry','nominal_ah','nominal_voltage','ups_profile','cutoff_v','charge_efficiency','peukert_k','temperature_factors')
    body=[getattr(config,k) for k in fields]+[electrical_signature(config.source)]
    return sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()[:24]


def finish_predictions(state,session):
    errors=list(state.prediction_errors)
    clean=session.end_reason=='confirmed_cutoff' and session.gap_s==0 and not session.quality
    if clean:
        for point in state.prediction_points:
            if point.session_id!=session.session_id or point.signature!=signature(state.config):continue
            actual=(session.ended_at-point.utc).total_seconds()
            if actual>=60 and point.predicted_s>0:
                errors.append(PredictionError(point.session_id,point.utc,session.ended_at,point.predicted_s,actual,point.signature,point.load_a,point.temperature_c))
    return replace(state,prediction_points=(),prediction_errors=tuple(errors[-192:]))


def track_predictions(old,state,sample):
    if state.last_discharge is not None and state.last_discharge!=old.last_discharge:
        state=finish_predictions(state,state.last_discharge)
    if state.anchor_has_gap or sample is None or state.restored:
        return replace(state,prediction_points=())
    session=state.active_session
    if sample is None or state.mode!='discharging' or session is None or session.gap_s or state.usable_empty:return state
    from .forecast import forecast
    f=forecast(state,sample,now=sample.utc)
    if f.time_to_cutoff_s is None or f.time_to_cutoff_s<=0:return state
    points=state.prediction_points
    if points and (sample.utc-points[-1].utc).total_seconds()<900:return state
    point=PredictionPoint(session.session_id,sample.utc,f.time_to_cutoff_s,signature(state.config),state.smoothed_discharge_a or -sample.current_a,sample.temperature_c)
    return replace(state,prediction_points=(points+(point,))[-32:])


def validation_summary(state,*,now):
    eligible={}
    from .forecast import load_context
    current,_,_=load_context(state,state.last_sample,now=now)
    temp=state.last_sample.temperature_c if state.last_sample else None
    for error in state.prediction_errors:
        if current is None or current<=state.config.mode_exit_a:continue
        if error.signature!=signature(state.config) or not 0<=(now-error.ended_at).total_seconds()<=90*86400:continue
        if error.actual_s<60 or error.predicted_s<=0:continue
        if abs(error.load_a/current-1)>.2:continue
        if temp is None or error.temperature_c is None or abs(temp-error.temperature_c)>5:continue
        # Multiple checkpoints in one discharge are correlated: one early point
        # represents one independent outcome, never several training samples.
        prior=eligible.get(error.session_id)
        if prior is None or error.utc<prior.utc:eligible[error.session_id]=error
    observations=tuple(eligible.values())
    ratios=[e.predicted_s/e.actual_s for e in observations]
    count=len(observations)
    return {'cycles':count,
            'mean_absolute_error_s':sum(abs(e.predicted_s-e.actual_s) for e in observations)/count if count else None,
            'bias_s':sum(e.predicted_s-e.actual_s for e in observations)/count if count else None,
            'lower_factor':1/max(ratios) if count>=3 else None,
            'upper_factor':1/min(ratios) if count>=3 else None,
            'last_verified_at':max((e.ended_at for e in observations),default=None)}


def assessment(state,forecast,*,now):
    c=state.config;reasons=list(forecast.quality);sample=state.last_sample
    anchor=state.last_anchor
    calibrated=anchor.utc if anchor and anchor.independently_verified else None
    age=max(0,(now-calibrated).total_seconds()) if calibrated else None
    if age is not None and age>c.calibration_max_age_s:reasons.append('calibration_due')
    if state.meter_checked_at is None:reasons.append('meter_unverified')
    validation=validation_summary(state,now=now)
    if validation['cycles']<3:reasons.append('forecast_unvalidated')
    if sample:
        if sample.battery_fault:reasons.append('battery_fault')
        if sample.charge_blocked or sample.charge_mosfet is False:reasons.append('charge_blocked')
        if sample.discharge_mosfet is False:reasons.append('discharge_blocked')
        # Text/code vocabularies differ by BMS. A separate explicit fault
        # signal establishes protection; opaque diagnostic text does not.
        if sample.battery_fault and sample.protection_reason:reasons.append('bms_protection')
    severe=any(r in reasons for r in ('range','stale','invalid','storage_error','restore_error','capacity_conflict','battery_fault','discharge_blocked'))
    status='unavailable' if forecast.time_remaining_s is None or severe else 'preliminary' if any(r in reasons for r in ('no_initial_anchor','nominal_estimate','manual_estimate','calibration_due','meter_unverified','data_gap','forecast_unvalidated','temperature_uncompensated','temperature_unknown','ambient_temperature')) else 'validated'
    lower=forecast.time_to_cutoff_s*validation['lower_factor'] if forecast.time_to_cutoff_s is not None and validation['lower_factor'] is not None and status!='unavailable' else None
    upper=forecast.time_to_cutoff_s*validation['upper_factor'] if forecast.time_to_cutoff_s is not None and validation['upper_factor'] is not None and status!='unavailable' else None
    return {'status':status,'reasons':list(dict.fromkeys(reasons)),'calibrated_at':calibrated,
            'calibration_age_s':age,'validation':validation,'cutoff_lower_s':lower,'cutoff_upper_s':upper,
            'bms_difference_percent':sample.bms_soc_percent-forecast.soc_percent if sample and sample.bms_soc_percent is not None and forecast.soc_percent is not None else None}
