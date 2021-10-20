# IMPORT
import asyncio
import logging

from homeassistant.const import (STATE_UNKNOWN)
from homeassistant.helpers.entity import (Entity)
from custom_components.homie import (KEY_HOMIE_ALREADY_DISCOVERED, KEY_HOMIE_ENTITY_NAME, HomieNode)

# TYPINGS
from homeassistant.helpers.typing import (HomeAssistantType, ConfigType)

# CONSTANTS
_LOGGER = logging.getLogger(__name__)
VALUE_PROP = 'value'

@asyncio.coroutine
def async_setup_platform(hass: HomeAssistantType, config: ConfigType, async_add_entities, discovery_info=None):
    """Set up the Homie sensor."""
    entity_name = discovery_info[KEY_HOMIE_ENTITY_NAME]
    homie_sensor_node = hass.data[KEY_HOMIE_ALREADY_DISCOVERED][entity_name]
    if homie_sensor_node is None: 
        raise ValueError("Homie Sensor failed to recive a Homie Node to bind too")
    if not homie_sensor_node.has_property(VALUE_PROP): 
        raise Exception(f"Homie Sensor Node doesn't have a {VALUE_PROP} property")
    
    async_add_entities([HomieSensor(entity_name, homie_sensor_node)])


# TODO: add expiry of state
class HomieSensor(Entity):
    """Implementation of a Homie Sensor."""

    def __init__(self, entity_name: str, homie_sensor_node: HomieNode):
        """Initialize Homie Sensor."""
        self._name = entity_name
        self._node = homie_sensor_node
        self._node.get_property(VALUE_PROP).add_listener(self._on_change)

    def _on_change(self):
        self.async_schedule_update_ha_state()

    @property
    def name(self):
        """Return the name of the Homie Sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the Homie Sensor."""
        return self._node.get_property(VALUE_PROP).state

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._node.get_property('_unit').state

    @property
    def should_poll(self):
        return False
