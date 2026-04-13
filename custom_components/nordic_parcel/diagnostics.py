"""Diagnostics support for Nordic Parcel integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_API_KEY, CONF_API_UID, CONF_CLIENT_ID, CONF_CLIENT_SECRET
from .coordinator import NordicParcelCoordinator

TO_REDACT = {CONF_API_KEY, CONF_API_UID, CONF_CLIENT_ID, CONF_CLIENT_SECRET}


def _mask_tracking_id(tracking_id: str) -> str:
    """Partially mask a tracking ID, showing only last 4 characters."""
    if len(tracking_id) <= 4:
        return tracking_id
    return "*" * (len(tracking_id) - 4) + tracking_id[-4:]


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: NordicParcelCoordinator = entry.runtime_data

    shipments_data = {}
    if coordinator.data:
        for tracking_id, shipment in coordinator.data.items():
            masked_id = _mask_tracking_id(tracking_id)
            shipments_data[masked_id] = {
                "carrier": shipment.carrier.value,
                "status": shipment.status.value,
                "sender": "**REDACTED**" if shipment.sender else None,
                "recipient": "**REDACTED**" if shipment.recipient else None,
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
                        "location": "**REDACTED**" if e.location else None,
                        "status": e.status.value,
                    }
                    for e in shipment.events
                ],
            }

    return {
        "config_entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "coordinator_data": shipments_data,
    }
