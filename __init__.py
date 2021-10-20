from __future__ import annotations

# IMPORTS
import asyncio
import logging
import re
import time
import datetime
import voluptuous as vol
import functools
from homeassistant.components import switch
import homeassistant.components.mqtt as mqtt
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.components.mqtt import (
    CONF_DISCOVERY_PREFIX,
    CONF_QOS,
    valid_subscribe_topic,
    _VALID_QOS_SCHEMA,
    subscription,
)
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers import config_validation as cv
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, STATE_UNKNOWN
from homeassistant.core import callback

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

# TYPES
from typing import Dict, List, Union, Any
from homeassistant.helpers.typing import ConfigType, ServiceDataType

# REGEX
DISCOVER_DEVICE = re.compile(
    r"(?P<prefix_topic>\w[-/\w]*\w)/(?P<device_id>\w[-\w]*\w)/\$homie"
)
DISCOVER_NODES = re.compile(
    r"(?P<prefix_topic>\w[-/\w]*\w)/(?P<node_id>\w[-\w]*\w)/\$properties"
)
DISCOVER_PROPERTIES = re.compile(
    r"(?P<property_id>\w[-/\w]*\w)(\[(?P<range_start>[0-9])-(?P<range_end>[0-9]+)\])?(?P<settable>:settable)?"
)

# CONSTANTS
from .const import DATA_HOMIE_CONFIG, DOMAIN, PLATFORMS

# PLATFORMS = ["binary_sensor", "light", "number", "sensor", "switch"]

DEPENDENCIES = ["mqtt"]
INTERVAL_SECONDS = 1
MESSAGE_MAX_KEEP_SECONDS = 5
HOMIE_SUPPORTED_VERSION = ["3.0.0", "3.0.1", "4.0.0"]
DEFAULT_DISCOVERY_PREFIX = "homie"
DEFAULT_QOS = 1
KEY_HOMIE_ALREADY_DISCOVERED = "KEY_HOMIE_ALREADY_DISCOVERED"
KEY_HOMIE_ENTITY_NAME = "KEY_HOMIE_ENTITY_ID"

# CONFIg
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(
                    CONF_DISCOVERY_PREFIX, default=DEFAULT_DISCOVERY_PREFIX
                ): valid_subscribe_topic,
                vol.Optional(CONF_QOS, default=DEFAULT_QOS): _VALID_QOS_SCHEMA,
            }
        ),
    },
    extra=vol.ALLOW_EXTRA,
)

# GLOBALS
_LOGGER = logging.getLogger(__name__)

TRUE = "true"
FALSE = "false"

# Global Helper Functions
def string_to_bool(val: str):
    return val == TRUE


def bool_to_string(val: bool):
    return TRUE if val else FALSE


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
    hass.data[DATA_HOMIE_CONFIG] = conf

    # there is no config entry yet
    if not hass.config_entries.async_entries(DOMAIN):
        # call the class ConfigFlow.async_step_import to create a config entry for yaml
        # ...and the async_setup_entry with the new created entry
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data={}
            )
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Setup platform from a ConfigEntry."""

    # get configuration.yaml (saved in async_setup)
    conf = hass.data.get(DATA_HOMIE_CONFIG)

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

    await async_setup_disabled(hass, hass.data.get(DATA_HOMIE_CONFIG), entry)

    from homeassistant.helpers import device_registry as dr

    device_registry = dr.async_get(hass)

    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "83459345346")},
        name="device name homie 2",
        manufacturer="manufacture home 2",
        model="model homie 2",
        sw_version="1.4",
    )

    return True


def _merge_config(entry, conf):
    """Merge configuration.yaml config with config entry."""
    return {**conf, **entry.data}


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
    # discovery_prefix = conf.get(CONF_DISCOVERY_PREFIX)
    discovery_prefix = "+"
    qos = conf.get(CONF_QOS)

    _LOGGER.debug("DEBUG discovery_prefix %s", discovery_prefix)

    # Destroy Homie
    # async def async_destroy(event):
    #     # TODO: unsub?
    #     pass
    # hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_destroy)

    # Sart
    async def async_start():
        await mqtt.async_subscribe(
            hass, f"{discovery_prefix}/+/$homie", async_discover_message_received, qos
        )

    async def async_discover_message_received(mqttmsg: ReceiveMessage):

        device_match = DISCOVER_DEVICE.match(mqttmsg.topic)

        if device_match and mqttmsg.payload in HOMIE_SUPPORTED_VERSION:

            device_base_topic = device_match.group("prefix_topic")
            device_id = device_match.group("device_id")

            if device_id not in _DEVICES:

                device = HomieDevice(
                    hass, device_base_topic, device_id, async_component_ready
                )

                _DEVICES[device_id] = device
                await device._async_setup(qos)

                _LOGGER.debug(
                    "async_discover_message_received %s : %s",
                    mqttmsg.topic,
                    mqttmsg.payload,
                )

    async def async_component_ready(component, delayed=False):
        if type(component) is HomieDevice:
            await async_setup_device(component)
        if type(component) is HomieNode:
            await async_setup_node(component)

    async def async_setup_device(device: HomieDevice):
        _LOGGER.debug("async_setup_device %s ", HomieDevice.name)
        pass

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

    stuff_lock = asyncio.Lock()

    await async_start()
    return True


# Types
class ChangeListener(object):
    def __init__(self):
        super().__init__()
        self._listeners = list()

    def __setattr__(self, name: str, value: str):
        super(ChangeListener, self).__setattr__(name, value)
        for action in self._listeners:
            action()

    def add_listener(self, action):
        self._listeners.append(action)


class HomieDevice(ChangeListener):
    # A definition of a Homie Device
    def __init__(
        self, hass: HomeAssistant, homie_base_topic: str, device_id: str, on_ready
    ):
        super().__init__()
        self._nodes = dict()
        self._homie_base_topic = homie_base_topic
        self._device_id = device_id
        self._base_topic = f"{homie_base_topic}/{device_id}"
        self._on_ready = on_ready
        self._topic_dict = TopicDict()
        self._sub_state = None
        self.hass = hass
        # self._is_setup = False

        # Device Attributes
        self._state = STATE_UNKNOWN
        self._homie_version = STATE_UNKNOWN
        self._name = STATE_UNKNOWN
        self._ip = STATE_UNKNOWN
        self._mac = STATE_UNKNOWN
        self._uptime = STATE_UNKNOWN
        self._signal = STATE_UNKNOWN
        self._stats_interval = STATE_UNKNOWN
        self._fw_name = STATE_UNKNOWN
        self._fw_version = STATE_UNKNOWN
        self._fw_checksum = STATE_UNKNOWN
        self._implementation = STATE_UNKNOWN

    async def _async_setup(self, qos: int):
        async def async_discover_message_received(
            topic: str, payload: str, msg_qos: int
        ):
            node_match = DISCOVER_NODES.match(topic)
            if node_match:
                node_base_topic = node_match.group("prefix_topic")
                node_id = node_match.group("node_id")
                if node_id not in self._nodes:
                    node = HomieNode(self, node_base_topic, node_id, self._on_ready)
                    self._nodes[node_id] = node
                    await node._async_setup(self.hass, qos, payload)

        await mqtt.async_subscribe(
            self.hass,
            f"{self._base_topic}/+/$properties",
            async_discover_message_received,
            qos,
        )
        """ await mqtt.async_subscribe(
            hass, f"{self._base_topic}/#", self._async_update, qos
        ) """

        # await mqtt.async_subscribe(
        #     hass, f"{self._base_topic}/+", self._async_update, qos
        # )

        # await mqtt.async_subscribe(
        #     hass, f"{self._base_topic}/$stats/#", self._async_update, qos
        # )

        # await mqtt.async_subscribe(
        #     hass, f"{self._base_topic}/$fw/#", self._async_update, qos
        # )

        # await mqtt.async_subscribe(
        #     hass, f"{self._base_topic}/$implementation/#", self._async_update, qos
        # )

        sub_topics = {
            "base": f"{self._base_topic}/+",
            "stats": f"{self._base_topic}/$stats/#",
            "fw": f"{self._base_topic}/$fw/#",
            "implementation": f"{self._base_topic}/$implementation/#",
        }

        sub_base = {
            "msg_callback": self._async_update,
            "qos": qos,
        }
        sub_topics = {
            name: {**sub_base, **{"topic": topic}}
            for (name, topic) in sub_topics.items()
        }

        self._sub_state = await subscription.async_subscribe_topics(
            self.hass, self._sub_state, sub_topics
        )

    async def _async_update(self, mqttmsg: ReceiveMessage):
        topic = mqttmsg.topic.replace(f"{self._base_topic}/", "")

        self._topic_dict.topic_set(topic, mqttmsg.payload)

        # Load Device Properties
        if topic == "$homie":
            self._homie_version = mqttmsg.payload
        elif topic == "$state":
            self._state = mqttmsg.payload
        elif topic == "$name":
            self._name = mqttmsg.payload
        elif topic == "$localip":
            self._ip = mqttmsg.payload
        elif topic == "$mac":
            self._mac = mqttmsg.payload

        # Load Device Stats Properties
        elif topic == "$stats/uptime":
            self._uptime = mqttmsg.payload
        elif topic == "$stats/signal":
            self._signal = mqttmsg.payload
        elif topic == "$stats/interval":
            self._stats_interval = mqttmsg.payload

        # Load Firmware Properties
        elif topic == "$fw/name":
            self._fw_name = mqttmsg.payload
        elif topic == "$fw/version":
            self._fw_version = mqttmsg.payload
        elif topic == "$fw/checksum":
            self._fw_checksum = mqttmsg.payload

        # Load Implementation Properties
        elif topic == "$implementation":
            self._implementation = mqttmsg.payload

        # Ready
        if topic == "$state" and self.online:
            await asyncio.sleep(10)
            await self._on_ready(self, delayed=True)

    async def unsubscribe_topics(self):
        self._sub_state = await subscription.async_unsubscribe_topics(
            self.hass, self._sub_state
        )

    @property
    def homie_base_topic(self):
        """Return the Base Topic of the device."""
        return self._homie_base_topic

    @property
    def device_id(self):
        """Return the Device ID of the device."""
        return self._device_id

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def homie_version(self):
        """Return the Homie Framework Version of the device."""
        return self._homie_version

    @property
    def online(self) -> bool:
        """Return true if the device is online."""
        return True if self._state == "ready" else False

    @property
    def state(self):
        return self._state

    @property
    def ip(self):
        """Return the IP of the device."""
        return self._ip

    @property
    def mac(self):
        """Return the MAC of the device."""
        return self._mac

    @property
    def uptime(self):
        """Return the Uptime of the device."""
        return self._uptime

    @property
    def signal(self):
        """Return the Signal of the device."""
        return self._signal

    @property
    def stats_interval(self):
        """Return the Stats Interval of the device."""
        return self._stats_interval

    @property
    def firmware_name(self):
        """Return the Firmware Name of the device."""
        return self._fw_name

    @property
    def firmware_version(self):
        """Return the Firmware Version of the device."""
        return self._fw_version

    @property
    def firmware_checksum(self):
        """Return the Firmware Checksum of the device."""
        return self._fw_checksum

    # @property
    # def is_setup(self):
    #     """Return True if the Device has been setup as a component"""
    #     return self._is_setup

    @property
    def nodes(self):
        """Return a Dict of Nodes for the device."""
        return self._nodes

    def node(self, node_id):
        """Return a specific Node for the device."""
        return self._nodes[node_name]


class HomieNode(ChangeListener):
    # A definition of a Homie Node
    def __init__(self, device: HomieDevice, base_topic: str, node_id: str, on_ready):
        super().__init__()
        self._device = device
        self._properties = dict()
        self._base_topic = base_topic
        self._node_id = node_id
        self._prefix_topic = f"{base_topic}/{node_id}"
        self._on_ready = on_ready
        self._is_setup = False

        self._type = STATE_UNKNOWN

    async def _async_setup(self, hass: HomeAssistant, qos: int, properties_str: str):
        for property_match in DISCOVER_PROPERTIES.finditer(properties_str):
            property_id = property_match.group("property_id")
            if property_id not in self._properties:
                property_settable = (
                    True if property_match.group("settable") is not None else False
                )
                property_range = (
                    (
                        int(property_match.group("range_start")),
                        int(property_match.group("range_end")),
                    )
                    if property_match.group("range_start") is not None
                    else ()
                )
                property = HomieProperty(
                    self,
                    self._prefix_topic,
                    property_id,
                    property_settable,
                    property_range,
                )
                self._properties[property_id] = property
                await property._async_setup(hass, qos)

        await mqtt.async_subscribe(
            hass, f"{self._prefix_topic}/#", self._async_update, qos
        )

    async def _async_update(self, mqttmsg: ReceiveMessage):
        topic = mqttmsg.topic.replace(self._prefix_topic, "")

        if topic == "/$type":
            self._type = mqttmsg.payload

        # Ready
        if topic == "/$type" and not self._is_setup:
            self._is_setup = True
            await self._on_ready(self)

    @property
    def base_topic(self):
        """Return the Base Topic of the node."""
        return self._base_topic

    @property
    def node_id(self):
        """Return the Node Id of the node."""
        return self._node_id

    @property
    def type(self):
        """Return the Type of the node."""
        return self._type

    @property
    def is_setup(self):
        """Return True if the Node has been setup as a component"""
        return self._is_setup

    @property
    def properties(self):
        """Return a Dict of properties for the node."""
        return self._properties

    def has_property(self, property_name: str):
        """Return a specific Property for the node."""
        return property_name in self._properties

    def get_property(self, property_name: str):
        """Return a specific Property for the node."""
        return self._properties[property_name]

    @property
    def device(self):
        """Return the Parent Device of the node."""
        return self._device


class HomieProperty(ChangeListener):
    # A definition of a Homie Property
    def __init__(
        self,
        node: HomieNode,
        base_topic: str,
        property_id: str,
        settable: bool,
        ranges: tuple,
    ):
        super().__init__()
        self._node = node
        self._base_topic = base_topic
        self._property_id = property_id
        self._settable = settable
        self._range = ranges
        self._prefix_topic = f"{base_topic}/{property_id}"

        self._state = STATE_UNKNOWN

    async def _async_setup(self, hass: HomeAssistant, qos: int):
        async def async_publish(topic: str, payload: str, retain=True):
            mqtt.async_publish(hass, topic, payload, qos, retain)

        self._async_publish = async_publish
        await mqtt.async_subscribe(
            hass, f"{self._prefix_topic}/#", self._async_update, qos
        )

    async def _async_update(self, mqttmsg: ReceiveMessage):
        topic = mqttmsg.topic.replace(self._prefix_topic, "")

        if topic == "":
            self._state = mqttmsg.payload
        elif topic == "/$settable":
            self._settable = mqttmsg.payload

    @property
    def property_id(self):
        """Return the Property Id of the Property."""
        return self._property_id

    @property
    def state(self):
        """Return the state of the Property."""
        return self._state

    async def async_set_state(self, value: str):
        """Set the state of the Property."""

        _LOGGER.debug(
            "async_set_state() %s %s %s",
            self.settable,
            f"{self._prefix_topic}/set",
            value,
        )

        # if self.settable:
        await self._async_publish(f"{self._prefix_topic}/set", value)

    @property
    def settable(self):
        """Return if the Property is settable."""
        return self._settable

    @property
    def node(self):
        """Return the Parent Node of the Property."""
        return self._node

    @property
    def name(self):
        """Return the Name of the Property."""
        return self._name

    @property
    def unit(self):
        """Return the Unit for the Property."""
        return self._unit

    @property
    def dataType(self):
        """Return the Data Type for the Property."""
        return self._datatype

    @property
    def format(self):
        """Return the Format for the Property."""
        return self._format


class TopicNode(dict):
    def __init__(self, value: Any = None, sub_topic: Dict[str, TopicNode] = {}):
        super().__init__(sub_topic)
        self._value = value

    def __str__(self):
        topic_child_str = ", ".join(
            "%s: %s" % (key, self[key].__str__()) for key in super().keys()
        )
        return "(%s, {%s})" % (self._value, topic_child_str)

    def __repr__(self):
        return self.__str__()

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, value):
        self._value = value


class TopicDict(dict):
    def __init__(self, include_topics: List = [], exclude_topics: List = []):
        super().__init__()
        self._listeners = list()
        self._include_topics = include_topics
        self._exclude_topics = exclude_topics

    @staticmethod
    def _topic_to_lst(topic_path: str) -> list:
        return topic_path.split("/")

    def add_include_topic(self, *regex_patterns: List[str]):
        for regex_pattern in regex_patterns:
            self._include_topics.append(re.compile(regex_pattern))

    def add_exclude_topic(self, *regex_patterns: List[str]):
        for regex_pattern in regex_patterns:
            self._exclude_topics.append(re.compile(regex_pattern))

    def add_listener(self, callback):
        self._listeners.append(callback)

    def __str__(self):
        return "{%s}" % ", ".join(
            "%s: %s" % (key, self[key].__str__()) for key in super().keys()
        )

    def __repr__(self):
        return self.__str__()

    def topic_get(self, topic_path: str, default=None):

        topic_node = self

        for topic_lvl in self._topic_to_lst(topic_path):

            if topic_lvl not in topic_node:
                return default

            topic_node = topic_node.get(topic_lvl)

        return topic_node

    def topic_set(self, topic_path: str, value):

        if self._include_topics and not any(
            regex_include.match(topic_path) for regex_include in self._include_topics
        ):
            return False

        if self._exclude_topics and any(
            regex_exclude.match(topic_path) for regex_exclude in self._exclude_topics
        ):
            return False

        topic_node = self

        for topic_lvl in self._topic_to_lst(topic_path):
            topic_node = topic_node.setdefault(topic_lvl, TopicNode())

        topic_node.value = value

        for callback in self._listeners:
            callback(topic_path, value)

    def topic_del(self, topic_path: str):

        topic_path_list = self._topic_to_lst(topic_path)

        topic_parent_node = self.topic_get(topic_path_list[:-1], False)

        if not topic_parent_node:
            return False

        return topic_parent_node.pop(topic_path_list[-1], False)

    def __getitem__(self, topic_path):
        return self.topic_get(topic_path)

    def __setitem__(self, topic_path, value):
        self.topic_set(topic_path, value)

    def __delitem__(self, topic_path):
        self.topic_del(topic_path)
