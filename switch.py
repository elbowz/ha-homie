import logging
import functools
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry, config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.restore_state import RestoreEntity

from homeassistant.const import (
    CONF_OPTIMISTIC,
    STATE_ON,
)

from homeassistant.components import switch
from homeassistant.components.mqtt import valid_subscribe_topic

from .homie import HomieDevice, HomieProperty
from .homie.utils import bool2str, str2bool
from .mixins import (
    async_setup_entry_helper,
    async_entity_conf_get_property,
    async_entity_conf_post_process,
)
from .utils import logger

from .const import (
    DOMAIN,
    CONF_QOS,
    DEFAULT_QOS,
    DATA_KNOWN_DEVICES,
    HOMIE_DISCOVERY_NEW_DEVICE,
    SWITCH,
    _VALID_QOS_SCHEMA,
    CONF_NAME,
    CONF_ICON,
    CONF_UNIQUE_ID,
    CONF_DEVICE_CLASS,
    CONF_ENABLED_BY_DEFAULT,
    CONF_DEVICE,
    CONF_NODE,
    CONF_PROPERTY,
    CONF_PROPERTY_TOPIC,
    TRUE,
    FALSE,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_OPTIMISTIC = False

# Common to PLATFROM (TODO: can be moved in shared lib)
SCHEMA_BASE = {
    vol.Optional(CONF_NAME): cv.string,
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

HOMIE_BASE_PLATFORM_SCHEMA = switch.PLATFORM_SCHEMA.extend(SCHEMA_BASE)


PLATFORM_SCHEMA = HOMIE_BASE_PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_OPTIMISTIC, default=DEFAULT_OPTIMISTIC): cv.boolean,
        # CONF_DEVICE_CLASS present in all entities but differ possible values by platfrom types
        vol.Optional(CONF_DEVICE_CLASS): switch.DEVICE_CLASSES_SCHEMA,
        # TODO: add "external" state_topic (device-node-property)
        # vol.Optional(CONF_STATE_TOPIC): valid_subscribe_topic,
    }
)


@logger()
async def async_setup_platform(
    hass: HomeAssistant, config: ConfigType, async_add_entities, discovery_info=None
):
    """Called if exist a platform entry (ie. 'platform: homie') in configuration.yaml"""
    # Convert property topic to dict form and update config
    async_entity_conf_post_process(config)
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

    homie_property = await async_entity_conf_get_property(hass, config)
    async_add_entities([HomieSwitch(hass, homie_property, config, config_entry)])


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
        return self._config.get(CONF_UNIQUE_ID, self._homie_property.base_topic)


class HomieSwitch(HomieEntity, switch.SwitchEntity, RestoreEntity):
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
