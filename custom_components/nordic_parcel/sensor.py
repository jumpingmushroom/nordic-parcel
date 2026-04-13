"""Sensor platform for Nordic Parcel integration."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Shipment
from .const import DOMAIN, ShipmentStatus
from .coordinator import NordicParcelCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Nordic Parcel sensors from a config entry."""
    coordinator: NordicParcelCoordinator = entry.runtime_data

    known_ids: set[str] = set()
    entity_id_map: dict[str, str] = {}

    @callback
    def _async_add_new_entities() -> None:
        """Add sensors for newly discovered shipments."""
        if not coordinator.data:
            return

        new_entities = []
        current_ids = set(coordinator.data.keys())

        for tracking_id in current_ids - known_ids:
            sensor = NordicParcelSensor(coordinator, tracking_id)
            new_entities.append(sensor)
            known_ids.add(tracking_id)

        # Remove entities for cleaned-up shipments
        removed = known_ids - current_ids
        if removed:
            registry = er.async_get(hass)
            for tracking_id in removed:
                entity_id = entity_id_map.pop(tracking_id, None)
                if entity_id and registry.async_get(entity_id):
                    registry.async_remove(entity_id)
            known_ids.difference_update(removed)

        if new_entities:
            async_add_entities(new_entities)
            for sensor in new_entities:
                if sensor.entity_id:
                    entity_id_map[sensor._tracking_id] = sensor.entity_id

    _async_add_new_entities()

    entry.async_on_unload(
        coordinator.async_add_listener(_async_add_new_entities)
    )


class NordicParcelSensor(CoordinatorEntity[NordicParcelCoordinator], SensorEntity):
    """Sensor representing a tracked parcel."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [s.value for s in ShipmentStatus]
    _attr_translation_key = "parcel"

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
        return shipment.status.value

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

        return attrs
