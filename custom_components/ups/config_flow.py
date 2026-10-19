"""Native profiles and explicitly confirmed battery maintenance."""
from dataclasses import replace
from uuid import uuid4
import probatio as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util
from .const import DOMAIN
from .models import Anchor
from .profiles import make_profile,profile_form_data,profile_from_form
from .persistence import _encode,CheckpointWriteError

CHEMISTRIES=['flooded','agm','gel','lifepo4']
UPS_PROFILES=['smartec','meanwell','custom']

def choice(items):return selector.SelectSelector(selector.SelectSelectorConfig(options=items,mode=selector.SelectSelectorMode.DROPDOWN))
def preset_schema():
    return vol.Schema({vol.Required('name',default='АКБ'):str,vol.Required('chemistry',default='flooded'):choice(CHEMISTRIES),vol.Required('ups_profile',default='smartec'):choice(UPS_PROFILES),vol.Required('nominal_ah',default=125):vol.All(vol.Coerce(float),vol.Range(min=.1,max=10000))})

def form_schema(config):
    values=profile_form_data(config);groups={}
    nullable={'installed_at','cutoff_v','full_voltage_v','tail_current_a'}
    for group,fields in values.items():
        fields=dict(fields)
        if group=='battery':
            for key in nullable:fields.setdefault(key,None)
        if group=='measurements':
            for key in config.source.__dataclass_fields__:
                if key.endswith('_entity_id'):fields.setdefault(key,None)
        schema={}
        for key,value in fields.items():
            if key.endswith('_entity_id'):
                domain='binary_sensor' if key in ('grid_failed_entity_id','battery_fault_entity_id','charge_blocked_entity_id','full_flag_entity_id','cutoff_flag_entity_id') else 'sensor'
                validator=selector.EntitySelector(selector.EntitySelectorConfig(domain=domain))
            elif key=='chemistry':validator=choice(CHEMISTRIES)
            elif key=='ups_profile':validator=choice(UPS_PROFILES)
            elif isinstance(value,bool):validator=bool
            elif key in nullable and key!='installed_at':validator=vol.Coerce(float)
            elif isinstance(value,(int,float)):validator=vol.Coerce(float) if key!='sign' else vol.Coerce(int)
            else:validator=str
            optional=key in nullable or (key.endswith('_entity_id') and key not in ('current_entity_id','voltage_entity_id'))
            marker=vol.Optional(key,description={'suggested_value':value}) if optional and value is not None else vol.Optional(key) if optional else vol.Required(key,default=value)
            schema[marker]=validator
        groups[vol.Required(group)]=section(vol.Schema(schema),{'collapsed':group=='advanced'})
    return vol.Schema(groups)

class UpsConfigFlow(config_entries.ConfigFlow,domain=DOMAIN):
    VERSION=1
    @staticmethod
    @callback
    def async_get_options_flow(config_entry):return UpsOptionsFlow()
    async def async_step_user(self,user_input=None):
        if self._async_current_entries():return self.async_abort(reason='single_instance_allowed')
        errors={}
        if user_input is not None:
            try:
                self._base=make_profile(user_input['chemistry'],user_input['ups_profile'],battery_id=str(uuid4()),nominal_ah=float(user_input['nominal_ah']))
                self._base=replace(self._base,name=user_input['name'])
                return await self.async_step_profile()
            except ValueError:errors={'base':'invalid_profile'}
        return self.async_show_form(step_id='user',data_schema=preset_schema(),errors=errors)
    async def async_step_profile(self,user_input=None):
        errors={}
        if user_input is not None:
            try:
                config=profile_from_form(user_input,self._base)
                return self.async_create_entry(title=config.name,data={'seed':_encode(config)})
            except (ValueError,TypeError,KeyError):errors={'base':'invalid_profile'}
        return self.async_show_form(step_id='profile',data_schema=form_schema(self._base),errors=errors)

class UpsOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self,user_input=None):
        self._runtime=self.config_entry.runtime_data
        self._base=self._runtime.state.config
        self._expected_battery_id=self._base.battery_id
        if self._runtime.restore_error:return self.async_abort(reason='restore_error')
        return self.async_show_menu(step_id='init',menu_options=['profile','preset','new_battery','known_soc','reset_learning'])
    async def async_step_preset(self,user_input=None):
        if user_input is not None:
            base=make_profile(user_input['chemistry'],user_input['ups_profile'],battery_id=self._expected_battery_id,nominal_ah=float(user_input['nominal_ah']))
            self._base=replace(base,name=user_input['name'],source=self._base.source)
            return await self.async_step_profile()
        return self.async_show_form(step_id='preset',data_schema=preset_schema())
    async def async_step_profile(self,user_input=None):
        errors={}
        if user_input is not None:
            try:
                config=profile_from_form(user_input,self._base)
                await self._runtime.async_apply_config(config)
                return self.async_create_entry(title='',data={})
            except CheckpointWriteError:errors={'base':'storage_error'}
            except (ValueError,TypeError,KeyError):errors={'base':'invalid_profile'}
        return self.async_show_form(step_id='profile',data_schema=form_schema(self._base),errors=errors)
    async def async_step_new_battery(self,user_input=None):
        self._action='new_battery';return await self.async_step_confirm()
    async def async_step_known_soc(self,user_input=None):
        self._action='known_soc';return await self.async_step_confirm()
    async def async_step_reset_learning(self,user_input=None):
        self._action='reset_learning';return await self.async_step_confirm()
    async def async_step_confirm(self,user_input=None):
        errors={}
        if user_input is not None:
            if user_input.get('confirm') is not True:errors={'base':'confirmation_required'}
            else:
                try:
                    if self._action=='new_battery':await self._runtime.async_new_battery(expected_battery_id=self._expected_battery_id)
                    elif self._action=='reset_learning':await self._runtime.async_reset_learning(expected_battery_id=self._expected_battery_id)
                    else:
                        value=float(user_input['soc_percent'])/100
                        await self._runtime.async_set_known_soc(Anchor(dt_util.utcnow(),value,'manual_estimate',False),expected_battery_id=self._expected_battery_id)
                    return self.async_create_entry(title='',data={})
                except CheckpointWriteError:errors={'base':'storage_error'}
                except ValueError:errors={'base':'battery_changed'}
        schema={vol.Required('confirm',default=False):bool}
        if self._action=='known_soc':schema[vol.Required('soc_percent')]=vol.All(vol.Coerce(float),vol.Range(min=0,max=100))
        return self.async_show_form(step_id='confirm',data_schema=vol.Schema(schema),errors=errors,description_placeholders={'action':self._action,'battery':self._base.name})
