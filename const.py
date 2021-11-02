"""Constants for the Homie component."""

from homeassistant.components.mqtt import CONF_DISCOVERY, CONF_QOS, _VALID_QOS_SCHEMA

DOMAIN = "homie"

# hass.data keys
HOMIE_CONFIG = f"{DOMAIN}-config"
KNOWN_DEVICES = f"{DOMAIN}-devices"

# configuration keys
CONF_BASE_TOPIC = "base_topic"

# configuration default
DEFAULT_BASE_TOPIC = "+"
DEFAULT_QOS = 1
DEFAULT_DISCOVERY = True

# signals/events
HOMIE_DISCOVERY_NEW = "homie_discovery_new_{}"

# useful consts
HOMIE_SUPPORTED_VERSION = ["3.0.0", "3.0.1", "4.0.0"]
DISCOVERY_TOPIC = "{}/+/$homie"
TRUE = "true"
FALSE = "false"

from homeassistant.components.switch import DOMAIN as SWITCH

# supported platfroms
PLATFORMS = [SWITCH]
