# This file Replaces the file homeassistant/components/mqtt/discovery.py
#
# Example of a homie properties, node and device layout that this very hacked together version works for.
#[homeassistant.components.mqtt.discovery] Online Match[templux1]: true
#[homeassistant.components.mqtt.discovery] Device:[templux1] - Node:[temperature] - Prop:[unit] - Value:[c]
#[homeassistant.components.mqtt.discovery] Device:[templux1] - Node:[temperature] - Prop:[temperature] - Value:[27.84]
#[homeassistant.components.mqtt.discovery] Found new component: sensor templux1_temperature
#
# devices/templux1/$online true
# devices/templux1/temperature/$properties unit,temperature
# devices/templux1/temperature/unit c
# devices/templux1/temperature/temperature 27.84


import asyncio
import json
import logging
import re

import homeassistant.components.mqtt as mqtt
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.const import (
    CONF_FORCE_UPDATE, CONF_NAME, CONF_VALUE_TEMPLATE, STATE_UNKNOWN,
    CONF_UNIT_OF_MEASUREMENT, CONF_PLATFORM)
from homeassistant.components.mqtt import (
    CONF_AVAILABILITY_TOPIC, CONF_STATE_TOPIC, CONF_PAYLOAD_AVAILABLE,
    CONF_PAYLOAD_NOT_AVAILABLE, CONF_QOS)

_LOGGER = logging.getLogger(__name__)

messages = {}
nodes = {}

TOPIC_NODES = re.compile(r'(?P<prefix_topic>[$\w]+[-\w]*\w)/(?P<device>[$\w]+[-\w]*\w)/\$nodes')
TOPIC_ONLINE = re.compile(r'(?P<prefix_topic>[$\w]+[-\w]*\w)/(?P<device>[$\w]+[-\w]*\w)/\$online')
TOPIC_NODE_PROPERTIES = re.compile(r'(?P<prefix_topic>[$\w]+[-\w]*\w)/(?P<device>[$\w]+[-\w]*\w)/(?P<node>[$\w]+[-\w]*\w)/\$properties')

STATE_ONLINE = 'true'
ALREADY_DISCOVERED = 'mqtt_discovered_components'


@asyncio.coroutine
def async_start(hass, discovery_topic, hass_config):
    """Initialize of MQTT Discovery."""
    # pylint: disable=unused-variable
    @asyncio.coroutine
    def async_device_message_received(topic, payload, qos):
        """Process the received message."""
        _LOGGER.info("mqdiscover | [%s]:[%s]:[%s]", qos, topic, payload)
        
        # List of all topics published on MQTT since HA was started
        messages[topic] = payload
        
        # Check if the topic is a list of nodes
        match_nodes = TOPIC_NODES.match(topic)
        if match_nodes:
            arr = payload.split(",")
            nodelist = {}
            for a in arr:
                b = a.split(':')
                nodelist[b[0]] = b[1]
            device = match_nodes.group('device')
            nodes[device] = nodelist
            for key, val in nodes.items():
                for key2, val2 in val.items():
                    _LOGGER.warning("Device:[%s] - Node:[%s] - Type:[%s]", key, key2, val2)
        
        # Check if topic is $online topic
        match_online = TOPIC_ONLINE.match(topic)
        if match_online:
            _LOGGER.warning("Online Match[%s]: %s", match_online.group('device'), payload)
            if payload.lower() == STATE_ONLINE:
                device = match_online.group('device')
                base_topic = match_online.group('prefix_topic')
                
                for m_key in list(messages):
                    match_node_prop = TOPIC_NODE_PROPERTIES.match(m_key)
                    if match_node_prop:
                        if match_node_prop.group('device') == device:
                            node = match_node_prop.group('node')
                            config = {}
                            for prop in messages[m_key].split(','):
                                _LOGGER.warning("Device:[%s] - Node:[%s] - Prop:[%s] - Value:[%s]", device, node, prop, messages['{}/{}/{}/{}'.format(base_topic, device, node, prop)])
                                if prop == 'unit':
                                    config[CONF_UNIT_OF_MEASUREMENT] = messages['{}/{}/{}/{}'.format(base_topic, device, node, prop)]
                                else:
                                    config[CONF_STATE_TOPIC] = '{}/{}/{}/{}'.format(base_topic, device, node, prop)
                                    config[CONF_NAME] = messages['{}/{}/$name'.format(base_topic,device)] + ' ' + prop
                            platform = 'mqtt'
                            component = 'sensor'
                            config[CONF_PLATFORM] = platform
                            if ALREADY_DISCOVERED not in hass.data:
                                hass.data[ALREADY_DISCOVERED] = set()
                            
                            discovery_id = '_'.join((device, node))
                            discovery_hash = (component, discovery_id)
                            if discovery_hash in hass.data[ALREADY_DISCOVERED]:
                                _LOGGER.info("Component has already been discovered: %s %s",
                                             component, discovery_id)
                                return

                            hass.data[ALREADY_DISCOVERED].add(discovery_hash)

                            _LOGGER.info("Found new component: %s %s", component, discovery_id)

                            yield from async_load_platform(
                                hass, component, platform, config, hass_config)    
                                
                                

        return

    # Listen for all MQTT messages on base topic
    yield from mqtt.async_subscribe(
        hass, discovery_topic + '/#', async_device_message_received, 0)

    return True
