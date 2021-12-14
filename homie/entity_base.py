import logging
import voluptuous as vol

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry, config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.typing import ConfigType

from homeassistant.components.mqtt import valid_subscribe_topic

from .homie import HomieDevice, HomieProperty

from .const import (
    DOMAIN,
    CONF_QOS,
    DEFAULT_QOS,
    DATA_KNOWN_DEVICES,
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
)

_LOGGER = logging.getLogger(__name__)

# Common to PLATFROM (TODO: can be moved in shared lib)
SCHEMA_BASE = vol.Schema(
    {
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
)


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
        """Subscribe to HomieProperty events."""
        # await self._homie_property.node.device.async_setup()

        self._homie_device.subscribe(self._async_on_device_change)
        self._homie_property.subscribe(self._async_on_property_change)

    async def async_will_remove_from_hass(self):
        # TODO: unsbscribe topics
        pass

    async def _async_on_device_change(self, homie_component, topic, value):
        """Callend on device topic or childrens (ie. nodes, property) change."""
        if isinstance(homie_component, HomieDevice):
            self.async_write_ha_state()

    async def _async_on_property_change(self, homie_property, topic, value):
        """Callend on property topic change."""
        if topic != "set":
            self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""

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
            "base_topic": self._homie_property.base_topic,
            **property_attrs,
            **stats,
            "ip": self._homie_device.t["$localip"],
            "device-config": self._homie_device.t["$implementation/config"],
            "state": self._homie_device.t["$state"],
        }

    @property
    def device_info(self):
        """Return the device info."""

        # map HomieDevice and DeviceEntry attrs
        device_registry_entry = {
            "identifiers": {(DOMAIN, self._homie_device.id)},
            "config_entry_id": self._config_entry.entry_id,
            "name": self._homie_device.t.get("$name", self._homie_device.id),
            "model": self._homie_device.t["$implementation"],
            "manufacturer": f"homie-{self._homie_device.t['$homie']}",
            "sw_version": self._homie_device.t["$fw/version"],
        }

        if mac := self._homie_device.t["$mac"]:
            mac = device_registry.format_mac(mac)

            device_registry_entry["connections"] = {
                (device_registry.CONNECTION_NETWORK_MAC, mac)
            }

        # note: using only identifiers (as foreign key) could create trouble when no device is in the device registry (ie device not ready)
        # return {"identifiers": {(DOMAIN, mac)}}

        return device_registry_entry

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
        """Return the name to display in UI."""
        return self._config.get(
            CONF_NAME,
            self._homie_property.t.get(
                "$name", f"{self._homie_device.id} > {self._homie_property.id}"
            ),
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


async def async_get_homie_property(
    hass: HomeAssistant, config: ConfigType
) -> HomieProperty:
    """"""
    device_id = config[CONF_PROPERTY][CONF_DEVICE]
    node_id = config[CONF_PROPERTY][CONF_NODE]
    property_id = config[CONF_PROPERTY][CONF_NAME]

    if (device := hass.data[DATA_KNOWN_DEVICES].get(device_id)) is None:
        raise ValueError("Specified {device_id} not exist")

    # TODO: convert HomieDevice and HomieNode .node/__getitem__ to async and raise a keyvalue exception

    if not await device.async_has_node(node_id):
        raise ValueError("Specified {node_id} not exist")
    if not await device[node_id].async_has_property(property_id):
        raise ValueError("Specified {property_id} not exist")

    return device[node_id][property_id]


def schema_post_processing(config: ConfigType) -> ConfigType:
    """Convert property topic path string in the dict form and
    validate entry has at least one property value."""

    if not (config.get(CONF_PROPERTY) or config.get(CONF_PROPERTY_TOPIC)):
        raise vol.Invalid(
            f"Platform must have at least '{CONF_PROPERTY}' or "
            f"'{CONF_PROPERTY_TOPIC}' to indentify the Homie Property"
        )

    if property_topic := config.get(CONF_PROPERTY_TOPIC):

        topic_split: list = property_topic.strip("/").split("/")[-3:]

        if len(topic_split) != 3:
            raise ValueError(
                f"The '{CONF_PROPERTY_TOPIC}' ({property_topic}) "
                "is not in the right format!"
            )

        config[CONF_PROPERTY] = dict(
            zip((CONF_DEVICE, CONF_NODE, CONF_NAME), topic_split)
        )

        del config[CONF_PROPERTY_TOPIC]

    return config
