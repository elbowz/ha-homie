import logging
import asyncio
import functools
import voluptuous as vol

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import config_validation as cv, event
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.typing import ConfigType

from homeassistant.components import binary_sensor

from . import entity_base
from .homie import HomieProperty
from .homie.utils import str2bool
from .mixins import async_setup_entry_helper
from .utils import logger

from .const import (
    HOMIE_DISCOVERY_NEW_DEVICE,
    BINARY_SENSOR,
    CONF_DEVICE_CLASS,
    CONF_DEVICE,
    CONF_PROPERTY,
)

_LOGGER = logging.getLogger(__name__)

CONF_OFF_DELAY = "off_delay"

PLATFORM_SCHEMA = entity_base.SCHEMA_BASE.extend(
    {
        vol.Optional(CONF_DEVICE_CLASS): binary_sensor.DEVICE_CLASSES_SCHEMA,
        vol.Optional(CONF_OFF_DELAY): cv.positive_int,
    }
).extend(binary_sensor.PLATFORM_SCHEMA.schema)


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
    """Setup HomieProperty as HA binary_sensor dynamically through discovery

    Called by hass.config_entries.async_forward_entry_setup() in async_setup_entry() component."""
    setup = functools.partial(
        _async_setup_entity, hass, async_add_entities, config_entry=config_entry
    )

    # Listening on new domain platfrom (eg binary_sensor) discovered and init the setup
    await async_setup_entry_helper(hass, BINARY_SENSOR, setup, PLATFORM_SCHEMA)


async def _async_setup_entity(hass, async_add_entities, config, config_entry=None):
    """Setup the HA binary_sensor with an HomieProperty."""

    homie_property = await entity_base.async_get_homie_property(hass, config)
    async_add_entities([HomieBinarySensor(hass, homie_property, config, config_entry)])


class HomieBinarySensor(entity_base.HomieEntity, binary_sensor.BinarySensorEntity):
    """Implementation of a Homie BinarySensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        homie_property: HomieProperty,
        config: ConfigType = {},
        config_entry: ConfigEntry = None,
    ):
        """Initialize Homie BinarySensor."""
        entity_base.HomieEntity.__init__(
            self, hass, homie_property, config, config_entry
        )

    async def _async_on_property_change(self, homie_property, topic, value):
        """Callend on property topic change."""

        # Apply a delay (CONF_OFF_DELAY) on False
        if (
            (off_delay := self._config.get(CONF_OFF_DELAY))
            and topic == ""
            and str2bool(self._homie_property.value) is False
        ):
            await asyncio.sleep(off_delay)

        await super()._async_on_property_change(homie_property, topic, value)

    @property
    def is_on(self):
        """Returns true if the Homie BinarySensor is on."""
        return str2bool(self._homie_property.value)
