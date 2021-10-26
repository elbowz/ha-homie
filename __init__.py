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
from voluptuous.validators import Boolean

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

            device_prefix_topic = device_match.group("prefix_topic")
            device_id = device_match.group("device_id")

            if device_id not in _DEVICES:

                device = HomieDevice(
                    hass,
                    device_prefix_topic + "/" + device_id,
                    qos,
                    async_component_ready,
                )

                _DEVICES[device_id] = device
                await device.async_setup()

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
        _LOGGER.debug("async_setup_device %s ", device.device_id)
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
# TODO: DELETE
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


def get_topic_head(topic: str) -> Union[tuple[str, str], bool]:
    topic = topic.strip("/")
    last_slash_index = topic.rfind("/")

    if last_slash_index == -1:
        return False

    return topic[last_slash_index + 1 :], topic


class HomieDevice:
    # A definition of a Homie Device
    def __init__(
        self, hass: HomeAssistant, base_topic: str, qos: int, on_ready: Callable
    ):
        self.device_id, self.base_topic = get_topic_head(base_topic)

        if self.device_id is False:
            raise ValueError(
                "Provide the full device topic (eg. 'homie/device-id'): %s"
                % self.base_topic
            )

        self.nodes = dict()
        self.topic_dict = TopicDict()
        self.topic_dict.add_listener(self._update_topic_dict)

        self._hass = hass
        self._qos = qos
        self._sub_state = None
        self._on_ready = on_ready

    async def async_setup(self):
        # async def _async_update_nodes(mqttmsg: ReceiveMessage):
        #     # TODO: add nodes restiction list
        #     node_match = DISCOVER_NODES.match(mqttmsg.topic)

        #     if node_match:
        #         node_id = node_match.group("node_id")
        #         node_prefix_topic = node_match.group("prefix_topic")

        #         if node_id not in self.nodes:
        #             node = HomieNode(self, node_prefix_topic + "/" + node_id)
        #             self.nodes[node_id] = node
        #             await node.async_setup()

        """await mqtt.async_subscribe(
            self._hass,
            f"{self.base_topic}/+/$properties",
            _async_update_nodes,
            qos,
        )"""

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

    async def _async_update(self, mqttmsg: ReceiveMessage):
        # TODO: try without "/"
        topic = mqttmsg.topic.replace(f"{self.base_topic}/", "")
        self.topic_dict.topic_set(topic, mqttmsg.payload)

    async def unsubscribe_topics(self):
        self._sub_state = await subscription.async_unsubscribe_topics(
            self._hass, self._sub_state
        )

    def _update_topic_dict(self, topic, value):
        # Call the async version
        self._hass.loop.create_task(self._async_update_topic_dict(topic, value))

    async def _async_update_topic_dict(self, topic, value):
        if topic == "$nodes":
            for node_id in value.split(","):
                # TODO: add nodes restiction list
                if node_id not in self.nodes:
                    node = HomieNode(self, self.base_topic + "/" + node_id)
                    self.nodes[node_id] = node
                    await node.async_setup()

        # Ready
        if topic == "$state" and value == "ready":
            await asyncio.sleep(10)
            await self._on_ready(self, delayed=True)

    def node(self, node_id: str):
        """Return a specific Node for the device."""
        return self.nodes[node_id]

    def __getitem__(self, node_id: str):
        return self.node(node_id)

    def __del__(self):
        self.unsubscribe_topics()


class HomieNode:
    # A definition of a Homie Node
    def __init__(self, device: HomieDevice, base_topic: str):
        self.node_id, self.base_topic = get_topic_head(base_topic)

        if self.node_id is False:
            raise ValueError(
                "Provide the full Node topic (eg. 'homie/device-id/node-id'): %s"
                % self.base_topic
            )

        self.device = device
        self.properties = dict()

        self.device.topic_dict[self.node_id] = TopicDict()
        self.topic_dict = self.device.topic_dict[self.node_id]
        # self.topic_dict.add_include_topic("^\$")
        self.topic_dict.add_listener(self._update_topic_dict)

        self._hass = device._hass
        self._qos = device._qos

    async def async_setup(self):
        self.unsubscribe_topics = await mqtt.async_subscribe(
            self._hass, f"{self.base_topic}/+", self._async_update, self._qos
        )

    async def _async_update(self, mqttmsg: ReceiveMessage):
        # TODO: try without "/"
        topic = mqttmsg.topic.replace(f"{self.base_topic}/", "")
        self.topic_dict[topic] = mqttmsg.payload

    def _update_topic_dict(self, topic, value):
        # Call the async version
        self._hass.loop.create_task(self._async_update_topic_dict(topic, value))

    async def _async_update_topic_dict(self, topic, value):
        # notes: can be removed this method and call node.async_setup() by create_task
        if topic == "$properties":
            for property_id in value.split(","):
                if property_id not in self.properties:
                    # TODO: add properties restiction list
                    node = HomieProperty(self, self.base_topic + "/" + property_id)
                    self.properties[property_id] = node
                    await node.async_setup()

    def has_property(self, property_id: str):
        """Return a specific Property for the node."""
        return property_id in self.properties

    def property(self, property_id: str):
        """Return a specific Property for the Node."""
        return self.properties[property_id]

    def __getitem__(self, property_id: str):
        return self.property(property_id)

    def __del__(self):
        self.unsubscribe_topics()


class HomieProperty:
    # A definition of a Homie Property
    def __init__(self, node: HomieNode, base_topic: str):
        self.property_id, self.base_topic = get_topic_head(base_topic)

        if self.property_id is False:
            raise ValueError(
                "Provide the full Property topic (eg. 'homie/device-id/node-id/property-id'): %s"
                % self.base_topic
            )

        self.node = node

        self.node.topic_dict[self.property_id] = TopicDict()
        self.topic_dict = self.node.topic_dict[self.property_id]
        self.topic_dict.add_listener(self._update_topic_dict)

        self._hass = node._hass
        self._qos = node._qos

    async def async_setup(self):
        self.unsubscribe_topics = await mqtt.async_subscribe(
            self._hass, f"{self.base_topic}/#", self._async_update, self._qos
        )

    async def _async_update(self, mqttmsg: ReceiveMessage):
        topic = mqttmsg.topic.replace(f"{self.base_topic}", "")

        if topic == "":
            self.topic_dict.value = mqttmsg.payload
        else:
            self.topic_dict[topic] = mqttmsg.payload

    def _update_topic_dict(self, topic, value):
        self._hass.loop.create_task(self._async_update_topic_dict(topic, value))

    async def _async_update_topic_dict(self, topic, value):
        pass

    @callback
    async def async_set(self, value: str):
        """Set the state of the Property."""
        if self.settable:
            mqtt.async_publish(
                self._hass, f"{self._prefix_topic}/set", value, self._qos, retain=True
            )

    # @property
    # def value(self):
    #     return self.topic_dict[]

    # @value.setter
    # def value(self, value):
    #     self._value = value

    @property
    def settable(self):
        """Return if the Property is settable."""
        return string_to_bool(self.topic_dict["$settable"])

    def __del__(self):
        self.unsubscribe_topics()


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


from typing import Callable

TopicDictCallbackType = Callable[[str, Any], bool]


class TopicDict(TopicNode):
    def __init__(self, include_topics: List = [], exclude_topics: List = []):
        super().__init__()
        self._listeners = list()
        self._include_topics = list()
        self._exclude_topics = list()
        self.add_include_topic(*include_topics)
        self.add_exclude_topic(*exclude_topics)

    @staticmethod
    def _topic_to_lst(topic_path: str) -> list:
        return topic_path.strip("/").split("/")

    def add_include_topic(self, *regex_patterns: List[str]):
        for regex_pattern in regex_patterns:
            self._include_topics.append(re.compile(regex_pattern))

    def add_exclude_topic(self, *regex_patterns: List[str]):
        for regex_pattern in regex_patterns:
            self._exclude_topics.append(re.compile(regex_pattern))

    def add_listener(self, callback: TopicDictCallbackType):
        self._listeners.append(callback)

    def topic_get(self, topic_path: Union[str, list], default=None):

        if not isinstance(topic_path, list):
            topic_path = self._topic_to_lst(topic_path)

        topic_node = self

        for topic_lvl in topic_path:

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

        if self._listeners and any(
            callback(topic_path, value) for callback in self._listeners
        ):
            return False

        topic_node = self

        for topic_lvl in self._topic_to_lst(topic_path):
            topic_node = topic_node.setdefault(topic_lvl, TopicDict())

        if isinstance(value, TopicDict):
            topic_parent_node, topic_label = self._get_parent(topic_path)
            super(TopicNode, topic_parent_node).__setitem__(topic_label, value)

        else:
            topic_node.value = value

    def _get_parent(self, topic_path: str):

        topic_path_list = self._topic_to_lst(topic_path)
        return self.topic_get(topic_path_list[:-1], False), topic_path_list[-1]

    def topic_del(self, topic_path: str):

        topic_parent_node, topic_label = self._get_parent(topic_path)

        if not topic_parent_node:
            return False

        return topic_parent_node.pop(topic_label, False)

    def __getitem__(self, topic_path):
        return self.topic_get(topic_path)

    def __setitem__(self, topic_path, value):
        self.topic_set(topic_path, value)

    def __delitem__(self, topic_path):
        self.topic_del(topic_path)
