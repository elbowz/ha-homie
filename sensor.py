from __future__ import annotations

import logging
import functools
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.restore_state import RestoreEntity

from homeassistant.const import (
    CONF_UNIT_OF_MEASUREMENT,
)

from homeassistant.components import sensor

from . import entity_base
from .homie import HomieProperty
from .mixins import async_setup_entry_helper
from .utils import logger

from .const import (
    HOMIE_DISCOVERY_NEW,
    HOMIE_DISCOVERY_NEW_DEVICE,
    SENSOR,
    CONF_DEVICE_CLASS,
    CONF_DEVICE,
    CONF_PROPERTY,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_OPTIMISTIC = False

PLATFORM_SCHEMA = entity_base.SCHEMA_BASE.extend(
    {
        # CONF_DEVICE_CLASS present in all entities but differ possible values by platfrom types
        vol.Optional(CONF_DEVICE_CLASS): sensor.DEVICE_CLASSES_SCHEMA,
        vol.Optional(sensor.CONF_STATE_CLASS): sensor.STATE_CLASSES_SCHEMA,
        vol.Optional(CONF_UNIT_OF_MEASUREMENT): cv.string,
    }
).extend(sensor.PLATFORM_SCHEMA.schema)

# Whole schema validation and post processing
PLATFORM_SCHEMA = vol.Schema(
    vol.All(PLATFORM_SCHEMA, entity_base.schema_post_processing)
)


@logger()
async def async_setup_platform(
    hass: HomeAssistant, config: ConfigType, async_add_entities, discovery_info=None
):
    """Called if exist a platform entry (ie. 'platform: homie') in configuration.yaml"""
    device_id = config[CONF_PROPERTY][CONF_DEVICE]

    # Workaround to bind entity and device (calling directly "_async_setup_entity" don't work)
    # setup = functools.partial(_async_setup_entity, hass, async_add_entities, config)
    setup = functools.partial(
        async_dispatcher_send, hass, HOMIE_DISCOVERY_NEW.format(SENSOR), config
    )

    # Avoid to create a new Home Device but wait its discovered first
    async_dispatcher_connect(hass, HOMIE_DISCOVERY_NEW_DEVICE.format(device_id), setup)


@logger()
async def async_setup_entry(hass, config_entry, async_add_entities):
    """Setup HomieProperty as HA sensor dynamically through discovery

    Called by hass.config_entries.async_forward_entry_setup() in async_setup_entry() component."""
    setup = functools.partial(
        _async_setup_entity, hass, async_add_entities, config_entry=config_entry
    )

    # Listening on new domain platfrom (eg sensor) discovered and init the setup
    await async_setup_entry_helper(hass, SENSOR, setup, PLATFORM_SCHEMA)


async def _async_setup_entity(hass, async_add_entities, config, config_entry=None):
    """Setup the HA sensor with an HomieProperty."""

    homie_property = await entity_base.async_get_homie_property(hass, config)
    async_add_entities([HomieSensor(hass, homie_property, config, config_entry)])


class HomieSensor(entity_base.HomieEntity, sensor.SensorEntity, RestoreEntity):
    """Implementation of a Homie Sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        homie_property: HomieProperty,
        config: ConfigType = {},
        config_entry: ConfigEntry = None,
    ):
        """Initialize Homie Sensor."""
        entity_base.HomieEntity.__init__(
            self, hass, homie_property, config, config_entry
        )

    async def async_added_to_hass(self):
        """Prefill with last state if optimistic."""

        await super().async_added_to_hass()

    @property
    def native_unit_of_measurement(self):
        """Return the unit this state is expressed in."""
        return self._config.get(
            CONF_UNIT_OF_MEASUREMENT, self._homie_property.t["$unit"]
        )

    @property
    def native_value(self):
        """Return the state of the entity."""
        return self._homie_property.value

    @property
    def state_class(self) -> str | None:
        """Return the state class of the sensor."""
        return self._config.get(sensor.CONF_STATE_CLASS)
