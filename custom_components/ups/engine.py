"""One immutable reducer; monotonic boundaries forbid integrating across gaps."""
from dataclasses import replace
from datetime import timedelta
from math import ceil,exp
from .models import *
from .accounting import integrate
from .capacity import consider_observation,evaluate_full_anchor,full_conditions
from .sessions import start_session,add_interval,close_session,event
from .evidence import track_evidence

def _capacity(state):
    return state.working_capacity.ah if state.working_capacity else state.config.nominal_ah

def _soc(state):
    return None if state.remaining_charge_ah is None else min(1,max(0,state.remaining_charge_ah/_capacity(state)))

def _target(state,sample):
    i=sample.current_a;c=state.config
    if state.full_latched and full_conditions(state,sample):return "idle"
    current=state.active_session.kind if state.active_session else state.mode
    if i>=c.mode_enter_a:return "charging"
    if i<=-c.mode_enter_a:return "discharging"
    if current=="charging" and i>c.mode_exit_a:return current
    if current=="discharging" and i < -c.mode_exit_a:return current
    return "idle"

def resume(state: EngineState,*,run_id: str) -> EngineState:
    return replace(state,last_tick_monotonic_s=None,run_id=run_id,candidate_mode=None,candidate_started_at=None,candidate_started_mono=None,candidate_session=None,candidate_previous_session=None,full_since_mono=None,restored=True,has_gap=state.has_gap or state.last_sample is not None,anchor_has_gap=state.anchor_has_gap or state.last_sample is not None)

def set_known_soc(state: EngineState,anchor: Anchor) -> Update:
    if not 0<=anchor.soc_fraction<=1:raise ValueError("soc")
    previous=state.last_anchor
    if previous and previous.independently_verified and anchor.independently_verified and state.config.cutoff_v is not None:
        temperature=state.anchor_temperature_sum/state.anchor_temperature_s if state.anchor_temperature_s else None
        current=(state.discharge_ah_total-state.anchor_discharge_ah)*3600/state.anchor_discharge_s if state.anchor_discharge_s else 0
        observation=CapacityObservation(state.discharge_ah_total-state.anchor_discharge_ah,previous,anchor,temperature,current,state.config.cutoff_v,state.anchor_has_gap,state.anchor_has_saturation,state.anchor_source_changed,state.charge_ah_total-state.anchor_charge_ah>1e-6)
        state=consider_observation(state,observation)
    s=replace(state,remaining_charge_ah=_capacity(state)*anchor.soc_fraction,last_anchor=anchor,anchor_discharge_ah=state.discharge_ah_total,anchor_charge_ah=state.charge_ah_total,anchor_has_gap=False,anchor_has_saturation=False,anchor_source_changed=False,has_gap=False if anchor.independently_verified else state.has_gap,anchor_temperature_sum=0,anchor_temperature_s=0,anchor_discharge_s=0,usable_empty=False,post_cutoff_charge_ah=None)
    return Update(s,(),True)

def advance(state: EngineState,reading: ValidatedSample) -> Update:
    if state.run_id==reading.run_id and state.last_tick_monotonic_s is not None and reading.monotonic_s<=state.last_tick_monotonic_s:return Update(state)
    old=state;sample=reading.sample;events=[];c=state.config
    limit=max(13,ceil(60/c.source.expected_interval_s)+1)
    s=replace(state,minute_samples=(state.minute_samples+(reading,))[-limit:],last_tick_monotonic_s=reading.monotonic_s,run_id=reading.run_id,issues=reading.issues)
    prev=state.last_sample
    continuous=sample is not None and prev is not None and prev.run_id==sample.run_id and prev.source_id==sample.source_id and state.last_tick_monotonic_s==prev.monotonic_s and 0<sample.monotonic_s-prev.monotonic_s<=3*c.source.expected_interval_s
    iv=integrate(prev,sample,c.charge_efficiency) if continuous else IntervalCharge()
    gap=0.0
    if prev is not None and not continuous:
        if state.last_tick_monotonic_s is not None and state.run_id==reading.run_id:gap=max(0,reading.monotonic_s-state.last_tick_monotonic_s)
        else:gap=max(0,(reading.utc-prev.utc).total_seconds())
    if gap or (prev is not None and prev.run_id!=reading.run_id):
        issues=list(s.issues)+["data_gap"]
        if gap>180:issues.append("long_gap")
        active=replace(s.active_session,gap_s=s.active_session.gap_s+gap,quality=tuple(dict.fromkeys(s.active_session.quality+("data_gap",)))) if s.active_session else None
        s=replace(s,active_session=active,has_gap=True,anchor_has_gap=True,anchor_has_saturation=s.anchor_has_saturation or "range" in reading.issues,issues=tuple(dict.fromkeys(issues)),candidate_mode=None,candidate_started_at=None,candidate_started_mono=None,candidate_session=None,candidate_previous_session=None,full_since_mono=None)
    if sample is None:
        return Update(replace(s,mode="unknown"),(),old.mode!="unknown")
    if "range" in reading.issues:s=replace(s,anchor_has_saturation=True)
    if sample.grid_failed is True and sample.current_a>c.mode_enter_a:s=replace(s,issues=s.issues+("grid_current_conflict",))
    post_cutoff=None if s.post_cutoff_charge_ah is None else max(0,s.post_cutoff_charge_ah+iv.delta_stored_ah)
    s=replace(s,post_cutoff_charge_ah=post_cutoff,usable_empty=post_cutoff<=0 if post_cutoff is not None else s.usable_empty)
    q=None if s.remaining_charge_ah is None else s.remaining_charge_ah+iv.delta_stored_ah
    if s.post_cutoff_charge_ah is not None and q is not None:q=max(0,q)
    smooth=s.smoothed_discharge_a
    if sample.current_a< -c.mode_exit_a:
        current=-sample.current_a
        smooth=current if smooth is None or not continuous else smooth+(1-exp(-iv.dt_s/120))*(current-smooth)
    target=_target(s,sample)
    active=add_interval(s.active_session,iv,sample)
    s=replace(s,last_sample=sample,charge_ah_total=s.charge_ah_total+iv.charge_ah,discharge_ah_total=s.discharge_ah_total+iv.discharge_ah,charge_wh_total=s.charge_wh_total+iv.charge_wh,discharge_wh_total=s.discharge_wh_total+iv.discharge_wh,remaining_charge_ah=q,active_session=active,smoothed_discharge_a=smooth,mode_observed_s=s.mode_observed_s+iv.dt_s if target==s.mode else 0,restored=False)
    if target==s.mode or (s.mode=="unknown" and s.active_session and target==s.active_session.kind):
        s=replace(s,mode=target,candidate_mode=None,candidate_session=None,candidate_previous_session=None,candidate_started_at=None,candidate_started_mono=None)
    else:
        if s.candidate_mode!=target:
            candidate=start_session(c,sample,target,_soc(s)) if target!="idle" else None
            s=replace(s,candidate_mode=target,candidate_started_at=sample.utc,candidate_started_mono=sample.monotonic_s,candidate_session=candidate,candidate_previous_session=s.active_session)
        else:
            s=replace(s,candidate_session=add_interval(s.candidate_session,iv,sample))
        if sample.monotonic_s-s.candidate_started_mono>=c.mode_hold_s:
            if s.candidate_previous_session:
                reason="grid_restored" if sample.grid_failed is False and s.candidate_previous_session.kind=="discharging" else "charge_finished" if target=="idle" and s.candidate_previous_session.kind=="charging" else "mode_changed"
                closed=close_session(s.candidate_previous_session,s.candidate_started_at,reason,_soc(s))
                s=replace(s,**{"last_charge" if closed.kind=="charging" else "last_discharge":closed})
                events.append(event(closed,"session_ended",sample.utc,f"Сессия завершена: {closed.kind}; {closed.measured_s/3600:.2f} ч, {closed.discharge_ah if closed.kind=='discharging' else closed.charge_ah:.3f} А·ч; {reason}"))
            if s.candidate_session: events.append(event(s.candidate_session,"session_started",s.candidate_started_at,f"Начало: {target}"))
            s=replace(s,mode=target,active_session=s.candidate_session,mode_observed_s=sample.monotonic_s-s.candidate_started_mono,candidate_mode=None,candidate_session=None,candidate_previous_session=None,candidate_started_at=None,candidate_started_mono=None)
    # Reference temperature and current are measured only on the discharge segment.
    if iv.discharge_ah>0:
        s=replace(s,anchor_discharge_s=s.anchor_discharge_s+iv.dt_s,anchor_temperature_sum=s.anchor_temperature_sum+(sample.temperature_c*iv.dt_s if sample.temperature_c is not None else 0),anchor_temperature_s=s.anchor_temperature_s+(iv.dt_s if sample.temperature_c is not None else 0))
    conditions=full_conditions(s,sample)
    if conditions:
        s=replace(s,full_since_mono=s.full_since_mono if s.full_since_mono is not None else sample.monotonic_s)
        anchor=evaluate_full_anchor(s,sample)
        if anchor and not s.full_latched:
            finishing_clean=not s.anchor_has_gap
            s=set_known_soc(s,anchor).state
            s=replace(s,full_latched=True)
            if s.active_session and s.active_session.kind=="charging":
                closed=close_session(s.active_session,sample.utc,"charge_finished",1.0)
                events.append(event(closed,"session_ended",sample.utc,"Заряд завершён по подтверждённым U/I и выдержке"))
                s=replace(s,last_charge=closed,active_session=None,mode="idle",candidate_mode=None,candidate_session=None,candidate_previous_session=None,candidate_started_at=None,candidate_started_mono=None)
            if s.finishing_started_at and finishing_clean:
                s=replace(s,last_finishing_s=s.finishing_measured_s,last_finishing_temperature_c=sample.temperature_c,last_finishing_current_a=sample.current_a)
        elif anchor:
            # The independent full criterion remains true during float. Terminal
            # maintenance current is recorded, but does not create extra inventory.
            s=replace(s,remaining_charge_ah=_capacity(s))
    else:
        # A float interval may contain real maintenance current. Start the independent
        # discharge reference at its last confirmed-full boundary, without discarding totals.
        if s.full_latched and sample.current_a<0 and state.last_sample:
            fraction=prev.current_a/(prev.current_a-sample.current_a) if continuous and prev.current_a>0 else 0
            discharge_s=iv.dt_s*(1-fraction)
            boundary=prev.utc+timedelta(seconds=iv.dt_s*fraction)
            # Positive float current precedes the independent discharge anchor.
            # It remains in terminal totals but cannot invalidate this experiment.
            s=replace(s,last_anchor=Anchor(boundary,1,"auto_full",True),anchor_discharge_ah=state.discharge_ah_total,anchor_charge_ah=s.charge_ah_total,anchor_has_gap=not continuous,anchor_discharge_s=discharge_s,anchor_temperature_sum=(sample.temperature_c or 0)*discharge_s,anchor_temperature_s=discharge_s if sample.temperature_c is not None else 0,remaining_charge_ah=_capacity(s)-iv.discharge_ah)
        s=replace(s,full_since_mono=None,full_latched=False)
    below=c.cutoff_v is not None and sample.current_a<0 and sample.voltage_v<=c.cutoff_v
    count=state.cutoff_count+1 if below and continuous else (1 if below else 0)
    s=replace(s,cutoff_count=count)
    if (sample.cutoff_flag is True or count>=2) and (not state.usable_empty or s.remaining_charge_ah is None):
        if s.remaining_charge_ah is None:
            # The first independent empty boundary is sufficient to start a
            # usable-range inventory; capacity remains a nominal estimate.
            s=set_known_soc(s,Anchor(sample.utc,0,"confirmed_cutoff",True)).state
        elif s.last_anchor and s.last_anchor.independently_verified:
            previous_capacity=s.working_capacity
            chemical_q=s.remaining_charge_ah
            previous_gap=s.has_gap
            s=set_known_soc(s,Anchor(sample.utc,0,"confirmed_cutoff",True)).state
            if s.working_capacity==previous_capacity:
                # Without a newly accepted independent capacity experiment, only
                # available reserve is known to be empty; retain the raw estimate.
                s=replace(s,remaining_charge_ah=chemical_q,has_gap=previous_gap)
        s=replace(s,usable_empty=True,post_cutoff_charge_ah=0.0,termination_status='confirmed_cutoff',termination_at=sample.utc)
        if s.active_session and s.active_session.kind=="discharging":
            closed=close_session(s.active_session,sample.utc,"confirmed_cutoff",_soc(s))
            events.append(event(closed,"session_ended",sample.utc,"Подтверждённая отсечка: доступный запас исчерпан"))
            s=replace(s,last_discharge=closed,active_session=None)
    if sample.charge_stage=="finishing":
        s=replace(s,finishing_started_at=s.finishing_started_at or sample.utc,finishing_measured_s=s.finishing_measured_s+iv.dt_s)
    elif not s.full_latched:s=replace(s,finishing_started_at=None,finishing_measured_s=0)
    if s.last_discharge and s.last_discharge is not state.last_discharge and not s.last_discharge.gap_s and s.last_discharge.measured_s>=30 and not s.anchor_has_saturation:
        s=replace(s,last_verified_discharge_a=s.last_discharge.discharge_ah*3600/s.last_discharge.measured_s,last_verified_discharge_at=s.last_discharge.ended_at)
    if state.restored:
        if state.active_session and state.active_session.kind=='discharging' and not state.usable_empty:
            s=replace(s,termination_status='unconfirmed_stop',termination_at=prev.utc if prev else sample.utc)
        ev=DomainEvent(f"{c.battery_id}/recovery/{sample.run_id}","recovered",sample.utc,c.battery_id,s.active_session.session_id if s.active_session else None,f"Восстановление после запуска. Последнее известное измерение: {prev.utc.isoformat() if prev else 'нет'}. Пропуск {gap:.0f} с не учитывался.")
        events.append(ev)
    s=track_evidence(old,s,sample,iv)
    s=replace(s,pending_events=s.pending_events+tuple(events))
    return Update(s,tuple(events),bool(events) or old.mode!=s.mode or old.issues!=s.issues)


def reconfigure(state: EngineState,config: BatteryConfig,*,now) -> Update:
    if config.battery_id!=state.config.battery_id:raise ValueError("battery_changed")
    from .prediction import electrical_signature
    boundary=electrical_signature(config.source)!=electrical_signature(state.config.source)
    s=replace(state,config=config,full_since_mono=None,full_latched=False,candidate_mode=None,candidate_started_at=None,candidate_started_mono=None,candidate_session=None,candidate_previous_session=None)
    if boundary:
        s=replace(s,last_tick_monotonic_s=None,anchor_source_changed=True,anchor_has_gap=True,has_gap=True,last_verified_discharge_a=None,last_verified_discharge_at=None,smoothed_discharge_a=None,meter_checked_at=None,working_capacity=None,health_capacity=None,remaining_charge_ah=None,last_anchor=None,capacity_candidate=None,capacity_conflict=False,post_cutoff_charge_ah=None,usable_empty=False,prediction_points=())
    changed=config.ups_profile!=state.config.ups_profile or config.cutoff_v!=state.config.cutoff_v
    chemistry_changed=config.chemistry!=state.config.chemistry
    if changed or chemistry_changed:
        s=replace(s,anchor_source_changed=True,last_verified_discharge_a=None,last_verified_discharge_at=None,usable_empty=False,post_cutoff_charge_ah=None,working_capacity=None,capacity_candidate=None,capacity_conflict=False,last_anchor=None,remaining_charge_ah=None,health_capacity=None if chemistry_changed else s.health_capacity)
    return Update(s,(),True)

def new_battery(state: EngineState,*,battery_id: str,now) -> Update:
    if not battery_id or battery_id==state.config.battery_id:raise ValueError("new battery id")
    old=state
    events=[]
    if old.active_session:
        closed=close_session(old.active_session,now,"battery_replaced",_soc(old))
        old=replace(old,**{'last_charge' if closed.kind=='charging' else 'last_discharge':closed})
        events.append(event(closed,'session_ended',now,'Сессия завершена: замена АКБ'))
    archive=BatteryArchive(old.config,now,old.working_capacity,old.health_capacity,old.last_charge,old.last_discharge,old.passport,old.capacity_history)
    ev=DomainEvent(f'{battery_id}/installed','battery_replaced',now,battery_id,None,'Установлена новая батарея. Начальная ёмкость и заряд ещё не подтверждены.')
    events.append(ev)
    s=EngineState(replace(old.config,battery_id=battery_id),generation=old.generation,charge_ah_total=old.charge_ah_total,discharge_ah_total=old.discharge_ah_total,charge_wh_total=old.charge_wh_total,discharge_wh_total=old.discharge_wh_total,archives=old.archives+(archive,),pending_events=old.pending_events+tuple(events),activity_reserved_ids=old.activity_reserved_ids)
    return Update(s,tuple(events),True)

def reset_learning(state: EngineState,*,now) -> Update:
    ev=DomainEvent(f'{state.config.battery_id}/reset/{now.isoformat()}','learning_reset',now,state.config.battery_id,None,'Обучение активной АКБ сброшено; накопленные А·ч и Вт·ч сохранены.')
    s=replace(state,working_capacity=None,health_capacity=None,capacity_candidate=None,capacity_conflict=False,last_observation=None,last_anchor=None,remaining_charge_ah=None,last_reset_at=now,pending_events=state.pending_events+(ev,))
    return Update(s,(ev,),True)
