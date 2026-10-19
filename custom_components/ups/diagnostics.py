from .persistence import _encode

async def async_get_config_entry_diagnostics(hass,entry):
    r=entry.runtime_data
    return {'state':_encode(r.state),'storage_error':r._storage_error,'restore_error':r.restore_error}
