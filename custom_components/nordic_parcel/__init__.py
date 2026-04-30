"""Nordic Parcel — Track parcels from Bring, Postnord, and Helthjem."""

from __future__ import annotations

import logging
from datetime import timedelta

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.bring import BringApiClient
from .api.helthjem import HelthjemApiClient
from .api.postnord import PostnordApiClient
from .const import (
    CONF_API_KEY,
    CONF_API_UID,
    CONF_CARRIER,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    Carrier,
)
from .coordinator import NordicParcelCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

SERVICE_ADD_TRACKING = "add_tracking"
SERVICE_REMOVE_TRACKING = "remove_tracking"

# cv.string coerces ints to str — HA's service-data template renderer parses
# pure-digit strings into int via literal_eval, which a strict `str` type rejects.
SERVICE_ADD_SCHEMA = vol.Schema(
    {
        vol.Required("tracking_id"): vol.All(cv.string, vol.Strip, vol.Length(min=1)),
        vol.Optional("carrier"): vol.In([Carrier.BRING, Carrier.POSTNORD, Carrier.HELTHJEM]),
    }
)

SERVICE_REMOVE_SCHEMA = vol.Schema(
    {
        vol.Required("tracking_id"): vol.All(cv.string, vol.Strip, vol.Length(min=1)),
    }
)


def _create_client(
    hass: HomeAssistant, entry: ConfigEntry
) -> BringApiClient | PostnordApiClient | HelthjemApiClient:
    """Create the appropriate API client for a config entry."""
    session = async_get_clientsession(hass)
    carrier = Carrier(entry.data[CONF_CARRIER])

    if carrier == Carrier.BRING:
        return BringApiClient(
            session,
            entry.data[CONF_API_UID],
            entry.data[CONF_API_KEY],
        )
    if carrier == Carrier.POSTNORD:
        return PostnordApiClient(session, entry.data[CONF_API_KEY])
    return HelthjemApiClient(
        session,
        entry.data[CONF_CLIENT_ID],
        entry.data[CONF_CLIENT_SECRET],
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Nordic Parcel from a config entry."""
    # Register services early (once, when first entry loads)
    # so they're available even if this entry's first refresh fails
    hass.data.setdefault(DOMAIN, {"coordinators": {}})
    if not hass.services.has_service(DOMAIN, SERVICE_ADD_TRACKING):
        _register_services(hass)

    client = _create_client(hass, entry)
    coordinator = NordicParcelCoordinator(hass, entry, client)

    await coordinator.async_config_entry_first_refresh()

    # Clear any auth issue from a previous failed attempt
    ir.async_delete_issue(hass, DOMAIN, f"auth_failed_{entry.entry_id}")

    entry.runtime_data = coordinator

    # Register coordinator in shared registry for cross-entry aggregation
    domain_data = hass.data[DOMAIN]
    domain_data["coordinators"][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for options changes to update scan interval
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    coordinator: NordicParcelCoordinator = entry.runtime_data
    coordinator.update_interval = timedelta(
        seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Remove coordinator from shared registry
    if DOMAIN in hass.data:
        hass.data[DOMAIN]["coordinators"].pop(entry.entry_id, None)

    # Unregister services and clean up shared data if no entries remain
    remaining = [
        e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != entry.entry_id
    ]
    if not remaining:
        hass.services.async_remove(DOMAIN, SERVICE_ADD_TRACKING)
        hass.services.async_remove(DOMAIN, SERVICE_REMOVE_TRACKING)
        hass.data.pop(DOMAIN, None)

    return unload_ok


def _register_services(hass: HomeAssistant) -> None:
    """Register integration services."""

    async def handle_add_tracking(call: ServiceCall) -> None:
        """Handle the add_tracking service call."""
        tracking_id = call.data["tracking_id"].strip().upper()
        carrier_filter = call.data.get("carrier")

        coordinators: list[NordicParcelCoordinator] = [
            entry.runtime_data
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.state is ConfigEntryState.LOADED
        ]

        if carrier_filter:
            coordinators = [c for c in coordinators if c.client.carrier == carrier_filter]

        if not coordinators:
            raise ServiceValidationError(
                f"No matching carrier configured for tracking {tracking_id}",
                translation_domain=DOMAIN,
                translation_key="no_matching_carrier",
                translation_placeholders={"tracking_id": tracking_id},
            )

        await coordinators[0].add_tracking(tracking_id)

    async def handle_remove_tracking(call: ServiceCall) -> None:
        """Handle the remove_tracking service call."""
        tracking_id = call.data["tracking_id"].strip().upper()

        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.state is not ConfigEntryState.LOADED:
                continue
            coordinator: NordicParcelCoordinator = entry.runtime_data
            if tracking_id in coordinator.manual_tracking_ids:
                await coordinator.remove_tracking(tracking_id)
                return

        raise ServiceValidationError(
            f"Tracking ID {tracking_id} not found in any carrier",
            translation_domain=DOMAIN,
            translation_key="tracking_not_found",
            translation_placeholders={"tracking_id": tracking_id},
        )

    hass.services.async_register(
        DOMAIN, SERVICE_ADD_TRACKING, handle_add_tracking, schema=SERVICE_ADD_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_TRACKING,
        handle_remove_tracking,
        schema=SERVICE_REMOVE_SCHEMA,
    )
