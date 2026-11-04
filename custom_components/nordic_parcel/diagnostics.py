"""Diagnostics support for Nordic Parcel integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_API_KEY,
    CONF_API_UID,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_DELIVERED_TIMESTAMPS,
    CONF_MANUAL_TRACKING,
)
from .coordinator import NordicParcelCoordinator

# title and unique_id embed the Bring API UID.
TO_REDACT = {
    CONF_API_KEY,
    CONF_API_UID,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    "title",
    "unique_id",
}

# Config-entry data keyed by full tracking IDs, which must be masked by key.
_TRACKING_KEYED = (CONF_MANUAL_TRACKING, CONF_DELIVERED_TIMESTAMPS)


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
                    shipment.estimated_delivery.isoformat() if shipment.estimated_delivery else None
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

    redacted_entry = async_redact_data(entry.as_dict(), TO_REDACT)
    # async_redact_data cannot mask dict *keys*; mask tracking IDs used as keys
    # in manual_tracking / delivered_timestamps so they don't leak in full.
    entry_data = redacted_entry.get("data")
    if isinstance(entry_data, dict):
        for key in _TRACKING_KEYED:
            keyed = entry_data.get(key)
            if isinstance(keyed, dict):
                entry_data[key] = {_mask_tracking_id(tid): value for tid, value in keyed.items()}

    return {
        "config_entry": redacted_entry,
        "coordinator_data": shipments_data,
    }
