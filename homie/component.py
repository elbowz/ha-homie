from __future__ import annotations

import re
import asyncio
from abc import abstractmethod
from typing import Any, Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.components import mqtt
from homeassistant.components.mqtt import subscription

from . import FALSE
from .topic_dict import Observable, TopicDict
from .utils import str2bool


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
        self.topic_dict.subscribe(self._async_update_topic_dict)

        self._hass = hass
        self._qos = qos

        self._asyncio_event = dict()

        if async_on_change:
            self.subscribe(async_on_change)

    async def _async_update(self, mqttmsg: mqtt.models.ReceiveMessage):
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

    # def _update_topic_dict(self, topic, value):

    #     # _LOGGER.debug(
    #     #     "%s._update_topic_dict %s -> %s",
    #     #     self.__class__.__name__,
    #     #     topic,
    #     #     value,
    #     # )

    #     # Call the async version
    #     self._hass.loop.create_task(self._async_update_topic_dict(topic, value))
    #     # Call the subscribed functions (Observable)
    #     self._call_subscribers(self, topic, value)

    @abstractmethod
    async def _async_update_topic_dict(self, topic, value):
        self._call_subscribers(self, topic, value)
        # raise NotImplementedError()

    def _event_fire(self, name):
        self._asyncio_event.setdefault(name, asyncio.Event()).set()

    async def _event_wait(self, name, timeout=10):
        event = self._asyncio_event.setdefault(name, asyncio.Event())

        try:
            await asyncio.wait_for(event.wait(), timeout=10)
        except asyncio.TimeoutError:
            return False

        return True

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
        await super()._async_update_topic_dict(topic, value)

        if topic == "$nodes":
            for node_id in value.split(","):
                # TODO: add nodes restiction list
                if node_id not in self.nodes:
                    node = HomieNode(self, self.base_topic + "/" + node_id)
                    self.nodes[node_id] = node
                    await node.async_setup()

            self._event_fire("nodes-init")

    def has_node(self, node_id: str):
        """Check presence of Node in the device."""
        return node_id in self.nodes

    async def async_has_node(self, node_id: str):
        """Check presence of Node in the device."""
        await self._event_wait("nodes-init")
        return self.has_node(node_id)

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
        await super()._async_update_topic_dict(topic, value)

        # notes: can be removed this method and call node.async_setup() by create_task
        if topic == "$properties":
            for property_id in value.split(","):
                if property_id not in self.properties:
                    # TODO: add properties restiction list
                    property = HomieProperty(self, self.base_topic + "/" + property_id)
                    self.properties[property_id] = property
                    await property.async_setup()

            self._event_fire("properties-init")

    def _call_subscribers(self, *attrs, **kwargs):
        super()._call_subscribers(*attrs, **kwargs)
        self.device._call_subscribers(*attrs, **kwargs)

    def has_property(self, property_id: str):
        """Return a specific Property for the node."""
        return property_id in self.properties

    async def async_has_property(self, property_id: str):
        """Check presence of Node in the device."""
        await self._event_wait("properties-init")
        return self.has_property(property_id)

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

    def _call_subscribers(self, *attrs, **kwargs):
        super()._call_subscribers(*attrs, **kwargs)
        self.node._call_subscribers(*attrs, **kwargs)

    # async def _async_update_topic_dict(self, topic, value):
    #     pass

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
        return self.topic_dict.get("$datatype")
