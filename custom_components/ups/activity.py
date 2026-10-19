"""At-most-once Activity publication; checkpoints remain the session record."""
from dataclasses import replace
from homeassistant.components import logbook
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from .const import DOMAIN

def reserve_activity(state,events):
    ids=tuple(dict.fromkeys(state.activity_reserved_ids+tuple(e.event_id for e in events)))
    reserved=set(ids)
    return replace(state,activity_reserved_ids=ids,pending_events=tuple(e for e in state.pending_events if e.event_id not in reserved))

class ActivityPublisher:
    def __init__(self,hass,entry_id):self.hass=hass;self.entry_id=entry_id
    async def async_publish(self,events):
        registry=er.async_get(self.hass)
        entity=registry.async_get_entity_id('sensor',DOMAIN,f'{self.entry_id}_battery_mode') or 'sensor.ups_battery_mode'
        for e in events:
            stamp=dt_util.as_local(e.occurred_at).strftime('%d.%m.%Y %H:%M:%S')
            logbook.async_log_entry(self.hass,'ИБП',f'{e.message} Известное время: {stamp}.',domain=DOMAIN,entity_id=entity)
