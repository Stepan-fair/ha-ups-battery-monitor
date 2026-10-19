"""UPS battery monitor; HA imports stay out of the pure calculation package."""
from .const import DOMAIN

async def async_setup_entry(hass,entry):
    from .runtime import UpsRuntime
    runtime=UpsRuntime(hass,entry)
    await runtime.async_start()
    entry.runtime_data=runtime
    try:
        await hass.config_entries.async_forward_entry_setups(entry,["sensor","binary_sensor"])
    except Exception:
        await runtime.async_stop()
        raise
    return True

async def async_unload_entry(hass,entry):
    runtime=entry.runtime_data
    await runtime.async_stop()
    return await hass.config_entries.async_unload_platforms(entry,["sensor","binary_sensor"])
