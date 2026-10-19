from homeassistant.components.binary_sensor import BinarySensorEntity,BinarySensorDeviceClass
from .const import DOMAIN

async def async_setup_entry(hass,entry,async_add_entities):
    async_add_entities([UpsOnBattery(entry.runtime_data)])

class UpsOnBattery(BinarySensorEntity):
    _attr_should_poll=False
    _attr_has_entity_name=True
    _attr_name='Питание от АКБ'
    _attr_device_class=BinarySensorDeviceClass.POWER
    def __init__(self,runtime):
        self.runtime=runtime;self._attr_unique_id=f'{runtime.entry.entry_id}_on_battery'
        self.entity_id='binary_sensor.ups_on_battery'
        self._attr_device_info={'identifiers':{(DOMAIN,runtime.entry.entry_id)}}
    async def async_added_to_hass(self):self.async_on_remove(self.runtime.async_add_listener(self.async_write_ha_state))
    @property
    def is_on(self):
        if self.runtime.on_battery is not None:return self.runtime.on_battery
        if self.runtime.state.mode=='discharging':return True
        if self.runtime.state.mode in ('charging','idle'):return False
        return None
    @property
    def available(self):return self.is_on is not None
