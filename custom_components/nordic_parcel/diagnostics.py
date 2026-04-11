"""Diagnostics support for Nordic Parcel integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_API_KEY, CONF_API_UID, CONF_CLIENT_ID, CONF_CLIENT_SECRET, DOMAIN
from .coordinator import NordicParcelCoordinator

TO_REDACT = {CONF_API_KEY, CONF_API_UID, CONF_CLIENT_ID, CONF_CLIENT_SECRET}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: NordicParcelCoordinator = hass.data[DOMAIN][entry.entry_id]

    shipments_data = {}
    if coordinator.data:
        for tracking_id, shipment in coordinator.data.items():
            shipments_data[tracking_id] = {
                "carrier": shipment.carrier.value,
                "status": shipment.status.value,
                "sender": shipment.sender,
                "recipient": shipment.recipient,
                "estimated_delivery": (
                    shipment.estimated_delivery.isoformat()
                    if shipment.estimated_delivery
                    else None
                ),
                "event_count": len(shipment.events),
                "events": [
                    {
                        "timestamp": e.timestamp.isoformat(),
                        "description": e.description,
                        "location": e.location,
                        "status": e.status.value,
                    }
                    for e in shipment.events
                ],
            }

    return {
        "config_entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "coordinator_data": shipments_data,
    }
