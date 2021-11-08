import re
import asyncio
import logging
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry, dispatcher, config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.const import EVENT_HOMEASSISTANT_STOP

import homeassistant.components.mqtt as mqtt

from .homie import HomieDevice

from .mixins import (
    async_create_ha_device,
    async_discover_properties,
)

from .utils import logger

from .const import (
    DISCOVERY_TOPIC,
    DOMAIN,
    DATA_HOMIE_CONFIG,
    DATA_KNOWN_DEVICES,
    CONF_BASE_TOPIC,
    CONF_DISCOVERY,
    CONF_QOS,
    CONF_INCLUDE,
    CONF_EXCLUDE,
    _VALID_QOS_SCHEMA,
    DEFAULT_BASE_TOPIC,
    DEFAULT_QOS,
    DEFAULT_DISCOVERY,
    PLATFORMS,
    HOMIE_DISCOVERY_NEW_DEVICE,
    HOMIE_SUPPORTED_VERSION,
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(
                    CONF_BASE_TOPIC, default=DEFAULT_BASE_TOPIC
                ): mqtt.valid_subscribe_topic,
                vol.Optional(CONF_QOS, default=DEFAULT_QOS): _VALID_QOS_SCHEMA,
                vol.Optional(CONF_DISCOVERY, default=DEFAULT_DISCOVERY): cv.boolean,
                vol.Optional(CONF_INCLUDE, default=[]): vol.All(
                    cv.ensure_list, [cv.string]
                ),
                vol.Optional(CONF_EXCLUDE, default=[]): vol.All(
                    cv.ensure_list, [cv.string]
                ),
            }
        ),
    },
    extra=vol.ALLOW_EXTRA,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Setup component from yaml configuration.

    Called with or w/o DOMAIN entry in configuration.yaml
    """

    conf = config.get(DOMAIN)

    # No DOMAIN entry in configuration.yaml
    if conf is None:
        return True
        # Return True if a config entry (ie UI form / config flow) exist
        # note: If return False also after an UI setup I need to retart HA to load the config_entry
        # return bool(hass.config_entries.async_entries(DOMAIN))

    conf = dict(conf)

    # Saved for later use (eg. config entry flow)
    hass.data[DATA_HOMIE_CONFIG] = conf

    # There is NOT a config entry yet
    if not hass.config_entries.async_entries(DOMAIN):
        # Import/copy the config (configuration.yaml) in a config entry
        # Call the method ConfigFlow.async_step_import()
        # https://developers.home-assistant.io/docs/data_entry_flow_index#initializing-a-config-flow-from-an-external-source
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data={}
            )
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Setup platform from a ConfigEntry."""

    # Get configuration.yaml (saved in async_setup())
    conf = hass.data.get(DATA_HOMIE_CONFIG)

    # Config entry was created because user had configuration.yaml entry
    # They removed that (conf is None and source = "import"), so remove entry.
    if conf is None and entry.source == config_entries.SOURCE_IMPORT:
        hass.async_create_task(hass.config_entries.async_remove(entry.entry_id))
        return False

    # If user didn't have configuration.yaml, generate defaults
    if conf is None:
        conf = CONFIG_SCHEMA({DOMAIN: dict(entry.data)})[DOMAIN]
        # TODO: should do the same, since below I'll merge the two dict?!
        # conf = CONFIG_SCHEMA({DOMAIN: dict()})[DOMAIN]

    # Else advise the user with the override policies in the log
    elif any(key in conf for key in entry.data):
        shared_keys = conf.keys() & entry.data.keys()
        override = {k: entry.data[k] for k in shared_keys}

        _LOGGER.info(
            "Data in your configuration entry is going to override your configuration.yaml: %s",
            override,
        )

    # Merge/extend configuration.yaml config with config entry
    conf = {**conf, **entry.data}

    async def async_setup_platforms():
        """Setup platforms."""

        # Call the async_setup_entry(entry, platform) of the supportted platforms
        await asyncio.gather(
            *(
                hass.config_entries.async_forward_entry_setup(entry, platform)
                for platform in PLATFORMS
            )
        )

    hass.async_create_task(async_setup_platforms())

    # Starting devices discovery
    await _async_setup_discovery(hass, conf, entry)

    return True


# REGEX
DISCOVER_DEVICE = re.compile(
    r"(?P<prefix_topic>\w[-/\w]*\w)/(?P<device_id>\w[-\w]*\w)/\$homie"
)

# TODO: take inspiration from mqtt.discovery ?! => separated file with a function


@logger()
async def _async_setup_discovery(
    hass: HomeAssistant, conf: ConfigType, entry: ConfigEntry
) -> bool:
    """Start component (ie Discovery)."""

    if conf is None:
        # Init with default values
        conf = CONFIG_SCHEMA({DOMAIN: {}})[DOMAIN]

    # Init discovered devices "registry"
    devices = hass.data.setdefault(DATA_KNOWN_DEVICES, dict())

    qos = conf.get(CONF_QOS)
    discovery_enabled = conf.get(CONF_DISCOVERY)
    base_topic = conf.get(CONF_BASE_TOPIC).strip("/")
    discovery_topic = DISCOVERY_TOPIC.format(base_topic)

    # Clear HA device registry (associated to the current config entry)
    dr = device_registry.async_get(hass)
    dr.async_clear_config_entry(entry.entry_id)

    @logger()
    async def async_discovery_message_received(mqttmsg: mqtt.models.ReceiveMessage):
        """Subscribed on discovery_topic."""

        # Apply regex to extract device id and prefix_topic
        device_match = DISCOVER_DEVICE.match(mqttmsg.topic)

        if device_match and mqttmsg.payload in HOMIE_SUPPORTED_VERSION:

            device_id = device_match.group("device_id")
            device_prefix_topic = device_match.group("prefix_topic")

            # Check if already discovered and added
            if device_id not in devices:

                device = HomieDevice(
                    hass,
                    f"{device_prefix_topic}/{device_id}",
                    qos,
                    async_device_on_ready,
                )

                devices[device_id] = device

                # Init (topics subscribe) device
                await device.async_setup()

                # Fire event to inform the presence of a new device in the global (hass.data) var
                dispatcher.async_dispatcher_send(
                    hass, HOMIE_DISCOVERY_NEW_DEVICE.format(device_id)
                )

    # @logger()
    async def async_device_on_ready(homie_device):
        # TODO: check include/exclude on device.base_topic

        # Add/update device to HA device registry
        async_create_ha_device(hass, homie_device, entry)

        if discovery_enabled:
            #
            async_discover_properties(hass, homie_device)

    async def async_destroy(event):
        """Stuff to do on close"""
        pass

    # Call on HA close
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_destroy)

    await mqtt.async_subscribe(
        hass, discovery_topic, async_discovery_message_received, qos
    )

    return True
