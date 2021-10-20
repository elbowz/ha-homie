# IMPORT
import functools
import logging

import voluptuous as vol

from homeassistant.components import switch
from homeassistant.components.mqtt.switch import MqttSwitch
from homeassistant.components.switch import SwitchEntity

from homeassistant.core import HomeAssistant, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.helpers.typing import ConfigType

from homeassistant.const import (
    CONF_NAME,
    CONF_OPTIMISTIC,
    CONF_PAYLOAD_OFF,
    CONF_PAYLOAD_ON,
    CONF_VALUE_TEMPLATE,
    STATE_ON,
)

from . import (
    DOMAIN,
    PLATFORMS,
    KEY_HOMIE_ALREADY_DISCOVERED,
    KEY_HOMIE_ENTITY_NAME,
    HomieNode,
)

# CONSTANTS
_LOGGER = logging.getLogger(__name__)
DEFAULT_NAME = "Homie Switch"
HOMIE_DISCOVERY_NEW = "homie_discovery_new_{}_{}"
STATE_PROP = "light"
STATE_ON_VALUE = "true"
STATE_OFF_VALUE = "false"

PLATFORM_SCHEMA = vol.Schema(
    {
        vol.Optional("KEY_HOMIE_ENTITY_ID", default=DEFAULT_NAME): cv.string,
    }
)


async def async_setup_platform(
    hass: HomeAssistant, config: ConfigType, async_add_entities, discovery_info=None
):
    """Called if exist a platform entry (ie. 'platform: homie') in configuration.yaml"""
    await async_setup_reload_service(hass, DOMAIN, PLATFORMS)
    await _async_setup_entity(hass, async_add_entities, config)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Called by hass.config_entries.async_forward_entry_setup()

    Thanks to the use of async_setup_entry() we can add device to registry.
    https://developers.home-assistant.io/docs/device_registry_index#defining-devices
    """
    setup = functools.partial(
        _async_setup_entity, hass, async_add_entities, config_entry=config_entry
    )

    _LOGGER.debug("async_setup_entry(): %s", config_entry)

    await async_setup_entry_helper(hass, switch.DOMAIN, setup, PLATFORM_SCHEMA)


async def async_setup_entry_helper(hass, domain, async_setup, schema):
    """Set up entity, automation or tag creation dynamically through MQTT discovery."""

    async def async_discover(discovery_payload):
        """Discover and add an MQTT entity, automation or tag."""
        # discovery_data = discovery_payload.discovery_data
        discovery_data = discovery_payload
        config = schema(discovery_payload)
        await async_setup(config, discovery_data=discovery_data)

    async_dispatcher_connect(
        hass, "homie_discovery_new".format(switch.DOMAIN, "homie"), async_discover
    )


async def _async_setup_entity(
    hass, async_add_entities, config, config_entry=None, discovery_data=None
):
    """Set up the MQTT binary sensor."""

    _LOGGER.debug("_async_setup_entity(): %s", config)

    entity_name = config[KEY_HOMIE_ENTITY_NAME]
    homie_sensor_node = hass.data[KEY_HOMIE_ALREADY_DISCOVERED][entity_name]

    from typing import OrderedDict

    config = OrderedDict(
        [
            ("payload_on", "true"),
            ("payload_off", "false"),
            ("optimistic", False),
            # ("platform", "mqtt"),
            ("name", "Switch fake"),
            ("unique_id", "switch666"),
            ("state_topic", "bdiot/thumbl-p-dev/light/light"),
            ("command_topic", "bdiot/thumbl-p-dev/light/light/set"),
            ("retain", False),
            ("enabled_by_default", True),
            ("payload_available", "online"),
            ("availability_mode", "latest"),
            ("payload_not_available", "offline"),
            ("qos", 0),
        ]
    )

    config_entry = None
    discovery_data = None
    # async_add_entities([HomieSwitch(hass, entity_name, homie_sensor_node)])
    async_add_entities([MqttSwitch(hass, config, config_entry, discovery_data)])


async def async_setup_platform_disabled(
    hass: HomeAssistant, config: ConfigType, async_add_entities, discovery_info=None
):
    """Set up the Homie Switch."""
    _LOGGER.info(f"Setting up Homie Switch: {config} - {discovery_info}")

    entity_name = discovery_info[KEY_HOMIE_ENTITY_NAME]
    homie_sensor_node = hass.data[KEY_HOMIE_ALREADY_DISCOVERED][entity_name]

    _LOGGER.debug("properties: %s", homie_sensor_node.properties)

    if homie_sensor_node is None:
        raise ValueError("Homie Switch faild to recive a Homie Node to bind too")
    if not homie_sensor_node.has_property(STATE_PROP):
        raise Exception(f"Homie Switch Node doesnt have a {STATE_PROP} property")

    async_add_entities([HomieSwitch(hass, entity_name, homie_sensor_node)])


class HomieSwitch(SwitchEntity):
    """Implementation of a Homie Switch."""

    def __init__(
        self, hass: HomeAssistant, entity_name: str, homie_sensor_node: HomieNode
    ):
        """Initialize Homie Switch."""
        self.hass = hass
        self._name = entity_name
        self._node = homie_sensor_node
        self._unique_id = "homie.unique_id"

    async def async_added_to_hass(self):
        """Subscribe mqtt events."""
        await super().async_added_to_hass()
        self._node.device.add_listener(self._on_change)
        self._node.add_listener(self._on_change)
        self._node.get_property(STATE_PROP).add_listener(self._on_change)

    # convert to async?
    def _on_change(self):
        _LOGGER.debug("async_schedule_update_ha_state() %s", vars(self))
        self.async_write_ha_state()
        # self.async_schedule_update_ha_state(force_refresh=False)

    @property
    def name(self):
        """Return the name of the Homie Switch."""
        return self._name

    @property
    def is_on(self):
        """Returns true if the Homie Switch is on."""
        return self._node.get_property(STATE_PROP).state == STATE_ON_VALUE

    @property
    def should_poll(self):
        return False

    async def async_turn_on(self, **kwargs):
        """Turn the device on.

        This method is a coroutine.
        """
        _LOGGER.debug("async_turn_on()")

        await self._node.get_property(STATE_PROP).async_set_state(STATE_ON_VALUE)

    async def async_turn_off(self, **kwargs):
        """Turn the device off.

        This method is a coroutine.
        """
        _LOGGER.debug("async_turn_on()")

        await self._node.get_property(STATE_PROP).async_set_state(STATE_OFF_VALUE)

    @property
    def available(self):
        """Return if the device is available."""
        return True
        return self._node.device.online

    @property
    def device_info(self):
        """Return the device info."""

        _LOGGER.debug("device_info()")

        return {
            "identifiers": {(DOMAIN, "8345934534")},
            "name": "device name homie",
            "manufacturer": "manufacture home",
            "model": "model homie",
            "sw_version": "1.3",
        }

    @property
    def unique_id(self):
        """Return a unique ID."""
        return self._unique_id
