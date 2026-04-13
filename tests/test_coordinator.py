"""Tests for the NordicParcelCoordinator."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.nordic_parcel.api import (
    CarrierAuthError,
    CarrierApiError,
    CarrierNotFoundError,
    CarrierRateLimitError,
    Shipment,
    TrackingEvent,
)
from custom_components.nordic_parcel.const import (
    CONF_CLEANUP_DAYS,
    CONF_DELIVERED_TIMESTAMPS,
    CONF_MANUAL_TRACKING,
    CONF_SCAN_INTERVAL,
    DOMAIN,
    Carrier,
    ShipmentStatus,
)
from custom_components.nordic_parcel.coordinator import NordicParcelCoordinator


def _make_shipment(
    tracking_id: str = "TEST123",
    status: ShipmentStatus = ShipmentStatus.IN_TRANSIT,
    sender: str = "Test Sender",
) -> Shipment:
    """Create a test Shipment object."""
    return Shipment(
        tracking_id=tracking_id,
        carrier=Carrier.BRING,
        status=status,
        sender=sender,
        events=[
            TrackingEvent(
                timestamp=datetime.now(timezone.utc),
                description="Test event",
                status=status,
            )
        ],
    )


@pytest.fixture
def mock_client() -> AsyncMock:
    """Create a mock CarrierClient."""
    client = AsyncMock()
    client.carrier = Carrier.BRING
    client.get_shipments = AsyncMock(return_value=[])
    client.track_shipment = AsyncMock(return_value=[])
    return client


@pytest.fixture
def coordinator(hass: HomeAssistant, mock_bring_config_entry, mock_client):
    """Create a NordicParcelCoordinator for testing."""
    return NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)


# --- _async_update_data tests ---


async def test_update_no_tracking_ids(
    hass: HomeAssistant, coordinator, mock_client
):
    """Test update with no manual tracking IDs returns empty dict."""
    result = await coordinator._async_update_data()
    assert result == {}
    mock_client.get_shipments.assert_awaited_once()
    mock_client.track_shipment.assert_not_awaited()


async def test_update_fetches_manual_tracking(
    hass: HomeAssistant,
    mock_bring_config_entry,
    mock_client,
):
    """Test update fetches each manual tracking ID."""
    shipment = _make_shipment("TRACK001")
    mock_client.track_shipment.return_value = [shipment]

    # Add a manual tracking ID to the config entry
    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {"TRACK001": {"added": "2026-04-13T00:00:00+00:00"}},
        },
    )

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)
    result = await coordinator._async_update_data()

    assert "TRACK001" in result
    assert result["TRACK001"].status == ShipmentStatus.IN_TRANSIT
    mock_client.track_shipment.assert_awaited_once_with("TRACK001")


async def test_update_auth_error_raises_config_entry_auth_failed(
    hass: HomeAssistant, coordinator, mock_client
):
    """Test that CarrierAuthError from get_shipments raises ConfigEntryAuthFailed."""
    mock_client.get_shipments.side_effect = CarrierAuthError("Bad auth")

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_update_auth_error_on_track_raises_config_entry_auth_failed(
    hass: HomeAssistant,
    mock_bring_config_entry,
    mock_client,
):
    """Test that CarrierAuthError from track_shipment raises ConfigEntryAuthFailed."""
    mock_client.track_shipment.side_effect = CarrierAuthError("Bad auth")

    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {"TRACK001": {"added": "2026-04-13T00:00:00+00:00"}},
        },
    )

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_update_rate_limit_raises_update_failed(
    hass: HomeAssistant, coordinator, mock_client
):
    """Test that CarrierRateLimitError from get_shipments raises UpdateFailed."""
    mock_client.get_shipments.side_effect = CarrierRateLimitError("Too fast")

    with pytest.raises(UpdateFailed, match="Rate limited"):
        await coordinator._async_update_data()


async def test_update_rate_limit_on_track_raises_update_failed(
    hass: HomeAssistant,
    mock_bring_config_entry,
    mock_client,
):
    """Test that CarrierRateLimitError from track_shipment raises UpdateFailed."""
    mock_client.track_shipment.side_effect = CarrierRateLimitError("Too fast")

    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {"TRACK001": {"added": "2026-04-13T00:00:00+00:00"}},
        },
    )

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)

    with pytest.raises(UpdateFailed, match="Rate limited"):
        await coordinator._async_update_data()


async def test_update_not_found_skips_tracking_id(
    hass: HomeAssistant,
    mock_bring_config_entry,
    mock_client,
):
    """Test that CarrierNotFoundError skips the tracking ID without error."""
    mock_client.track_shipment.side_effect = CarrierNotFoundError("Not found")

    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {"NOTFOUND1": {"added": "2026-04-13T00:00:00+00:00"}},
        },
    )

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)
    result = await coordinator._async_update_data()

    assert result == {}


async def test_update_api_error_logs_warning_continues(
    hass: HomeAssistant,
    mock_bring_config_entry,
    mock_client,
):
    """Test that a generic CarrierApiError logs warning but doesn't fail."""
    mock_client.track_shipment.side_effect = CarrierApiError("Server error")

    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {"ERR001": {"added": "2026-04-13T00:00:00+00:00"}},
        },
    )

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)
    result = await coordinator._async_update_data()

    # Should return empty since the only tracking ID errored
    assert result == {}


# --- Status change event tests ---


async def test_status_change_event_not_fired_on_first_poll(
    hass: HomeAssistant,
    mock_bring_config_entry,
    mock_client,
):
    """Test that no status_changed event fires on the first poll (old_status is None)."""
    shipment = _make_shipment("TRACK001", ShipmentStatus.IN_TRANSIT)
    mock_client.track_shipment.return_value = [shipment]

    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {"TRACK001": {"added": "2026-04-13T00:00:00+00:00"}},
        },
    )

    events = []
    hass.bus.async_listen(f"{DOMAIN}_status_changed", lambda e: events.append(e))

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert len(events) == 0


async def test_status_change_event_fired_on_transition(
    hass: HomeAssistant,
    mock_bring_config_entry,
    mock_client,
):
    """Test that status_changed event fires on status transition."""
    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {"TRACK001": {"added": "2026-04-13T00:00:00+00:00"}},
        },
    )

    events = []
    hass.bus.async_listen(f"{DOMAIN}_status_changed", lambda e: events.append(e))

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)

    # First poll: IN_TRANSIT
    mock_client.track_shipment.return_value = [
        _make_shipment("TRACK001", ShipmentStatus.IN_TRANSIT)
    ]
    await coordinator._async_update_data()
    await hass.async_block_till_done()
    assert len(events) == 0

    # Second poll: OUT_FOR_DELIVERY
    mock_client.track_shipment.return_value = [
        _make_shipment("TRACK001", ShipmentStatus.OUT_FOR_DELIVERY)
    ]
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["tracking_id"] == "TRACK001"
    assert events[0].data["old_status"] == ShipmentStatus.IN_TRANSIT.value
    assert events[0].data["new_status"] == ShipmentStatus.OUT_FOR_DELIVERY.value


async def test_delivered_event_fired_on_delivery(
    hass: HomeAssistant,
    mock_bring_config_entry,
    mock_client,
):
    """Test that delivered event fires when shipment becomes delivered."""
    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {"TRACK001": {"added": "2026-04-13T00:00:00+00:00"}},
        },
    )

    delivered_events = []
    hass.bus.async_listen(f"{DOMAIN}_delivered", lambda e: delivered_events.append(e))

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)

    # First poll: IN_TRANSIT
    mock_client.track_shipment.return_value = [
        _make_shipment("TRACK001", ShipmentStatus.IN_TRANSIT)
    ]
    await coordinator._async_update_data()
    await hass.async_block_till_done()
    assert len(delivered_events) == 0

    # Second poll: DELIVERED
    mock_client.track_shipment.return_value = [
        _make_shipment("TRACK001", ShipmentStatus.DELIVERED)
    ]
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert len(delivered_events) == 1
    assert delivered_events[0].data["tracking_id"] == "TRACK001"
    assert delivered_events[0].data["carrier"] == Carrier.BRING.value


async def test_delivered_event_not_fired_twice(
    hass: HomeAssistant,
    mock_bring_config_entry,
    mock_client,
):
    """Test that delivered event only fires once per shipment."""
    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {"TRACK001": {"added": "2026-04-13T00:00:00+00:00"}},
        },
    )

    delivered_events = []
    hass.bus.async_listen(f"{DOMAIN}_delivered", lambda e: delivered_events.append(e))

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)

    # Two polls with DELIVERED status
    mock_client.track_shipment.return_value = [
        _make_shipment("TRACK001", ShipmentStatus.DELIVERED)
    ]
    await coordinator._async_update_data()
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert len(delivered_events) == 1


# --- Auto-cleanup tests ---


async def test_auto_cleanup_removes_expired_delivered_parcels(
    hass: HomeAssistant,
    mock_bring_config_entry,
    mock_client,
):
    """Test that delivered parcels are removed after cleanup_days."""
    delivered_time = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()

    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {"OLD001": {"added": "2026-04-01T00:00:00+00:00"}},
            CONF_DELIVERED_TIMESTAMPS: {"OLD001": delivered_time},
        },
        options={CONF_CLEANUP_DAYS: 3},
    )

    mock_client.track_shipment.return_value = [
        _make_shipment("OLD001", ShipmentStatus.DELIVERED)
    ]

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)
    result = await coordinator._async_update_data()

    # The shipment should have been cleaned up
    assert "OLD001" not in result
    # Check config entry was updated to remove it
    assert "OLD001" not in mock_bring_config_entry.data.get(CONF_MANUAL_TRACKING, {})


async def test_auto_cleanup_keeps_recent_delivered_parcels(
    hass: HomeAssistant,
    mock_bring_config_entry,
    mock_client,
):
    """Test that recently delivered parcels are kept."""
    delivered_time = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()

    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {"NEW001": {"added": "2026-04-12T00:00:00+00:00"}},
            CONF_DELIVERED_TIMESTAMPS: {"NEW001": delivered_time},
        },
        options={CONF_CLEANUP_DAYS: 3},
    )

    mock_client.track_shipment.return_value = [
        _make_shipment("NEW001", ShipmentStatus.DELIVERED)
    ]

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)
    result = await coordinator._async_update_data()

    assert "NEW001" in result


async def test_auto_cleanup_disabled_when_zero(
    hass: HomeAssistant,
    mock_bring_config_entry,
    mock_client,
):
    """Test that cleanup is disabled when cleanup_days is 0."""
    delivered_time = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()

    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {"OLD001": {"added": "2026-01-01T00:00:00+00:00"}},
            CONF_DELIVERED_TIMESTAMPS: {"OLD001": delivered_time},
        },
        options={CONF_CLEANUP_DAYS: 0},
    )

    mock_client.track_shipment.return_value = [
        _make_shipment("OLD001", ShipmentStatus.DELIVERED)
    ]

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)
    result = await coordinator._async_update_data()

    assert "OLD001" in result


# --- add_tracking / remove_tracking tests ---


async def test_add_tracking_uppercases_id(
    hass: HomeAssistant,
    mock_bring_config_entry,
    mock_client,
):
    """Test that add_tracking uppercases the tracking ID."""
    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)
    await coordinator.add_tracking("abc123")

    manual = mock_bring_config_entry.data.get(CONF_MANUAL_TRACKING, {})
    assert "ABC123" in manual
    assert "abc123" not in manual


async def test_add_tracking_persists_to_config_entry(
    hass: HomeAssistant,
    mock_bring_config_entry,
    mock_client,
):
    """Test that add_tracking persists the ID in config entry data."""
    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)
    await coordinator.add_tracking("TRACK999")

    manual = mock_bring_config_entry.data[CONF_MANUAL_TRACKING]
    assert "TRACK999" in manual
    assert "added" in manual["TRACK999"]


async def test_remove_tracking_uppercases_and_removes(
    hass: HomeAssistant,
    mock_bring_config_entry,
    mock_client,
):
    """Test that remove_tracking uppercases and removes the ID."""
    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {"TRACK001": {"added": "2026-04-13T00:00:00+00:00"}},
        },
    )

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)
    await coordinator.remove_tracking("track001")

    manual = mock_bring_config_entry.data.get(CONF_MANUAL_TRACKING, {})
    assert "TRACK001" not in manual


async def test_remove_tracking_nonexistent_id_is_noop(
    hass: HomeAssistant,
    mock_bring_config_entry,
    mock_client,
):
    """Test that removing a non-existent ID doesn't error."""
    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)
    await coordinator.remove_tracking("DOESNOTEXIST")
    # Should not raise


async def test_manual_tracking_ids_property(
    hass: HomeAssistant,
    mock_bring_config_entry,
    mock_client,
):
    """Test the manual_tracking_ids property returns current IDs."""
    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {
                "AAA": {"added": "2026-04-13T00:00:00+00:00"},
                "BBB": {"added": "2026-04-13T00:00:00+00:00"},
            },
        },
    )

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)
    ids = coordinator.manual_tracking_ids
    assert sorted(ids) == ["AAA", "BBB"]


# --- Consignment replacement test ---


async def test_consignment_replaced_with_package_ids(
    hass: HomeAssistant,
    mock_bring_config_entry,
    mock_client,
):
    """Test that consignment IDs are replaced with resolved package IDs."""
    # The API returns packages with different IDs than the consignment
    mock_client.track_shipment.return_value = [
        _make_shipment("PKG001"),
        _make_shipment("PKG002"),
    ]

    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {"CONS001": {"added": "2026-04-13T00:00:00+00:00"}},
        },
    )

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)
    result = await coordinator._async_update_data()

    assert "PKG001" in result
    assert "PKG002" in result
    # The consignment ID should be replaced in config
    manual = mock_bring_config_entry.data[CONF_MANUAL_TRACKING]
    assert "CONS001" not in manual
    assert "PKG001" in manual
    assert "PKG002" in manual
