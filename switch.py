# IMPORT
import functools
import logging

import voluptuous as vol

from homeassistant.components import switch
from homeassistant.components.mqtt.switch import MqttSwitch
from homeassistant.components.switch import (
    DEVICE_CLASSES_SCHEMA,
    PLATFORM_SCHEMA,
    SwitchEntity,
)

from homeassistant.components.mqtt import valid_subscribe_topic

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
    CONF_ICON,
    CONF_UNIQUE_ID,
    CONF_DEVICE_CLASS,
    STATE_ON,
)

from . import (
    DOMAIN,
    PLATFORMS,
    HOMIE_CONFIG,
    KEY_HOMIE_ALREADY_DISCOVERED,
    KEY_HOMIE_ENTITY_NAME,
    HomieDevice,
    HomieProperty,
    CONF_BASE_TOPIC,
    CONF_QOS,
    DEFAULT_QOS,
    _VALID_QOS_SCHEMA,
    TRUE,
    FALSE,
)

# CONSTANTS
_LOGGER = logging.getLogger(__name__)

DEFAULT_OPTIMISTIC = False
CONF_ENABLED_BY_DEFAULT = "enabled_by_default"
CONF_DEVICE = "device"
CONF_NODE = "node"
CONF_PROPERTY = "property"
CONF_PROPERTY_TOPIC = "property_topic"

# Common to PLATFROM
SCHEMA_BASE = {
    vol.Optional(CONF_NAME): cv.string,
    vol.Optional(CONF_BASE_TOPIC): cv.string,
    vol.Optional(CONF_ICON): cv.icon,
    vol.Optional(CONF_UNIQUE_ID): cv.string,
    vol.Optional(CONF_ENABLED_BY_DEFAULT, default=True): cv.boolean,
    vol.Optional(CONF_QOS, default=DEFAULT_QOS): _VALID_QOS_SCHEMA,
    vol.Exclusive(CONF_PROPERTY, "property"): vol.Schema(
        {
            vol.Required(CONF_DEVICE): cv.string,
            vol.Required(CONF_NODE): cv.string,
            vol.Required(CONF_NAME): cv.string,
        }
    ),
    vol.Exclusive(CONF_PROPERTY_TOPIC, "property"): valid_subscribe_topic,
}

HOMIE_BASE_PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend(SCHEMA_BASE)


PLATFORM_SCHEMA = HOMIE_BASE_PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_OPTIMISTIC, default=DEFAULT_OPTIMISTIC): cv.boolean,
        # CONF_DEVICE_CLASS present in all entities but differ possible values by platfrom type
        vol.Optional(CONF_DEVICE_CLASS): DEVICE_CLASSES_SCHEMA,
        # TODO: add "external" state_topic (device-node-property)
        # vol.Optional(CONF_STATE_TOPIC): valid_subscribe_topic,
    }
)


async def async_setup_platform(
    hass: HomeAssistant, config: ConfigType, async_add_entities, discovery_info=None
):
    """Called if exist a platform entry (ie. 'platform: homie') in configuration.yaml"""
    # await async_setup_reload_service(hass, DOMAIN, PLATFORMS)
    # await _async_setup_entity(hass, async_add_entities, config)

    _LOGGER.debug("async_setup_platform() %s %s", config, hass.data.get(HOMIE_CONFIG))
    return
    device = HomieDevice(
        hass,
        "bdiot/thumbl-p-dev",
        config.get(CONF_QOS),
    )

    await device.async_setup()

    if await device.async_has_node("light"):
        if await device["light"].async_has_property("light"):
            async_add_entities([HomieSwitch(hass, device["light"]["light"], config)])


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
        config: ConfigType = {},
        config_entry: ConfigEntry = None,
    ):
        """Initialize Homie Switch."""
        self.hass = hass
        self._homie_property = homie_property
        self._config = config
        self._config_entry = config_entry

        self._homie_node = homie_property.node
        self._homie_device = homie_property.node.device

        self._unique_id = homie_property.base_topic.replace("/", "-")

    async def async_added_to_hass(self):
        """Subscribe mqtt events."""
        _LOGGER.debug("HomieEntity.async_added_to_hass()")

        # NON CREDO SERVA => funzione vuota
        # await super().async_added_to_hass()

        # await self._homie_property.node.device.async_setup()

        # update also on device change?!
        # self._homie_device.t.add_listener(self._on_change)
        # self._homie_property.t.add_listener(self._on_change)
        self._homie_property.subscribe(self._on_change)

    async def async_will_remove_from_hass(self):
        _LOGGER.debug("async_will_remove_from_hass()")

        # TODO: unsbscribe topics

        # NON CREDO SERVA => funzione vuota
        # await super().async_will_remove_from_hass()

    # convert to async?
    async def _on_change(self, cls, topic, value):
        if topic != "set":
            _LOGGER.debug("_on_change %s %s %s", cls, topic, value)
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
            "state": self._homie_device.t["$state"],
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
    def available(self):
        """Return if the device is available."""
        return self._homie_device.t.get("$state") == "ready"

    @property
    def name(self):
        """Return the name of the Homie Switch."""
        return self._config.get(
            CONF_NAME, self._homie_property.t.get("$name", self._homie_property.id)
        )

    @property
    def icon(self):
        """Return icon of the entity if any."""
        return self._config.get(CONF_ICON)

    @property
    def device_class(self):
        """Return icon of the entity if any."""
        return self._config.get(CONF_DEVICE_CLASS)

    @property
    def unique_id(self):
        """Return a unique ID."""
        return self._config.get(CONF_UNIQUE_ID, self._unique_id)


class HomieSwitch(HomieEntity, SwitchEntity, RestoreEntity):
    """Implementation of a Homie Switch."""

    def __init__(
        self,
        hass: HomeAssistant,
        homie_property: HomieProperty,
        config: ConfigType = {},
        config_entry: ConfigEntry = None,
    ):
        """Initialize Homie Switch."""
        HomieEntity.__init__(self, hass, homie_property, config, config_entry)

        self._optimistic = self._config.get(CONF_OPTIMISTIC)

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

    @property
    def assumed_state(self):
        """Return true if we do optimistic updates."""
        return self._optimistic
