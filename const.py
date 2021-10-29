"""Constants for the Homie component."""

DOMAIN = "homie"

# hass.data keys
HOMIE_CONFIG = f"{DOMAIN}-config"
KNOWN_DEVICES = f"{DOMAIN}-devices"

# signals/events
HOMIE_DISCOVERY_NEW = "homie_discovery_new_{}"

# useful consts
TRUE = "true"
FALSE = "false"

from homeassistant.components.switch import DOMAIN as SWITCH

PLATFORMS = [SWITCH]
