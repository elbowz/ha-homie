"""Config flow for BastarDog Test integration."""
from __future__ import annotations

import logging
from typing import Any
from homeassistant.core import callback

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

from homeassistant.helpers.typing import DiscoveryInfoType

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# TODO adjust the data schema to the data that you need
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional("host", default="ciao"): cv.string,
        vol.Optional("username", default="ciao"): cv.string,
        vol.Optional("password", default="ciao"): cv.string,
    }
)


class PlaceholderHub:
    """Placeholder class to make tests pass.

    TODO Remove this placeholder class and replace with things from your PyPI package.
    """

    def __init__(self, host: str) -> None:
        """Initialize."""
        self.host = host

    async def authenticate(self, username: str, password: str) -> bool:
        """Test if we can authenticate with the host."""
        return True


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    # TODO validate the data can be used to set up a connection.

    # If your PyPI package is not built with async, pass your methods
    # to the executor:
    # await hass.async_add_executor_job(
    #     your_validate_func, data["username"], data["password"]
    # )

    hub = PlaceholderHub(data["host"])

    if not await hub.authenticate(data["username"], data["password"]):
        raise InvalidAuth

    # If you cannot connect:
    # throw CannotConnect
    # If the authentication is wrong:
    # InvalidAuth

    # Return info that you want to store in the config entry.
    return {"title": "Name of the device"}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BastarDog Test."""

    VERSION = 1

    async def async_step_import(self, user_input):
        """Import a config entry.

        Special type of import, we're not actually going to store any data.
        Instead, we're going to rely on the values that are in config file.
        """
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        return self.async_create_entry(title="configuration.yaml", data={})

    async def async_step_mqtt(self, discovery_info: DiscoveryInfoType) -> FlowResult:
        """Handle a flow initialized by MQTT discovery."""
        ciao = self._async_in_progress()
        ciao = self._async_current_entries()
        # ?? check if there is something already configured or in progress
        # if self._async_in_progress() or self._async_current_entries():
        #     return self.async_abort(reason="single_instance_allowed")

        # id == DOMAIN beacuse if ignored by the user the discover tile MUST not reappear
        # https://developers.home-assistant.io/docs/config_entries_config_flow_handler/#unique-ids
        await self.async_set_unique_id(DOMAIN)

        # # Validate the message, abort if it fails
        # if not discovery_info["topic"].endswith("/config"):
        #     # Not a Tasmota discovery message
        #     return self.async_abort(reason="invalid_discovery_info")
        # if not discovery_info["payload"]:
        #     # Empty payload, the Tasmota is not configured for native discovery
        #     return self.async_abort(reason="invalid_discovery_info")

        # # "tasmota/discovery/#" is hardcoded in Tasmota's manifest
        # assert discovery_info["subscribed_topic"] == "tasmota/discovery/#"
        # self._prefix = "tasmota/discovery"

        # "Invoking a discovery step should never result in a finished flow and a config entry. Always confirm with the user."
        # https://developers.home-assistant.io/docs/config_entries_config_flow_handler/#discovery-steps
        return await self.async_step_confirm()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}

        try:
            info = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    # CALLED ON BUTTON "CONFIGURE" WHEN DISCOVERED TILE (because called by async_step_mqtt)
    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm the setup."""

        # data = {CONF_DISCOVERY_PREFIX: self._prefix}

        # if user_input is not None:
        #     return self.async_create_entry(title="Tasmota", data=data)

        # ?? display the tile
        # return self.async_show_form(step_id="confirm")
        errors = {}
        fields = {}
        fields[vol.Optional("label", default="my default")] = str

        return self.async_show_form(
            step_id="confirm", data_schema=vol.Schema(fields), errors=errors
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


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
