from dataclasses import replace
from unittest.mock import patch
import pytest
from custom_components.ups.models import DomainEvent
from custom_components.ups.activity import reserve_activity
from custom_components.ups.persistence import CheckpointWriteError
from .conftest import tick
from tests.unit.helpers import utc

async def test_activity_is_not_replayed_after_restore(hass,runtime):
    events=[];hass.bus.async_listen('logbook_entry',lambda e:events.append(e.data))
    e=DomainEvent('one-event','session_started',utc(),runtime.state.config.battery_id,'s1','Начало разряда')
    await runtime.async_publish_events((e,));await runtime.async_publish_events((e,))
    await hass.async_block_till_done()
    assert len(events)==1
    restored=runtime.store.load().state
    assert 'one-event' in restored.activity_reserved_ids
    runtime.state=restored
    await runtime.async_publish_events((e,));await hass.async_block_till_done()
    assert len(events)==1

async def test_failed_reservation_does_not_publish(hass,runtime):
    events=[];hass.bus.async_listen('logbook_entry',lambda e:events.append(e.data))
    e=DomainEvent('fail-event','session_started',utc(),runtime.state.config.battery_id,'s1','Начало')
    with patch.object(runtime.store,'save',side_effect=CheckpointWriteError('test full')):
        with pytest.raises(CheckpointWriteError):await runtime.async_publish_events((e,))
    assert not events
    assert e in runtime.state.pending_events
    await runtime.async_publish_events(())
    await hass.async_block_till_done()
    assert len(events)==1

async def test_crash_after_reservation_preserves_session(hass,freezer,runtime):
    for t in range(0,31,5):await tick(hass,freezer,runtime,t)
    for t in range(35,56,5):await tick(hass,freezer,runtime,t,amps=2)
    completed=runtime.state.last_discharge
    e=DomainEvent('crash-reserved','session_ended',utc(55),runtime.state.config.battery_id,completed.session_id,'Итог разряда')
    proposed=reserve_activity(runtime.state,(e,))
    receipt=await hass.async_add_executor_job(runtime.store.save,proposed)
    restored=runtime.store.load().state
    assert restored.last_discharge.session_id==completed.session_id
    assert 'crash-reserved' in restored.activity_reserved_ids
    runtime.state=restored
    events=[];hass.bus.async_listen('logbook_entry',lambda e:events.append(e.data))
    await runtime.async_publish_events((e,));await hass.async_block_till_done()
    assert not events

async def test_recovered_event_is_labeled(hass,freezer,runtime):
    await tick(hass,freezer,runtime,0)
    await runtime.async_checkpoint()
    entry=runtime.entry
    await hass.config_entries.async_reload(entry.entry_id)
    events=[];hass.bus.async_listen('logbook_entry',lambda e:events.append(e.data))
    await tick(hass,freezer,entry.runtime_data,180)
    assert any('Восстановление' in e['message'] and 'не учитывался' in e['message'] for e in events)


async def test_previous_generation_never_replays_uncertain_activity(hass,runtime):
    events=[];hass.bus.async_listen('logbook_entry',lambda e:events.append(e.data))
    e=DomainEvent('fallback-event','session_started',utc(),runtime.state.config.battery_id,'s1','Событие до повреждения')
    runtime.state=replace(runtime.state,pending_events=(e,))
    await runtime.async_checkpoint()
    await runtime.async_publish_events(())
    await hass.async_block_till_done()
    old_previous=runtime.store.previous.read_bytes()
    assert len(events)==1
    entry=runtime.entry
    await hass.config_entries.async_unload(entry.entry_id)
    # Simulate abrupt loss of the new reserved generation before any later save.
    runtime.store.current.write_bytes(b'corrupt')
    runtime.store.previous.write_bytes(old_previous)
    assert await hass.config_entries.async_setup(entry.entry_id)
    recovered=entry.runtime_data
    await recovered.async_publish_events(())
    await hass.async_block_till_done()
    assert len([x for x in events if 'Событие до повреждения' in x['message']])==1
    assert not recovered.store.load().state.pending_events
    assert 'fallback-event' in recovered.store.load().state.activity_reserved_ids
