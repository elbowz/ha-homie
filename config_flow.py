"""Config flow for Homie integration."""
from __future__ import annotations

import logging
import voluptuous as vol

from typing import Any
from homeassistant.core import callback

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

import homeassistant.components.mqtt as mqtt

from homeassistant.helpers.typing import DiscoveryInfoType

from .const import (
    DOMAIN,
    CONF_BASE_TOPIC,
    DEFAULT_BASE_TOPIC,
    CONF_QOS,
    DEFAULT_QOS,
    CONF_DISCOVERY,
    DEFAULT_DISCOVERY,
    _VALID_QOS_SCHEMA,
)

_LOGGER = logging.getLogger(__name__)

# Cannot use the same (complex) schema used in __init__
# https://github.com/home-assistant/core/issues/32819
CONFIG_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_BASE_TOPIC, default=DEFAULT_BASE_TOPIC): cv.string,
        vol.Optional(CONF_QOS, default=DEFAULT_QOS): _VALID_QOS_SCHEMA,
        vol.Optional(CONF_DISCOVERY, default=DEFAULT_DISCOVERY): cv.boolean,
    }
)


class HomieConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BastarDog Test."""

    VERSION = 1

    async def async_step_import(self, user_input):
        """Import a config entry.

        Special type of import, we're not actually going to store any data.
        Instead, we're going to rely on the values that are in config file.
        """
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        # Create the config entry (a component async_setup_entry() call will be made)
        return self.async_create_entry(title="configuration.yaml", data={})

    async def async_step_mqtt(self, discovery_info: DiscoveryInfoType) -> FlowResult:
        """Handle a flow initialized by mqtt discovery ("mqtt" in manifest.json)."""
        # Check if there is something already configured or in progress
        if self._async_in_progress() or self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        # id == DOMAIN beacuse if ignored by the user the discover tile MUST not reappear
        # https://developers.home-assistant.io/docs/config_entries_config_flow_handler/#unique-ids
        await self.async_set_unique_id(DOMAIN)

        # "Invoking a discovery step should never result in a finished flow and a config entry. Always confirm with the user."
        # https://developers.home-assistant.io/docs/config_entries_config_flow_handler/#discovery-steps
        # Called on button "configure" on discovered tile
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                mqtt.valid_subscribe_topic(user_input.get(CONF_BASE_TOPIC))
                pass
            except vol.Invalid:
                errors["base"] = "invalid_base_topic"
            if not errors:
                return self.async_create_entry(title="Homie", data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=CONFIG_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        # ?? CALLED ON BUTTON "CONFIGURE"
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handles options flow for the component."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry
