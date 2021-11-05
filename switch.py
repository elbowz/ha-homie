import logging
import functools
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.restore_state import RestoreEntity

from homeassistant.const import (
    CONF_OPTIMISTIC,
    STATE_ON,
)

from homeassistant.components import switch

from . import entity_base
from .homie import HomieProperty
from .homie.utils import bool2str, str2bool
from .mixins import async_setup_entry_helper
from .utils import logger

from .const import (
    HOMIE_DISCOVERY_NEW_DEVICE,
    SWITCH,
    CONF_DEVICE_CLASS,
    CONF_DEVICE,
    CONF_PROPERTY,
    TRUE,
    FALSE,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_OPTIMISTIC = False


PLATFORM_SCHEMA = entity_base.SCHEMA_BASE.extend(
    {
        vol.Optional(CONF_OPTIMISTIC, default=DEFAULT_OPTIMISTIC): cv.boolean,
        # CONF_DEVICE_CLASS present in all entities but differ possible values by platfrom types
        vol.Optional(CONF_DEVICE_CLASS): switch.DEVICE_CLASSES_SCHEMA,
        # TODO: add "external" state_topic (device-node-property)
        # vol.Optional(CONF_STATE_TOPIC): valid_subscribe_topic,
    }
).extend(switch.PLATFORM_SCHEMA.schema)


@logger()
async def async_setup_platform(
    hass: HomeAssistant, config: ConfigType, async_add_entities, discovery_info=None
):
    """Called if exist a platform entry (ie. 'platform: homie') in configuration.yaml"""
    # Convert property topic to dict form and update config
    entity_base.async_post_process(config)
    device_id = config[CONF_PROPERTY][CONF_DEVICE]

    setup = functools.partial(_async_setup_entity, hass, async_add_entities, config)

    # Avoid to create a new Home Device but wait its discovered first
    async_dispatcher_connect(hass, HOMIE_DISCOVERY_NEW_DEVICE.format(device_id), setup)


@logger()
async def async_setup_entry(hass, config_entry, async_add_entities):
    """Setup HomieProperty as HA switch dynamically through discovery

    Called by hass.config_entries.async_forward_entry_setup() in async_setup_entry() component."""
    setup = functools.partial(
        _async_setup_entity, hass, async_add_entities, config_entry=config_entry
    )

    # Listening on new domain platfrom (eg switch) discovered and init the setup
    await async_setup_entry_helper(hass, SWITCH, setup, PLATFORM_SCHEMA)


async def _async_setup_entity(hass, async_add_entities, config, config_entry=None):
    """Setup the HA switch with an HomieProperty."""

    homie_property = await entity_base.async_get_homie_property(hass, config)
    async_add_entities([HomieSwitch(hass, homie_property, config, config_entry)])


class HomieSwitch(entity_base.HomieEntity, switch.SwitchEntity, RestoreEntity):
    """Implementation of a Homie Switch."""

    def __init__(
        self,
        hass: HomeAssistant,
        homie_property: HomieProperty,
        config: ConfigType = {},
        config_entry: ConfigEntry = None,
    ):
        """Initialize Homie Switch."""
        entity_base.HomieEntity.__init__(
            self, hass, homie_property, config, config_entry
        )

        self._optimistic = self._config.get(CONF_OPTIMISTIC)

    async def async_added_to_hass(self):
        """Prefill with last state if optimistic."""

        await super().async_added_to_hass()

        if self._optimistic:
            last_state = await self.async_get_last_state()
            if last_state:
                self._homie_property.value = bool2str(last_state.state == STATE_ON)

    @property
    def is_on(self):
        """Returns true if the Homie Switch is on."""
        return str2bool(self._homie_property.value)

    @logger()
    async def async_turn_on(self, **kwargs):
        """Turn the device on."""
        self._homie_property.async_set(TRUE)

        if self._optimistic:
            # Optimistically assume that switch has changed state.
            self._homie_property.value = TRUE
            self.async_write_ha_state()

    @logger()
    async def async_turn_off(self, **kwargs):
        """Turn the device off."""
        self._homie_property.async_set(FALSE)

        if self._optimistic:
            # Optimistically assume that switch has changed state.
            self._homie_property.value = FALSE
            self.async_write_ha_state()

    @property
    def assumed_state(self):
        """Return true if we do optimistic updates."""
        return self._optimistic
