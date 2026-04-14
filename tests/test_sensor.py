"""Tests for Nordic Parcel sensor platform."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.nordic_parcel.api import Shipment, TrackingEvent
from custom_components.nordic_parcel.const import (
    DOMAIN,
    Carrier,
    ShipmentStatus,
)
from custom_components.nordic_parcel.coordinator import NordicParcelCoordinator
from custom_components.nordic_parcel.sensor import NordicParcelSensor, NordicParcelSummarySensor


def _make_shipment(
    tracking_id: str = "TEST123",
    status: ShipmentStatus = ShipmentStatus.IN_TRANSIT,
    carrier: Carrier = Carrier.BRING,
    sender: str = "Test Sender",
) -> Shipment:
    """Create a test Shipment object."""
    return Shipment(
        tracking_id=tracking_id,
        carrier=carrier,
        status=status,
        sender=sender,
        events=[
            TrackingEvent(
                timestamp=datetime.now(UTC),
                description="Test event",
                status=status,
            )
        ],
    )


def _mock_client(carrier: Carrier = Carrier.BRING) -> AsyncMock:
    """Create a mock carrier client."""
    client = AsyncMock()
    client.carrier = carrier
    client.get_shipments = AsyncMock(return_value=[])
    client.track_shipment = AsyncMock(return_value=[])
    return client


# --- Parcel sensor tests ---


class TestParcelSensor:
    """Tests for NordicParcelSensor."""

    async def test_sensor_unique_id(self, hass: HomeAssistant, mock_bring_config_entry):
        """Test sensor unique_id format."""
        client = _mock_client()
        coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, client)
        coordinator.data = {"TRACK123": _make_shipment("TRACK123")}

        sensor = NordicParcelSensor(coordinator, "TRACK123")
        assert sensor.unique_id == f"{DOMAIN}_TRACK123"

    async def test_sensor_name_with_sender(self, hass: HomeAssistant, mock_bring_config_entry):
        """Test sensor name includes sender and last 6 of tracking ID."""
        client = _mock_client()
        coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, client)
        coordinator.data = {"ABCDEF123456": _make_shipment("ABCDEF123456", sender="Komplett")}

        sensor = NordicParcelSensor(coordinator, "ABCDEF123456")
        assert sensor.name == "Komplett (123456)"

    async def test_sensor_name_without_sender(self, hass: HomeAssistant, mock_bring_config_entry):
        """Test sensor name falls back to tracking ID when no sender."""
        client = _mock_client()
        coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, client)
        shipment = _make_shipment("TRACK789")
        shipment.sender = None
        coordinator.data = {"TRACK789": shipment}

        sensor = NordicParcelSensor(coordinator, "TRACK789")
        assert sensor.name == "TRACK789"

    async def test_sensor_native_value(self, hass: HomeAssistant, mock_bring_config_entry):
        """Test sensor state returns status value."""
        client = _mock_client()
        coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, client)
        coordinator.data = {"T1": _make_shipment("T1", ShipmentStatus.OUT_FOR_DELIVERY)}

        sensor = NordicParcelSensor(coordinator, "T1")
        assert sensor.native_value == "out_for_delivery"

    async def test_sensor_unavailable_no_data(self, hass: HomeAssistant, mock_bring_config_entry):
        """Test sensor is unavailable when shipment not in coordinator data."""
        client = _mock_client()
        coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, client)
        coordinator.data = {}
        coordinator.last_update_success = True

        sensor = NordicParcelSensor(coordinator, "MISSING")
        assert sensor.available is False

    async def test_sensor_extra_state_attributes(
        self, hass: HomeAssistant, mock_bring_config_entry
    ):
        """Test sensor exposes all expected attributes."""
        client = _mock_client()
        coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, client)
        shipment = _make_shipment("ATTR001", sender="TestSender AS")
        shipment.recipient = "Test Recipient"
        coordinator.data = {"ATTR001": shipment}

        sensor = NordicParcelSensor(coordinator, "ATTR001")
        attrs = sensor.extra_state_attributes

        assert attrs["carrier"] == Carrier.BRING.value
        assert attrs["tracking_id"] == "ATTR001"
        assert attrs["sender"] == "TestSender AS"
        assert attrs["recipient"] == "Test Recipient"
        assert attrs["event_count"] == 1
        assert "last_event_description" in attrs
        assert "last_event_time" in attrs

    async def test_sensor_device_info(self, hass: HomeAssistant, mock_bring_config_entry):
        """Test sensor device info references correct carrier."""
        client = _mock_client()
        coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, client)
        coordinator.data = {"T1": _make_shipment("T1")}

        sensor = NordicParcelSensor(coordinator, "T1")
        assert sensor.device_info["manufacturer"] == "Bring"
        assert sensor.device_info["model"] == "Parcel Tracking"
        assert (DOMAIN, mock_bring_config_entry.entry_id) in sensor.device_info["identifiers"]


# --- Summary sensor tests ---


@pytest.fixture(autouse=True)
def _patch_write_state():
    """Prevent async_write_ha_state from requiring a platform."""
    with patch.object(NordicParcelSummarySensor, "async_write_ha_state"):
        yield


class TestSummarySensor:
    """Tests for NordicParcelSummarySensor."""

    async def test_summary_empty(self, hass: HomeAssistant):
        """Test summary with no coordinators returns 0."""
        hass.data.setdefault(DOMAIN, {"coordinators": {}})
        sensor = NordicParcelSummarySensor(hass)
        sensor._aggregate()

        assert sensor.native_value == 0
        assert sensor.extra_state_attributes["total_active"] == 0
        assert sensor.extra_state_attributes["total_delivered"] == 0

    async def test_summary_counts_active_parcels(
        self, hass: HomeAssistant, mock_bring_config_entry
    ):
        """Test summary counts non-delivered parcels."""
        client = _mock_client()
        coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, client)
        coordinator.data = {
            "T1": _make_shipment("T1", ShipmentStatus.IN_TRANSIT),
            "T2": _make_shipment("T2", ShipmentStatus.OUT_FOR_DELIVERY),
            "T3": _make_shipment("T3", ShipmentStatus.DELIVERED),
        }

        hass.data.setdefault(DOMAIN, {"coordinators": {}})
        hass.data[DOMAIN]["coordinators"]["entry1"] = coordinator

        sensor = NordicParcelSummarySensor(hass)
        sensor._aggregate()

        assert sensor.native_value == 2
        assert sensor.extra_state_attributes["total_active"] == 2
        assert sensor.extra_state_attributes["total_delivered"] == 1

    async def test_summary_status_breakdown(self, hass: HomeAssistant, mock_bring_config_entry):
        """Test summary includes status breakdown in attributes."""
        client = _mock_client()
        coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, client)
        coordinator.data = {
            "T1": _make_shipment("T1", ShipmentStatus.IN_TRANSIT),
            "T2": _make_shipment("T2", ShipmentStatus.IN_TRANSIT),
            "T3": _make_shipment("T3", ShipmentStatus.OUT_FOR_DELIVERY),
            "T4": _make_shipment("T4", ShipmentStatus.CUSTOMS),
        }

        hass.data.setdefault(DOMAIN, {"coordinators": {}})
        hass.data[DOMAIN]["coordinators"]["entry1"] = coordinator

        sensor = NordicParcelSummarySensor(hass)
        sensor._aggregate()

        assert sensor.extra_state_attributes["in_transit"] == 2
        assert sensor.extra_state_attributes["out_for_delivery"] == 1
        assert sensor.extra_state_attributes["customs"] == 1
        # Statuses with 0 count should not appear
        assert "delivered" not in sensor.extra_state_attributes
        assert "failed" not in sensor.extra_state_attributes

    async def test_summary_carrier_breakdown(
        self,
        hass: HomeAssistant,
        mock_bring_config_entry,
        mock_postnord_config_entry,
    ):
        """Test summary includes carrier breakdown in attributes."""
        bring_client = _mock_client(Carrier.BRING)
        bring_coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, bring_client)
        bring_coordinator.data = {
            "T1": _make_shipment("T1", ShipmentStatus.IN_TRANSIT, Carrier.BRING),
            "T2": _make_shipment("T2", ShipmentStatus.IN_TRANSIT, Carrier.BRING),
        }

        postnord_client = _mock_client(Carrier.POSTNORD)
        postnord_coordinator = NordicParcelCoordinator(
            hass, mock_postnord_config_entry, postnord_client
        )
        postnord_coordinator.data = {
            "T3": _make_shipment("T3", ShipmentStatus.OUT_FOR_DELIVERY, Carrier.POSTNORD),
        }

        hass.data.setdefault(DOMAIN, {"coordinators": {}})
        hass.data[DOMAIN]["coordinators"]["bring"] = bring_coordinator
        hass.data[DOMAIN]["coordinators"]["postnord"] = postnord_coordinator

        sensor = NordicParcelSummarySensor(hass)
        sensor._aggregate()

        assert sensor.native_value == 3
        assert sensor.extra_state_attributes["carrier_bring"] == 2
        assert sensor.extra_state_attributes["carrier_postnord"] == 1

    async def test_summary_unique_id(self, hass: HomeAssistant):
        """Test summary sensor has correct unique_id."""
        sensor = NordicParcelSummarySensor(hass)
        assert sensor.unique_id == f"{DOMAIN}_summary"

    async def test_summary_device_info(self, hass: HomeAssistant):
        """Test summary sensor device info."""
        sensor = NordicParcelSummarySensor(hass)
        assert sensor.device_info["identifiers"] == {(DOMAIN, "summary")}
        assert sensor.device_info["name"] == "Nordic Parcel"
