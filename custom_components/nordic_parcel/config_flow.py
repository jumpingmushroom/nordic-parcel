"""Config flow for Nordic Parcel integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CarrierAuthError, CarrierApiError
from .api.bring import BringApiClient
from .api.helthjem import HelthjemApiClient
from .api.postnord import PostnordApiClient
from .const import (
    CONF_API_KEY,
    CONF_API_UID,
    CONF_CARRIER,
    CONF_CLEANUP_DAYS,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_SCAN_INTERVAL,
    DEFAULT_CLEANUP_DAYS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    Carrier,
)

_LOGGER = logging.getLogger(__name__)


class NordicParcelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Nordic Parcel."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the carrier selection step."""
        if user_input is not None:
            self._carrier = Carrier(user_input[CONF_CARRIER])
            if self._carrier == Carrier.BRING:
                return await self.async_step_bring()
            if self._carrier == Carrier.POSTNORD:
                return await self.async_step_postnord()
            return await self.async_step_helthjem()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CARRIER): vol.In(
                        {
                            Carrier.BRING: "Bring (Posten Norge)",
                            Carrier.POSTNORD: "Postnord",
                            Carrier.HELTHJEM: "Helthjem",
                        }
                    ),
                }
            ),
        )

    async def async_step_bring(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle Bring credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = BringApiClient(
                session, user_input[CONF_API_UID], user_input[CONF_API_KEY]
            )
            try:
                if await client.authenticate():
                    await self.async_set_unique_id(
                        f"bring_{user_input[CONF_API_UID]}"
                    )
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"Bring ({user_input[CONF_API_UID]})",
                        data={
                            CONF_CARRIER: Carrier.BRING,
                            CONF_API_UID: user_input[CONF_API_UID],
                            CONF_API_KEY: user_input[CONF_API_KEY],
                        },
                    )
                errors["base"] = "invalid_auth"
            except CarrierApiError:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="bring",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_UID): str,
                    vol.Required(CONF_API_KEY): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "docs_url": "https://developer.bring.com/api/tracking/"
            },
        )

    async def async_step_postnord(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle Postnord credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = PostnordApiClient(session, user_input[CONF_API_KEY])
            try:
                if await client.authenticate():
                    await self.async_set_unique_id(
                        f"postnord_{user_input[CONF_API_KEY][:8]}"
                    )
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title="Postnord",
                        data={
                            CONF_CARRIER: Carrier.POSTNORD,
                            CONF_API_KEY: user_input[CONF_API_KEY],
                        },
                    )
                errors["base"] = "invalid_auth"
            except CarrierApiError:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="postnord",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "docs_url": "https://developer.postnord.com/"
            },
        )

    async def async_step_helthjem(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle Helthjem credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = HelthjemApiClient(
                session, user_input[CONF_CLIENT_ID], user_input[CONF_CLIENT_SECRET]
            )
            try:
                if await client.authenticate():
                    await self.async_set_unique_id(
                        f"helthjem_{user_input[CONF_CLIENT_ID][:8]}"
                    )
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title="Helthjem",
                        data={
                            CONF_CARRIER: Carrier.HELTHJEM,
                            CONF_CLIENT_ID: user_input[CONF_CLIENT_ID],
                            CONF_CLIENT_SECRET: user_input[CONF_CLIENT_SECRET],
                        },
                    )
                errors["base"] = "invalid_auth"
            except CarrierApiError:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="helthjem",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CLIENT_ID): str,
                    vol.Required(CONF_CLIENT_SECRET): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "docs_url": "https://developer.helthjem.no/"
            },
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Handle reauthentication."""
        carrier = Carrier(entry_data[CONF_CARRIER])
        if carrier == Carrier.BRING:
            return await self.async_step_bring()
        if carrier == Carrier.POSTNORD:
            return await self.async_step_postnord()
        return await self.async_step_helthjem()

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> NordicParcelOptionsFlow:
        """Return the options flow handler."""
        return NordicParcelOptionsFlow(config_entry)


class NordicParcelOptionsFlow(OptionsFlow):
    """Handle options for Nordic Parcel."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage integration options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=self._config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=60, max=86400)),
                    vol.Optional(
                        CONF_CLEANUP_DAYS,
                        default=self._config_entry.options.get(
                            CONF_CLEANUP_DAYS, DEFAULT_CLEANUP_DAYS
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=30)),
                }
            ),
        )
