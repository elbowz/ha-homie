from __future__ import annotations
from abc import abstractmethod

# IMPORTS
import asyncio
import logging
import re
import time
import datetime
import voluptuous as vol
import functools
import sys


import homeassistant.components.mqtt as mqtt
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.components.mqtt import (
    valid_subscribe_topic,
    subscription,
)
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers import config_validation as cv
from homeassistant.const import (
    EVENT_HOMEASSISTANT_STOP,
    STATE_UNKNOWN,
    CONF_INCLUDE,
    CONF_EXCLUDE,
)
from homeassistant.core import callback

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from homeassistant.helpers import device_registry

from .helpers import TopicDict, str2bool, bool2str

# TYPES
from typing import Callable, Dict, List, Union, Any
from homeassistant.helpers.typing import ConfigType, ServiceDataType
from voluptuous.validators import Boolean

# REGEX
DISCOVER_DEVICE = re.compile(
    r"(?P<prefix_topic>\w[-/\w]*\w)/(?P<device_id>\w[-\w]*\w)/\$homie"
)

# CONSTANTS
from .const import (
    DISCOVERY_TOPIC,
    DOMAIN,
    HOMIE_CONFIG,
    CONF_BASE_TOPIC,
    CONF_DISCOVERY,
    CONF_QOS,
    _VALID_QOS_SCHEMA,
    DEFAULT_BASE_TOPIC,
    DEFAULT_QOS,
    DEFAULT_DISCOVERY,
    PLATFORMS,
    HOMIE_DISCOVERY_NEW,
    HOMIE_SUPPORTED_VERSION,
    SWITCH,
    TRUE,
    FALSE,
)


KEY_HOMIE_ALREADY_DISCOVERED = "KEY_HOMIE_ALREADY_DISCOVERED"
KEY_HOMIE_ENTITY_NAME = "KEY_HOMIE_ENTITY_ID"

# CONFIg
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(
                    CONF_BASE_TOPIC, default=DEFAULT_BASE_TOPIC
                ): valid_subscribe_topic,
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
    # TODO: remove?
    extra=vol.ALLOW_EXTRA,
)


# GLOBALS
_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Setup component from yaml configuration.

    Called with or w/o DOMAIN entry in configuration.yaml
    """

    conf: ConfigType | None = config.get(DOMAIN)

    # if no DOMAIN entry in configuration.yaml
    if conf is None:
        # ...but a config entry (ie UI form) exist => exit
        return bool(hass.config_entries.async_entries(DOMAIN))

    conf = dict(conf)

    # saved for using in the config entry flow later
    hass.data[HOMIE_CONFIG] = conf

    # there is no config entry yet
    if not hass.config_entries.async_entries(DOMAIN):
        # call the class ConfigFlow.async_step_import to create a config entry for yaml
        # ...and the async_setup_entry with the new created entry
        # https://developers.home-assistant.io/docs/data_entry_flow_index#initializing-a-config-flow-from-an-external-source
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data={}
            )
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Setup platform from a ConfigEntry."""

    # get configuration.yaml (saved in async_setup)
    conf = hass.data.get(HOMIE_CONFIG)

    # Config entry was created because user had configuration.yaml entry
    # They removed that (conf is None and source = "import"), so remove entry.
    if conf is None and entry.source == config_entries.SOURCE_IMPORT:
        hass.async_create_task(hass.config_entries.async_remove(entry.entry_id))
        return False

    # if user didn't have configuration.yaml, generate defaults
    if conf is None:
        conf = CONFIG_SCHEMA({DOMAIN: dict(entry.data)})[DOMAIN]
    # else advise the user the override policy in the log
    elif any(key in conf for key in entry.data):
        shared_keys = conf.keys() & entry.data.keys()
        override = {k: entry.data[k] for k in shared_keys}
        # if CONF_PASSWORD in override:
        #    override[CONF_PASSWORD] = "********"
        _LOGGER.info(
            "Data in your configuration entry is going to override your "
            "configuration.yaml: %s",
            override,
        )

    conf = _merge_config(entry, conf)

    async def setup_platforms():
        """Setup platforms."""
        await asyncio.gather(
            *(
                hass.config_entries.async_forward_entry_setup(entry, platform)
                for platform in PLATFORMS
            )
        )

    hass.async_create_task(setup_platforms())

    await async_setup_disabled(hass, hass.data.get(HOMIE_CONFIG), entry)

    dr = device_registry.async_get(hass)

    # device_registry.async_get_or_create(
    #     config_entry_id=entry.entry_id,
    #     identifiers={(DOMAIN, "83459345346")},
    #     name="device name homie 23",
    #     manufacturer="manufacture home 2",
    #     model="model homie 2",
    #     sw_version="1.4",
    # )

    dr.async_clear_config_entry(entry.entry_id)

    return True


def _merge_config(entry, conf):
    """Merge configuration.yaml config with config entry."""
    return {**conf, **entry.data}


# DELETE
import types


def imports():
    for name, val in globals().items():
        if isinstance(val, types.ModuleType):
            yield val.__name__


async def async_setup_disabled(hass: HomeAssistant, config: ConfigType, entry):
    """Setup the Homie service."""
    # Init
    _DEVICES = dict()
    hass.data[KEY_HOMIE_ALREADY_DISCOVERED] = dict()

    _LOGGER.debug("async_setup")

    conf = config
    # Config
    # conf = config.get(DOMAIN)
    if conf is None:
        conf = CONFIG_SCHEMA({DOMAIN: {}})[DOMAIN]

    base_topic = conf.get(CONF_BASE_TOPIC).strip("/")
    discovery_topic = DISCOVERY_TOPIC.format(base_topic)
    qos = conf.get(CONF_QOS)

    _LOGGER.debug("DEBUG discovery_topic %s", discovery_topic)

    # Destroy Homie
    # async def async_destroy(event):
    #     # TODO: unsub?
    #     pass
    # hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_destroy)

    # Sart
    async def async_start():

        await mqtt.async_subscribe(
            hass, discovery_topic, async_discover_message_received, qos
        )

    async def async_discover_message_received(mqttmsg: ReceiveMessage):

        device_match = DISCOVER_DEVICE.match(mqttmsg.topic)

        if device_match and mqttmsg.payload in HOMIE_SUPPORTED_VERSION:

            device_prefix_topic = device_match.group("prefix_topic")
            device_id = device_match.group("device_id")

            if device_id not in _DEVICES:

                device = HomieDevice(
                    hass,
                    device_prefix_topic + "/" + device_id,
                    qos,
                    async_component_change,
                )

                _DEVICES[device_id] = device
                await device.async_setup()

                _LOGGER.debug(
                    "async_discover_message_received %s : %s",
                    mqttmsg.topic,
                    mqttmsg.payload,
                )

    async def async_component_change(component, topic, value):
        # _LOGGER.debug(
        #     "async_component_change %s, %s, %s", type(component), topic, value
        # )

        # Ready
        if type(component) is HomieDevice and topic == "$state" and value == "ready":
            await asyncio.sleep(10)
            await async_setup_device(component)

    async def async_setup_device(device: HomieDevice):
        _LOGGER.debug("async_setup_device %s ", device.id)

        # TODO: check include/exclude on device.base_topic

        mac = device_registry.format_mac(device.t["$mac"])

        device_registry_entry = {
            "config_entry_id": entry.entry_id,
            "identifiers": {(DOMAIN, mac)},
            "connections": {(device_registry.CONNECTION_NETWORK_MAC, mac)},
            "name": device.t.get("$name", device.id),
            "model": device.t["$implementation"],
            "manufacturer": f"homie-{device.t['$homie']}",
            "sw_version": device.t["$fw/version"],
        }

        dr = device_registry.async_get(hass)

        dr.async_get_or_create(**device_registry_entry)

        for node in device.nodes.values():

            # TODO: check include/exclude on node.base_topic

            for property in node.properties.values():

                # TODO: check include/exclude on property.base_topic

                # TODO: check if already added
                # device_registry = await hass.helpers.device_registry.async_get(hass)
                # entity_registry = await self.hass.helpers.entity_registry.async_get(hass)
                # if entity_registry.async_is_registered(self.entity_id):
                #     entity_entry = entity_registry.async_get(self.entity_id)

                if property.settable and property.datatype == "boolean":
                    async_dispatcher_send(
                        hass, HOMIE_DISCOVERY_NEW.format(SWITCH), property
                    )

    async def async_setup_node(node: HomieNode):
        def get_entity_name():
            return f"{node.device.device_id}_{node.node_id}"

        _LOGGER.debug("async_setup_node %s ", HomieNode.node_id)

        if node.type == "sensor":
            await setup_device_node_as_platform(get_entity_name(), node, "sensor")
        elif node.type == "switch":
            await setup_device_node_as_platform(get_entity_name(), node, "switch")

    async def setup_device_node_as_platform(
        entity_name: str, node: HomieNode, platform: str
    ):
        hass.data[KEY_HOMIE_ALREADY_DISCOVERED][entity_name] = node
        discovery_info = {KEY_HOMIE_ENTITY_NAME: entity_name}
        # await async_load_platform(hass, platform, DOMAIN, discovery_info, conf)

        """    async with stuff_lock:
            await hass.config_entries.async_forward_entry_setup(entry, switch.DOMAIN) """

        async_dispatcher_send(
            hass,
            "homie_discovery_new".format(switch.DOMAIN, "homie"),
            discovery_info,
        )

    await async_start()
    return True


# TODO: use also in TopicDict?! and/or implement bubbling in TopicDict?
class Observable(object):
    def __init__(self):
        self._callbacks = []

    def subscribe(self, callback):
        self._callbacks.append(callback)

    async def _async_call_subscribers(self, *attrs, **kwargs):
        for fn in self._callbacks:
            await fn(*attrs, **kwargs)


class HomieBase(Observable):
    def __init__(
        self,
        hass: HomeAssistant,
        base_topic: str,
        qos: int = 0,
        topic_dict: TopicDict = None,
        async_on_change: Any[Callable, None] = None,
    ):
        Observable.__init__(self)
        self.id, self.base_topic = TopicDict.topic_get_head(base_topic)

        if self.id is False:
            raise ValueError(
                "Provide the full topic (eg. 'homie/device-id', 'homie/device-id/node-id'): %s"
                % self.base_topic
            )

        self.topic_dict = topic_dict if topic_dict else TopicDict()
        self.topic_dict.add_listener(self._update_topic_dict)

        self._hass = hass
        self._qos = qos

        if async_on_change:
            self.subscribe(async_on_change)

    async def _async_update(self, mqttmsg: ReceiveMessage):
        topic = mqttmsg.topic.removeprefix(self.base_topic).strip("/")

        # _LOGGER.debug(
        #     "%s._async_update() %s (%s) -> %s",
        #     self.__class__.__name__,
        #     mqttmsg.topic,
        #     topic,
        #     mqttmsg.payload,
        # )

        if topic == "":
            self.topic_dict.value = mqttmsg.payload
        else:
            self.topic_dict[topic] = mqttmsg.payload

    def _update_topic_dict(self, topic, value):

        # _LOGGER.debug(
        #     "%s._update_topic_dict %s -> %s",
        #     self.__class__.__name__,
        #     topic,
        #     value,
        # )

        # Call the async version
        self._hass.loop.create_task(self._async_update_topic_dict(topic, value))
        # Call the subscribed functions (Observable)
        self._hass.loop.create_task(self._async_call_subscribers(self, topic, value))

    @abstractmethod
    async def _async_update_topic_dict(self, topic, value):
        raise NotImplementedError()

    @property
    def t(self):
        return self.topic_dict


class HomieDevice(HomieBase):
    # A definition of a Homie Device
    def __init__(
        self,
        hass: HomeAssistant,
        base_topic: str,
        qos: int,
        async_on_change: Any[Callable, None] = None,
    ):
        super().__init__(hass, base_topic, qos, async_on_change=async_on_change)

        self.nodes: dict[str, HomieNode] = dict()

        self.topic_dict.add_include_topic("^\$")

        self._sub_state = None

    async def async_setup(self):

        # Topics (and callback) to subscribe
        sub_topics = {
            "base": {"topic": f"{self.base_topic}/+"},
            "stats": {"topic": f"{self.base_topic}/$stats/#"},
            "fw": {"topic": f"{self.base_topic}/$fw/#"},
            "implementation": {"topic": f"{self.base_topic}/$implementation/#"},
            # "nodes": {
            #     "topic": f"{self.base_topic}/+/$properties",
            #     "msg_callback": _async_update_nodes,
            # },
        }

        sub_base = {
            "msg_callback": self._async_update,
            "qos": self._qos,
        }

        sub_topics = {
            name: {**sub_base, **value} for (name, value) in sub_topics.items()
        }

        self._sub_state = await subscription.async_subscribe_topics(
            self._hass, self._sub_state, sub_topics
        )

    async def async_unsubscribe_topics(self):
        self._sub_state = await subscription.async_unsubscribe_topics(
            self._hass, self._sub_state
        )
        # TODO: add nodes unsubscribe

    async def _async_update_topic_dict(self, topic, value):

        if topic == "$nodes":
            for node_id in value.split(","):
                # TODO: add nodes restiction list
                if node_id not in self.nodes:
                    node = HomieNode(self, self.base_topic + "/" + node_id)
                    self.nodes[node_id] = node
                    await node.async_setup()

    def node(self, node_id: str):
        """Return a specific Node for the device."""
        return self.nodes[node_id]

    def __getitem__(self, node_id: str):
        return self.node(node_id)


class HomieNode(HomieBase):
    # A definition of a Homie Node
    def __init__(self, device: HomieDevice, base_topic: str):
        super().__init__(device._hass, base_topic, device._qos)

        self.device = device
        self.properties: dict[str, HomieProperty] = dict()

        self.device.topic_dict.set(self.id, self.topic_dict, force=True)

        self.topic_dict.add_include_topic("^\$")

    async def async_setup(self):
        self._async_unsubscribe_topics = await mqtt.async_subscribe(
            self._hass, f"{self.base_topic}/+", self._async_update, self._qos
        )

    async def async_unsubscribe_topics(self):
        self._async_unsubscribe_topics()

        # TODO: add properties unsubscribe

    async def _async_update_topic_dict(self, topic, value):

        # notes: can be removed this method and call node.async_setup() by create_task
        if topic == "$properties":
            for property_id in value.split(","):
                if property_id not in self.properties:
                    # TODO: add properties restiction list
                    property = HomieProperty(self, self.base_topic + "/" + property_id)
                    self.properties[property_id] = property
                    await property.async_setup()

    async def _async_call_subscribers(self, *attrs, **kwargs):
        await super()._async_call_subscribers(*attrs, **kwargs)
        await self.device._async_call_subscribers(*attrs, **kwargs)

    def has_property(self, property_id: str):
        """Return a specific Property for the node."""
        return property_id in self.properties

    def property(self, property_id: str):
        """Return a specific Property for the Node."""
        return self.properties[property_id]

    def __getitem__(self, property_id: str):
        return self.property(property_id)


class HomieProperty(HomieBase):
    # A definition of a Homie Property
    def __init__(self, node: HomieNode, base_topic: str):
        super().__init__(node._hass, base_topic, node._qos)

        self.node = node
        self.node.topic_dict.set(self.id, self.topic_dict, force=True)

    async def async_setup(self):
        self.async_unsubscribe_topics = await mqtt.async_subscribe(
            self._hass, f"{self.base_topic}/#", self._async_update, self._qos
        )

    async def _async_call_subscribers(self, *attrs, **kwargs):
        await super()._async_call_subscribers(*attrs, **kwargs)
        await self.node._async_call_subscribers(*attrs, **kwargs)

    async def _async_update_topic_dict(self, topic, value):
        pass

    @callback
    def async_set(self, value: str):
        """Set the state of the Property."""
        if self.settable:
            mqtt.async_publish(
                self._hass, f"{self.base_topic}/set", value, self._qos, retain=True
            )

    @property
    def value(self):
        return self.topic_dict.value

    @value.setter
    def value(self, value):
        self.topic_dict.value = value

    @property
    def settable(self):
        """Return if the Property is settable."""
        value = self.topic_dict.get("$settable", FALSE)
        return str2bool(value)

    @property
    def datatype(self):
        """Return Property type."""
        value = self.topic_dict.get("$datatype", STATE_UNKNOWN)
        return value
