"""Sensor platform for Nordic Parcel integration."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Shipment
from .const import DOMAIN
from .coordinator import NordicParcelCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Nordic Parcel sensors from a config entry."""
    coordinator: NordicParcelCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Track which tracking IDs have entities
    known_ids: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        """Add sensors for newly discovered shipments."""
        if not coordinator.data:
            return

        new_entities = []
        current_ids = set(coordinator.data.keys())

        for tracking_id in current_ids - known_ids:
            new_entities.append(
                NordicParcelSensor(coordinator, tracking_id)
            )
            known_ids.add(tracking_id)

        # Remove IDs that are no longer in coordinator data (cleaned up)
        removed = known_ids - current_ids
        known_ids.difference_update(removed)

        if new_entities:
            async_add_entities(new_entities)

    # Add entities for any shipments already known
    _async_add_new_entities()

    # Listen for coordinator updates to add new shipments dynamically
    entry.async_on_unload(
        coordinator.async_add_listener(_async_add_new_entities)
    )


class NordicParcelSensor(CoordinatorEntity[NordicParcelCoordinator], SensorEntity):
    """Sensor representing a tracked parcel."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NordicParcelCoordinator,
        tracking_id: str,
    ) -> None:
        super().__init__(coordinator, context=tracking_id)
        self._tracking_id = tracking_id
        self._attr_unique_id = f"{DOMAIN}_{tracking_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name=coordinator.config_entry.title,
            manufacturer=coordinator.client.carrier.value.title(),
            model="Parcel Tracking",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _shipment(self) -> Shipment | None:
        """Get the current shipment data from coordinator."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._tracking_id)

    @property
    def available(self) -> bool:
        """Return True if the shipment data is available."""
        return super().available and self._shipment is not None

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        shipment = self._shipment
        if shipment and shipment.sender:
            return f"{shipment.sender} ({self._tracking_id[-6:]})"
        return self._tracking_id

    @property
    def native_value(self) -> str | None:
        """Return the shipment status as the sensor state."""
        shipment = self._shipment
        if not shipment:
            return None
        return shipment.status.value.replace("_", " ").title()

    @property
    def icon(self) -> str:
        """Return an icon based on status."""
        shipment = self._shipment
        if not shipment:
            return "mdi:package-variant"

        icon_map = {
            "pre_transit": "mdi:package-variant-closed",
            "in_transit": "mdi:truck-delivery",
            "out_for_delivery": "mdi:truck-fast",
            "ready_for_pickup": "mdi:mailbox-up",
            "delivered": "mdi:package-variant-closed-check",
            "returned": "mdi:package-variant-closed-minus",
            "failed": "mdi:package-variant-closed-remove",
        }
        return icon_map.get(shipment.status.value, "mdi:package-variant")

    @property
    def extra_state_attributes(self) -> dict:
        """Return detailed shipment attributes."""
        shipment = self._shipment
        if not shipment:
            return {}

        attrs = {
            "carrier": shipment.carrier.value,
            "tracking_id": shipment.tracking_id,
            "sender": shipment.sender,
            "recipient": shipment.recipient,
            "estimated_delivery": (
                shipment.estimated_delivery.isoformat()
                if shipment.estimated_delivery
                else None
            ),
            "event_count": len(shipment.events),
        }

        last = shipment.last_event
        if last:
            attrs["last_event_description"] = last.description
            attrs["last_event_time"] = last.timestamp.isoformat()
            attrs["last_event_location"] = last.location

        # Include recent events (limit to 10 to keep attributes manageable)
        attrs["events"] = [
            {
                "time": e.timestamp.isoformat(),
                "description": e.description,
                "location": e.location,
                "status": e.status.value,
            }
            for e in shipment.events[:10]
        ]

        return attrs
