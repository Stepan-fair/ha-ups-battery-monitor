"""Serialized HA adapter; only its single timer advances the reducer."""
import asyncio,logging,time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import uuid4
from homeassistant.core import callback
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.util import dt as dt_util
from .const import TICK_S,CHECKPOINT_S
from .models import BatteryConfig,RawSnapshot,RawReading,Forecast
from .profiles import initial_state
from .inputs import normalize
from .engine import advance,resume
from .forecast import forecast
from .persistence import CheckpointStore,CheckpointWriteError,_decode,_encode

_LOGGER=logging.getLogger(__name__)

class UpsRuntime:
    def __init__(self,hass,entry):
        self.hass=hass;self.entry=entry
        from .migration import upgrade_config
        self.state=initial_state(_decode(BatteryConfig,upgrade_config(dict(entry.data['seed']))))
        self.store=CheckpointStore(Path(hass.config.path('.storage','ups')),entry.entry_id)
        self.run_id=str(uuid4());self._lock=asyncio.Lock();self._tick_running=False
        self._stopping=False;self._unsubscribe=None;self._unsubscribe_stop=None;self._listeners=set()
        self._last_checkpoint_mono=None;self._last_publish_mono=None
        self._storage_error=False;self.restore_error=False
        from .activity import ActivityPublisher
        self.publisher=ActivityPublisher(hass,entry.entry_id)
        self.values={};self.attributes={};self.on_battery=None
    async def async_start(self):
        result=await self.hass.async_add_executor_job(self.store.load)
        if result.state is not None:
            self.state=resume(result.state,run_id=self.run_id)
            if result.recovered_previous:
                from .activity import reserve_activity
                # The lost newest generation may already have dispatched these
                # events. Persist suppression before enabling any publication.
                self.state=reserve_activity(replace(self.state,has_gap=True,anchor_has_gap=True,issues=result.issues),self.state.pending_events)
                try:await self._checkpoint_locked()
                except CheckpointWriteError as e:raise ConfigEntryNotReady('UPS recovery reservation failed') from e
        elif self.entry.data.get('initialized') or result.issues:
            self.restore_error=True
            self.state=replace(self.state,mode='restore_error',issues=('restore_error',)+result.issues)
            _LOGGER.error('UPS checkpoint cannot be restored: %s',result.issues)
        else:
            try:await self._checkpoint_locked()
            except CheckpointWriteError as e:raise ConfigEntryNotReady('Initial UPS checkpoint failed') from e
            self.hass.config_entries.async_update_entry(self.entry,data={**self.entry.data,'initialized':True})
        async def on_stop(event):
            await self.async_stop()
        self._unsubscribe_stop=self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP,on_stop)
        self._publish(dt_util.utcnow(),None)
        if not self.restore_error:self._unsubscribe=async_track_time_interval(self.hass,self._scheduled,timedelta(seconds=TICK_S))
    async def _scheduled(self,now):
        await self.async_tick(now,time.monotonic())
    @callback
    def async_add_listener(self,listener):
        self._listeners.add(listener)
        def remove():self._listeners.discard(listener)
        return remove
    def _snapshot(self,now,monotonic_s):
        c=self.state.config.source
        mapping={'current':c.current_entity_id,'voltage':c.voltage_entity_id}
        for key in ['temperature','humidity','grid_failed','battery_fault','load_power','charge_blocked','full_flag','min_cell_voltage','cutoff_flag','charge_stage','bms_soc']:
            entity=getattr(c,key+'_entity_id')
            if entity:mapping[key]=entity
        readings={}
        for key,entity in mapping.items():
            state=self.hass.states.get(entity)
            readings[key]=RawReading(state.state if state else None,state.attributes.get('unit_of_measurement') if state else None,state.last_reported if state else None)
        grid=readings.get('grid_failed')
        if grid and grid.reported_at and grid.value in ('on','off'):
            self.on_battery=grid.value=='on'
        else:self.on_battery=None
        return RawSnapshot(now,monotonic_s,self.run_id,readings)
    async def async_tick(self,now_utc,monotonic_s):
        if self._tick_running or self._stopping or self.restore_error:return
        self._tick_running=True
        try:
            async with self._lock:
                if self._stopping:return
                before=(self.state.mode,self.state.issues)
                raw=self._snapshot(now_utc,monotonic_s)
                update=advance(self.state,normalize(raw,self.state.config.source))
                self.state=update.state
                if self._storage_error:self.state=replace(self.state,issues=tuple(dict.fromkeys(self.state.issues+('storage_error',))))
                due=self._last_checkpoint_mono is None or monotonic_s-self._last_checkpoint_mono>=CHECKPOINT_S
                if update.save_required or due:
                    try:
                        await self._checkpoint_locked();self._last_checkpoint_mono=monotonic_s
                    except CheckpointWriteError:pass
                if self.state.pending_events:
                    try:await self._publish_events_locked(())
                    except CheckpointWriteError:pass
                urgent=before!=(self.state.mode,self.state.issues) or bool(update.events)
                periodic=self._last_publish_mono is None or monotonic_s-self._last_publish_mono>=CHECKPOINT_S
                if urgent or periodic:
                    self._publish(now_utc,monotonic_s if periodic else None)
        finally:self._tick_running=False
    async def _checkpoint_locked(self):
        clean=replace(self.state,issues=tuple(i for i in self.state.issues if i!='storage_error'))
        try:receipt=await self.hass.async_add_executor_job(self.store.save,clean)
        except CheckpointWriteError:
            self.state=replace(self.state,issues=tuple(dict.fromkeys(self.state.issues+('storage_error',))))
            if not self._storage_error:_LOGGER.error('UPS checkpoint write failed; measurements remain in memory')
            self._storage_error=True
            raise
        if self._storage_error:_LOGGER.warning('UPS checkpoint storage recovered')
        self._storage_error=False
        self.state=replace(clean,generation=receipt.generation)
        return receipt
    async def async_checkpoint(self):
        async with self._lock:
            if self.restore_error:raise CheckpointWriteError('restore_error: read only')
            return await self._checkpoint_locked()
    def _publish(self,now,monotonic_s):
        from .sensor import snapshot_values,snapshot_attributes
        s=self.state
        f=forecast(s,s.last_sample,now=now) if s.last_sample else Forecast(None,None,None,None,None,None,None,s.issues+('no_initial_anchor',),'unknown')
        self.values=snapshot_values(s,f)
        if self.restore_error:
            self.values={key:None for key in self.values}|{'battery_mode':'restore_error','data_quality':'restore_error'}
        self.attributes=snapshot_attributes(s,f)
        if monotonic_s is not None:self._last_publish_mono=monotonic_s
        for listener in tuple(self._listeners):listener()
    async def async_stop(self):
        if self._stopping:return
        self._stopping=True
        if self._unsubscribe_stop:self._unsubscribe_stop();self._unsubscribe_stop=None
        if self._unsubscribe:self._unsubscribe();self._unsubscribe=None
        async with self._lock:
            if not self.restore_error:
                try:await self._checkpoint_locked()
                except CheckpointWriteError:pass

    async def _apply_locked(self,proposed):
        try:receipt=await self.hass.async_add_executor_job(self.store.save,proposed)
        except CheckpointWriteError:
            self._storage_error=True
            self.state=replace(self.state,issues=tuple(dict.fromkeys(self.state.issues+('storage_error',))))
            self._publish(dt_util.utcnow(),None)
            raise
        self._storage_error=False
        self.state=replace(proposed,generation=receipt.generation,issues=tuple(i for i in proposed.issues if i!='storage_error'))
        self._publish(dt_util.utcnow(),None)
        if self.state.pending_events:
            try:await self._publish_events_locked(())
            except CheckpointWriteError:pass
    def _check_battery(self,expected):
        if self.restore_error:raise ValueError('restore_error')
        if expected!=self.state.config.battery_id:raise ValueError('battery_changed')
    async def async_apply_config(self,config):
        from .engine import reconfigure
        from .profiles import validate_profile
        async with self._lock:
            self._check_battery(config.battery_id)
            config=validate_profile(_encode(config))
            await self._apply_locked(reconfigure(self.state,config,now=dt_util.utcnow()).state)
    async def async_new_battery(self,*,expected_battery_id):
        from .engine import new_battery
        async with self._lock:
            self._check_battery(expected_battery_id)
            identity=str(uuid4())
            await self._apply_locked(new_battery(self.state,battery_id=identity,now=dt_util.utcnow()).state)
            return identity
    async def async_set_known_soc(self,anchor,*,expected_battery_id):
        from .engine import set_known_soc
        async with self._lock:
            self._check_battery(expected_battery_id)
            await self._apply_locked(set_known_soc(self.state,anchor).state)
    async def async_reset_learning(self,*,expected_battery_id):
        from .engine import reset_learning
        async with self._lock:
            self._check_battery(expected_battery_id)
            await self._apply_locked(reset_learning(self.state,now=dt_util.utcnow()).state)

    async def _publish_events_locked(self,events):
        from .activity import reserve_activity
        combined={e.event_id:e for e in self.state.pending_events+tuple(events)}
        reserved=set(self.state.activity_reserved_ids)
        pending=tuple(e for key,e in combined.items() if key not in reserved)
        if not pending:return
        # Failed reservation keeps the full pending queue in RAM for the next tick.
        self.state=replace(self.state,pending_events=pending)
        proposed=reserve_activity(self.state,pending)
        try:receipt=await self.hass.async_add_executor_job(self.store.save,proposed)
        except CheckpointWriteError:
            self._storage_error=True
            self.state=replace(self.state,issues=tuple(dict.fromkeys(self.state.issues+('storage_error',))))
            raise
        self.state=replace(proposed,generation=receipt.generation)
        try:await self.publisher.async_publish(pending)
        except Exception:
            _LOGGER.exception('UPS Activity dispatch failed after durable reservation')
            self.state=replace(self.state,issues=tuple(dict.fromkeys(self.state.issues+('activity_error',))))
    async def async_publish_events(self,events):
        async with self._lock:
            if self.restore_error:raise CheckpointWriteError('restore_error')
            await self._publish_events_locked(events)
