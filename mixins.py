import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers import device_registry, entity_registry
from homeassistant.helpers.entity_registry import EntityRegistry
from homeassistant.helpers.device_registry import DeviceEntry, DeviceRegistry
from homeassistant.helpers.dispatcher import (
    async_dispatcher_send,
    async_dispatcher_connect,
)
from homeassistant.const import CONF_PLATFORM

from .homie import HomieDevice
from .utils import logger

from .const import (
    DOMAIN,
    HOMIE_DISCOVERY_NEW,
    SWITCH,
    BINARY_SENSOR,
    SENSOR,
    CONF_PROPERTY,
    CONF_DEVICE,
    CONF_NODE,
    CONF_NAME,
)

_LOGGER = logging.getLogger(__name__)


@callback
def async_create_ha_device(
    hass: HomeAssistant,
    device: HomieDevice,
    entry: ConfigEntry,
    dr: DeviceRegistry = None,
) -> DeviceEntry:
    """Add (or update if already present) device to HA device registry

    https://developers.home-assistant.io/docs/device_registry_index#defining-devices"""
    mac = device_registry.format_mac(device.t["$mac"])

    # map HomieDevice cls and DeviceEntry attrs
    device_registry_entry = {
        "config_entry_id": entry.entry_id,
        "identifiers": {(DOMAIN, mac)},
        "connections": {(device_registry.CONNECTION_NETWORK_MAC, mac)},
        "name": device.t.get("$name", device.id),
        "model": device.t["$implementation"],
        "manufacturer": f"homie-{device.t['$homie']}",
        "sw_version": device.t["$fw/version"],
    }

    if dr is None:
        dr = device_registry.async_get(hass)

    # add/update device in registry
    return dr.async_get_or_create(**device_registry_entry)


@callback
def async_discover_properties(
    hass: HomeAssistant,
    device: HomieDevice,
    er: EntityRegistry = None,
):

    if er is None:
        er = entity_registry.async_get(hass)

    def fire_homie_discovery_new(platform: str, unique_id: str, payload: ConfigType):
        if not er.async_get_entity_id(platform, DOMAIN, unique_id):
            async_dispatcher_send(
                hass, HOMIE_DISCOVERY_NEW.format(platform), discovery_payload
            )

    for node in device.nodes.values():
        for property in node.properties.values():

            # TODO: check include/exclude on property.base_topic

            # Entity already in the registry (use base_topic as unique_id)
            # if er.async_is_registered(property.base_topic):
            #     return False

            discovery_payload = {
                CONF_PROPERTY: {
                    CONF_DEVICE: device.id,
                    CONF_NODE: node.id,
                    CONF_NAME: property.id,
                }
            }

            platform_domain = None

            if property.settable:
                # Actuators
                if property.datatype == "boolean":
                    platform_domain = SWITCH
            else:
                # Sensors
                if property.datatype == "boolean":
                    platform_domain = BINARY_SENSOR
                else:
                    platform_domain = SENSOR

            if platform_domain:
                fire_homie_discovery_new(
                    platform_domain, property.base_topic, discovery_payload
                )


async def async_setup_entry_helper(hass, domain, async_setup, schema):
    """Setup entity creation dynamically through discovery."""

    async def async_discover(discovery_payload):
        """Discover and add an Homie property as HA entity."""

        # Add the schama mandatory key
        discovery_payload[CONF_PLATFORM] = DOMAIN

        try:
            config = schema(discovery_payload)
            await async_setup(config)
        except Exception:
            raise

    async_dispatcher_connect(hass, HOMIE_DISCOVERY_NEW.format(domain), async_discover)
