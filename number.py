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

from homeassistant.const import CONF_OPTIMISTIC, CONF_UNIT_OF_MEASUREMENT, CONF_MODE

from homeassistant.components import number

from . import entity_base
from .homie import HomieProperty
from .mixins import async_setup_entry_helper
from .utils import logger

from .const import (
    HOMIE_DISCOVERY_NEW,
    HOMIE_DISCOVERY_NEW_DEVICE,
    NUMBER,
    CONF_DEVICE,
    CONF_PROPERTY,
)

_LOGGER = logging.getLogger(__name__)

CONF_MIN = number.ATTR_MIN
CONF_MAX = number.ATTR_MAX
CONF_STEP = number.ATTR_STEP

DEFAULT_OPTIMISTIC = False


def validate_config(config):
    """Validate that the configuration is valid, throws if it isn't."""
    if (
        config.get(CONF_MIN)
        and config.get(CONF_MAX)
        and config.get(CONF_MIN) >= config.get(CONF_MAX)
    ):
        raise vol.Invalid(f"'{CONF_MAX}' must be > '{CONF_MIN}'")

    return config


PLATFORM_SCHEMA = entity_base.SCHEMA_BASE.extend(
    {
        vol.Optional(CONF_MAX): vol.Coerce(float),
        vol.Optional(CONF_MIN): vol.Coerce(float),
        vol.Optional(CONF_OPTIMISTIC, default=DEFAULT_OPTIMISTIC): cv.boolean,
        vol.Optional(CONF_STEP): vol.All(vol.Coerce(float), vol.Range(min=1e-3)),
        vol.Optional(CONF_MODE, default=number.MODE_AUTO): vol.All(
            vol.Lower, vol.In(["auto", "slider", "box"])
        ),
        vol.Optional(CONF_UNIT_OF_MEASUREMENT): cv.string,
    }
).extend(number.PLATFORM_SCHEMA.schema)

# Whole schema validation and post processing
PLATFORM_SCHEMA = vol.Schema(
    vol.All(PLATFORM_SCHEMA, entity_base.schema_post_processing, validate_config)
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
        async_dispatcher_send, hass, HOMIE_DISCOVERY_NEW.format(NUMBER), config
    )

    # Avoid to create a new Home Device but wait its discovered first
    async_dispatcher_connect(hass, HOMIE_DISCOVERY_NEW_DEVICE.format(device_id), setup)


@logger()
async def async_setup_entry(hass, config_entry, async_add_entities):
    """Setup HomieProperty as HA number dynamically through discovery

    Called by hass.config_entries.async_forward_entry_setup() in async_setup_entry() component."""
    setup = functools.partial(
        _async_setup_entity, hass, async_add_entities, config_entry=config_entry
    )

    # Listening on new domain platfrom (eg number) discovered and init the setup
    await async_setup_entry_helper(hass, NUMBER, setup, PLATFORM_SCHEMA)


async def _async_setup_entity(hass, async_add_entities, config, config_entry=None):
    """Setup the HA number with an HomieProperty."""

    homie_property = await entity_base.async_get_homie_property(hass, config)
    async_add_entities([HomieNumber(hass, homie_property, config, config_entry)])


class HomieNumber(entity_base.HomieEntity, number.NumberEntity):
    """Implementation of a Homie Number."""

    def __init__(
        self,
        hass: HomeAssistant,
        homie_property: HomieProperty,
        config: ConfigType = {},
        config_entry: ConfigEntry = None,
    ):
        """Initialize Homie Number."""
        entity_base.HomieEntity.__init__(
            self, hass, homie_property, config, config_entry
        )

        self._optimistic = self._config.get(CONF_OPTIMISTIC)

    @property
    def min_value(self) -> float:
        """Return the minimum value."""
        min_value, _ = self._homie_property.t.get("$format").split(":")
        return self._config.get(CONF_MIN, float(min_value))

    @property
    def max_value(self) -> float:
        """Return the maximum value."""
        _, max_value = self._homie_property.t.get("$format").split(":")
        return self._config.get(CONF_MAX, float(max_value))

    @property
    def step(self) -> float:
        """Return the increment/decrement step."""
        return self._config.get(CONF_STEP, super().step)

    @property
    def value(self):
        """Return the current value."""
        return self._homie_property.value

    @property
    def unit_of_measurement(self) -> str | None:
        """Return the unit this state is expressed in."""
        return self._config.get(
            CONF_UNIT_OF_MEASUREMENT, self._homie_property.t["$unit"]
        )

    @property
    def mode(self) -> str | None:
        return self._config.get(CONF_MODE)

    async def async_set_value(self, value: float) -> None:
        """Update the current value."""
        # if value.is_integer():
        #     value = int(value)

        await self._homie_property.async_set(value)

        if self._optimistic:
            # Optimistically set the new value.
            self._homie_property.value = value
            self.async_write_ha_state()

    @property
    def assumed_state(self):
        """Return true if we do optimistic updates."""
        return self._optimistic
