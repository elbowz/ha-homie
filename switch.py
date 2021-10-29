# IMPORT
import functools
import logging

import voluptuous as vol

from homeassistant.components import switch
from homeassistant.components.mqtt.switch import MqttSwitch
from homeassistant.components.switch import SwitchEntity, PLATFORM_SCHEMA

from homeassistant.core import HomeAssistant, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.helpers.typing import ConfigType

from .helpers import bool2str, str2bool

from .const import HOMIE_DISCOVERY_NEW, SWITCH

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
    HomieProperty,
    TRUE,
    FALSE,
)

# CONSTANTS
_LOGGER = logging.getLogger(__name__)
DEFAULT_NAME = "Homie Switch"

STATE_PROP = "light"
STATE_ON_VALUE = "true"
STATE_OFF_VALUE = "false"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required("ciao"): cv.string,
        vol.Optional("bau", default="admin"): cv.string,
    }
)


async def async_setup_platform(
    hass: HomeAssistant, config: ConfigType, async_add_entities, discovery_info=None
):
    """Called if exist a platform entry (ie. 'platform: homie') in configuration.yaml"""
    # await async_setup_reload_service(hass, DOMAIN, PLATFORMS)
    # await _async_setup_entity(hass, async_add_entities, config)
    pass


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Called by hass.config_entries.async_forward_entry_setup()

    Thanks to the use of async_setup_entry() we can add device to registry.
    https://developers.home-assistant.io/docs/device_registry_index#defining-devices
    """
    setup = functools.partial(
        _async_setup_entity, hass, async_add_entities, config_entry=config_entry
    )

    _LOGGER.debug("async_setup_entry(): %s", config_entry)

    # await async_setup_entry_helper(hass, switch.DOMAIN, setup, PLATFORM_SCHEMA)

    async def async_discover(discovery_payload):
        """Discover and add an Homie entity"""
        # discovery_data = discovery_payload.discovery_data
        # discovery_data = discovery_payload
        # config = schema(discovery_payload)
        # await async_setup(config, discovery_data=discovery_data)
        _LOGGER.debug("async_discover(): %s", discovery_payload)

        async_add_entities([HomieSwitch(hass, discovery_payload)])

    async_dispatcher_connect(hass, HOMIE_DISCOVERY_NEW.format(SWITCH), async_discover)

    # async_dispatcher_connect(
    #     hass, HOMIE_DISCOVERY_NEW.format(switch.DOMAIN), async_discover
    # )


async def async_setup_entry_helper(hass, domain, async_setup, schema):
    """Set up entity dynamically through Homie discovery."""

    async def async_discover(discovery_payload):
        """Discover and add an Homie entity"""
        # discovery_data = discovery_payload.discovery_data
        discovery_data = discovery_payload
        config = schema(discovery_payload)
        await async_setup(config, discovery_data=discovery_data)

    async_dispatcher_connect(
        hass, "homie_discovery_new".format(SWITCH, "homie"), async_discover
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


from homeassistant.helpers.entity import Entity
from homeassistant.helpers import device_registry
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.config_entries import ConfigEntry


class HomieEntity(Entity):
    """Implementation of a Homie Switch."""

    def __init__(
        self,
        hass: HomeAssistant,
        homie_property: HomieProperty,
        config: ConfigType = None,
        config_entry: ConfigEntry = None,
    ):
        """Initialize Homie Switch."""
        self._hass = hass
        self._homie_property = homie_property
        self._config = config
        self._config_entry = config_entry

        self._homie_node = homie_property.node
        self._homie_device = homie_property.node.device

        self._optimistic = False
        self._unique_id = homie_property.base_topic.replace("/", "-")

        # update also on device change?!
        # self._homie_device.t.add_listener(self._on_change)
        self._homie_property.t.add_listener(self._on_change)

    async def async_added_to_hass(self):
        """Subscribe mqtt events."""
        _LOGGER.debug("HomieEntity.async_added_to_hass()")

        # NON CREDO SERVA => funzione vuota
        # await super().async_added_to_hass()

        # await self._homie_property.node.device.async_setup()

    async def async_will_remove_from_hass(self):
        _LOGGER.debug("async_will_remove_from_hass()")

        # TODO: unsbscribe topics

        # NON CREDO SERVA => funzione vuota
        # await super().async_will_remove_from_hass()

    # convert to async?
    def _on_change(self, topic, value):
        if topic != "set":
            _LOGGER.debug("_on_change %s %s", topic, value)
            self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""

        _LOGGER.debug("extra_state_attributes()")

        property_attrs = {
            f"attr-{topic.lstrip('$')}": value
            for topic, value in self._homie_property.t.dict_value().items()
        }

        stats = {
            f"stat-{topic}": value
            for topic, value in self._homie_device.t.get_obj("$stats")
            .dict_value()
            .items()
        }

        return {
            **property_attrs,
            **stats,
            "ip": self._homie_device.t["$localip"],
            "device-config": self._homie_device.t["$implementation/config"],
        }

    @property
    def device_info(self):
        """Return the device info."""

        _LOGGER.debug("device_info()")

        mac = device_registry.format_mac(self._homie_device.t["$mac"])

        return {"identifiers": {(DOMAIN, mac)}}

    @property
    def should_poll(self):
        """No polling needed."""
        return False

    @property
    def assumed_state(self):
        """Return true if we do optimistic updates."""
        return self._optimistic

    @property
    def available(self):
        """Return if the device is available."""
        return self._homie_device.t.get("$state") == "ready"

    @property
    def name(self):
        """Return the name of the Homie Switch."""
        return self._homie_property.t.get("$name", self._homie_property.id)

    @property
    def icon(self):
        """Return icon of the entity if any."""
        return None  # self._config.get(CONF_ICON)

    @property
    def unique_id(self):
        """Return a unique ID."""
        return self._unique_id


class HomieSwitch(HomieEntity, SwitchEntity, RestoreEntity):
    """Implementation of a Homie Switch."""

    def __init__(
        self,
        hass: HomeAssistant,
        homie_property: HomieProperty,
        config: ConfigType = None,
        config_entry: ConfigEntry = None,
    ):
        """Initialize Homie Switch."""
        HomieEntity.__init__(self, hass, homie_property, config, config_entry)

    async def async_added_to_hass(self):
        """Subscribe mqtt events."""
        _LOGGER.debug("HomieSwitch.async_added_to_hass()")

        await super().async_added_to_hass()
        # await self._homie_property.node.device.async_setup()

        if self._optimistic:
            last_state = await self.async_get_last_state()
            if last_state:
                self._homie_property.value = bool2str(last_state.state == STATE_ON)

    @property
    def is_on(self):
        """Returns true if the Homie Switch is on."""
        return str2bool(self._homie_property.value)

    async def async_turn_on(self, **kwargs):
        """Turn the device on."""
        _LOGGER.debug("async_turn_on()")

        self._homie_property.async_set(TRUE)

        if self._optimistic:
            # Optimistically assume that switch has changed state.
            self._homie_property.value = TRUE
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn the device off."""
        _LOGGER.debug("async_turn_off()")

        self._homie_property.async_set(FALSE)

        if self._optimistic:
            # Optimistically assume that switch has changed state.
            self._homie_property.value = FALSE
            self.async_write_ha_state()
