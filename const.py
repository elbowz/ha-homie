"""Constants for the Homie component."""

from homeassistant.const import (
    CONF_INCLUDE,
    CONF_EXCLUDE,
    CONF_NAME,
    CONF_ICON,
    CONF_UNIQUE_ID,
    CONF_DEVICE_CLASS,
)
from homeassistant.components.mqtt import CONF_DISCOVERY, CONF_QOS, _VALID_QOS_SCHEMA
from .homie import TRUE, FALSE

DOMAIN = "homie"

# hass.data keys
DATA_HOMIE_CONFIG = f"{DOMAIN}-config"
DATA_KNOWN_DEVICES = f"{DOMAIN}-devices"

# configuration keys
CONF_BASE_TOPIC = "base_topic"
CONF_ENABLED_BY_DEFAULT = "enabled_by_default"
CONF_DEVICE = "device"
CONF_NODE = "node"
CONF_PROPERTY = "property"
CONF_PROPERTY_TOPIC = f"{CONF_PROPERTY}_topic"

# configuration default
DEFAULT_BASE_TOPIC = "+"
DEFAULT_QOS = 1
DEFAULT_DISCOVERY = True

# signals/events
HOMIE_DISCOVERY_NEW = f"{DOMAIN}_discovery_new_{{}}"
HOMIE_DISCOVERY_NEW_DEVICE = f"{DOMAIN}_discovery_new_{CONF_DEVICE}_{{}}"

# useful consts
HOMIE_SUPPORTED_VERSION = ["3.0.0", "3.0.1", "4.0.0"]
DISCOVERY_TOPIC = "{}/+/$homie"
DEVICE = CONF_DEVICE
NODE = CONF_NODE
PROPERTY = CONF_PROPERTY

from homeassistant.components.switch import DOMAIN as SWITCH
from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR
from homeassistant.components.sensor import DOMAIN as SENSOR
from homeassistant.components.number import DOMAIN as NUMBER

# supported platfroms
PLATFORMS = [SWITCH, BINARY_SENSOR, SENSOR, NUMBER]
