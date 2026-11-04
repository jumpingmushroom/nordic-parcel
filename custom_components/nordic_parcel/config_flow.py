"""Config flow for Nordic Parcel integration."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CarrierApiError
from .api.factory import create_client
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

_CREDENTIAL_FIELDS: dict[Carrier, tuple[str, ...]] = {
    Carrier.BRING: (CONF_API_UID, CONF_API_KEY),
    Carrier.POSTNORD: (CONF_API_KEY,),
    Carrier.HELTHJEM: (CONF_CLIENT_ID, CONF_CLIENT_SECRET),
}
# Non-secret fields shown pre-filled during reauthentication.
_PREFILLED_FIELDS = (CONF_API_UID, CONF_CLIENT_ID)
_DOCS_URLS: dict[Carrier, str] = {
    Carrier.BRING: "https://developer.bring.com/api/tracking/",
    Carrier.POSTNORD: "https://developer.postnord.com/",
    Carrier.HELTHJEM: "https://developer.helthjem.no/",
}


def _credentials_schema(carrier: Carrier, current: Mapping[str, Any] | None = None) -> vol.Schema:
    """Return the credentials form for a carrier, pre-filled from ``current`` on reauth."""
    return vol.Schema(
        {
            (
                vol.Required(key, default=current.get(key, ""))
                if current is not None and key in _PREFILLED_FIELDS
                else vol.Required(key)
            ): str
            for key in _CREDENTIAL_FIELDS[carrier]
        }
    )


def _unique_id(carrier: Carrier, credentials: Mapping[str, Any]) -> str:
    """Return the config entry unique ID for a set of credentials."""
    if carrier == Carrier.BRING:
        return f"bring_{credentials[CONF_API_UID]}"
    hashed = credentials[CONF_API_KEY if carrier == Carrier.POSTNORD else CONF_CLIENT_ID]
    return f"{carrier.value}_{hashlib.sha256(hashed.encode()).hexdigest()[:8]}"


def _title(carrier: Carrier, credentials: Mapping[str, Any]) -> str:
    """Return the config entry title for a set of credentials."""
    if carrier == Carrier.BRING:
        return f"Bring ({credentials[CONF_API_UID]})"
    return "Postnord" if carrier == Carrier.POSTNORD else "Helthjem"


class NordicParcelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Nordic Parcel."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the carrier selection step."""
        if user_input is not None:
            return await self._async_step_credentials(Carrier(user_input[CONF_CARRIER]))

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

    async def async_step_bring(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle Bring credentials."""
        return await self._async_step_credentials(Carrier.BRING, user_input)

    async def async_step_postnord(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Postnord credentials."""
        return await self._async_step_credentials(Carrier.POSTNORD, user_input)

    async def async_step_helthjem(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Helthjem credentials."""
        return await self._async_step_credentials(Carrier.HELTHJEM, user_input)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Handle reauthentication."""
        return await self._async_step_credentials(
            Carrier(entry_data[CONF_CARRIER]), reauth_entry=self._get_reauth_entry()
        )

    async def async_step_reauth_bring(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Bring reauthentication."""
        return await self._async_step_credentials(
            Carrier.BRING, user_input, self._get_reauth_entry()
        )

    async def async_step_reauth_postnord(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Postnord reauthentication."""
        return await self._async_step_credentials(
            Carrier.POSTNORD, user_input, self._get_reauth_entry()
        )

    async def async_step_reauth_helthjem(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Helthjem reauthentication."""
        return await self._async_step_credentials(
            Carrier.HELTHJEM, user_input, self._get_reauth_entry()
        )

    async def _async_step_credentials(
        self,
        carrier: Carrier,
        user_input: dict[str, Any] | None = None,
        reauth_entry: ConfigEntry | None = None,
    ) -> ConfigFlowResult:
        """Show a carrier's credentials form, or validate and save what was submitted."""
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = create_client(session, {CONF_CARRIER: carrier, **user_input})
            try:
                if await client.authenticate():
                    return await self._async_save_credentials(carrier, user_input, reauth_entry)
                errors["base"] = "invalid_auth"
            except CarrierApiError:
                errors["base"] = "cannot_connect"

        if reauth_entry is not None:
            return self.async_show_form(
                step_id=f"reauth_{carrier.value}",
                data_schema=_credentials_schema(carrier, reauth_entry.data),
                errors=errors,
            )
        return self.async_show_form(
            step_id=carrier.value,
            data_schema=_credentials_schema(carrier),
            errors=errors,
            description_placeholders={"docs_url": _DOCS_URLS[carrier]},
        )

    async def _async_save_credentials(
        self,
        carrier: Carrier,
        credentials: dict[str, Any],
        reauth_entry: ConfigEntry | None,
    ) -> ConfigFlowResult:
        """Create the entry, or update the one being reauthenticated."""
        unique_id = _unique_id(carrier, credentials)
        existing = await self.async_set_unique_id(unique_id)

        if reauth_entry is None:
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=_title(carrier, credentials),
                data={CONF_CARRIER: carrier, **credentials},
            )

        if existing is not None and existing.entry_id != reauth_entry.entry_id:
            return self.async_abort(reason="already_configured")
        # Leave the title alone unless the account changed; the user may have renamed it.
        title = (
            reauth_entry.title
            if unique_id == reauth_entry.unique_id
            else _title(carrier, credentials)
        )
        return self.async_update_reload_and_abort(
            reauth_entry,
            unique_id=unique_id,
            title=title,
            data={**reauth_entry.data, **credentials},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> NordicParcelOptionsFlow:
        """Return the options flow handler."""
        return NordicParcelOptionsFlow()


class NordicParcelOptionsFlow(OptionsFlow):
    """Handle options for Nordic Parcel."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage integration options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=60, max=86400)),
                    vol.Optional(
                        CONF_CLEANUP_DAYS,
                        default=self.config_entry.options.get(
                            CONF_CLEANUP_DAYS, DEFAULT_CLEANUP_DAYS
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=30)),
                }
            ),
        )
