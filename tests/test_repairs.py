"""Tests for Nordic Parcel repairs integration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir

from custom_components.nordic_parcel.api import Shipment, TrackingEvent
from custom_components.nordic_parcel.const import (
    CONF_MANUAL_TRACKING,
    DOMAIN,
    Carrier,
    ShipmentStatus,
)
from custom_components.nordic_parcel.coordinator import NordicParcelCoordinator


def _make_shipment(
    tracking_id: str = "TEST123",
    status: ShipmentStatus = ShipmentStatus.IN_TRANSIT,
    carrier: Carrier = Carrier.BRING,
    event_age_days: int = 0,
) -> Shipment:
    """Create a test Shipment with event at given age."""
    event_time = datetime.now(UTC) - timedelta(days=event_age_days)
    return Shipment(
        tracking_id=tracking_id,
        carrier=carrier,
        status=status,
        sender="Test Sender",
        events=[
            TrackingEvent(
                timestamp=event_time,
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


# --- Stale tracking issue tests ---


async def test_stale_tracking_issue_created(
    hass: HomeAssistant, mock_bring_config_entry, mock_client
):
    """Test that a stale tracking issue is created for old shipments."""
    shipment = _make_shipment("STALE001", ShipmentStatus.IN_TRANSIT, event_age_days=15)
    mock_client.track_shipment.return_value = [shipment]

    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {"STALE001": {"added": "2026-03-01T00:00:00+00:00"}},
        },
    )

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)
    await coordinator._async_update_data()

    issue_reg = ir.async_get(hass)
    issue = issue_reg.async_get_issue(DOMAIN, "stale_tracking_STALE001")
    assert issue is not None
    assert issue.severity == ir.IssueSeverity.WARNING
    assert issue.is_fixable is True


async def test_stale_tracking_issue_not_created_for_recent(
    hass: HomeAssistant, mock_bring_config_entry, mock_client
):
    """Test that no stale issue is created for recently-updated shipments."""
    shipment = _make_shipment("FRESH001", ShipmentStatus.IN_TRANSIT, event_age_days=5)
    mock_client.track_shipment.return_value = [shipment]

    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {"FRESH001": {"added": "2026-04-01T00:00:00+00:00"}},
        },
    )

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)
    await coordinator._async_update_data()

    issue_reg = ir.async_get(hass)
    issue = issue_reg.async_get_issue(DOMAIN, "stale_tracking_FRESH001")
    assert issue is None


async def test_stale_tracking_issue_not_created_for_delivered(
    hass: HomeAssistant, mock_bring_config_entry, mock_client
):
    """Test that no stale issue is created for delivered shipments."""
    shipment = _make_shipment("DEL001", ShipmentStatus.DELIVERED, event_age_days=20)
    mock_client.track_shipment.return_value = [shipment]

    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {"DEL001": {"added": "2026-03-01T00:00:00+00:00"}},
        },
    )

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)
    await coordinator._async_update_data()

    issue_reg = ir.async_get(hass)
    issue = issue_reg.async_get_issue(DOMAIN, "stale_tracking_DEL001")
    assert issue is None


async def test_stale_tracking_issue_auto_cleared(
    hass: HomeAssistant, mock_bring_config_entry, mock_client
):
    """Test that stale issue is auto-cleared when parcel updates."""
    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {"STALE002": {"added": "2026-03-01T00:00:00+00:00"}},
        },
    )

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)

    # First update: stale shipment
    mock_client.track_shipment.return_value = [
        _make_shipment("STALE002", ShipmentStatus.IN_TRANSIT, event_age_days=15)
    ]
    await coordinator._async_update_data()

    issue_reg = ir.async_get(hass)
    assert issue_reg.async_get_issue(DOMAIN, "stale_tracking_STALE002") is not None

    # Second update: shipment now has recent event
    mock_client.track_shipment.return_value = [
        _make_shipment("STALE002", ShipmentStatus.IN_TRANSIT, event_age_days=1)
    ]
    await coordinator._async_update_data()

    assert issue_reg.async_get_issue(DOMAIN, "stale_tracking_STALE002") is None


# --- Stuck in customs issue tests ---


async def test_customs_issue_created(hass: HomeAssistant, mock_bring_config_entry, mock_client):
    """Test that customs issue is created for parcels stuck 7+ days."""
    shipment = _make_shipment("CUST001", ShipmentStatus.CUSTOMS, event_age_days=8)
    mock_client.track_shipment.return_value = [shipment]

    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {"CUST001": {"added": "2026-03-01T00:00:00+00:00"}},
        },
    )

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)
    await coordinator._async_update_data()

    issue_reg = ir.async_get(hass)
    issue = issue_reg.async_get_issue(DOMAIN, "stuck_customs_CUST001")
    assert issue is not None
    assert issue.severity == ir.IssueSeverity.WARNING
    assert issue.is_fixable is False


async def test_customs_issue_not_created_for_recent(
    hass: HomeAssistant, mock_bring_config_entry, mock_client
):
    """Test that no customs issue for parcels in customs less than 7 days."""
    shipment = _make_shipment("CUST002", ShipmentStatus.CUSTOMS, event_age_days=3)
    mock_client.track_shipment.return_value = [shipment]

    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {"CUST002": {"added": "2026-04-01T00:00:00+00:00"}},
        },
    )

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)
    await coordinator._async_update_data()

    issue_reg = ir.async_get(hass)
    assert issue_reg.async_get_issue(DOMAIN, "stuck_customs_CUST002") is None


async def test_customs_issue_auto_cleared_on_status_change(
    hass: HomeAssistant, mock_bring_config_entry, mock_client
):
    """Test that customs issue is cleared when parcel leaves customs."""
    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {"CUST003": {"added": "2026-03-01T00:00:00+00:00"}},
        },
    )

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)

    # First update: stuck in customs
    mock_client.track_shipment.return_value = [
        _make_shipment("CUST003", ShipmentStatus.CUSTOMS, event_age_days=10)
    ]
    await coordinator._async_update_data()

    issue_reg = ir.async_get(hass)
    assert issue_reg.async_get_issue(DOMAIN, "stuck_customs_CUST003") is not None

    # Second update: cleared customs, now in transit
    mock_client.track_shipment.return_value = [
        _make_shipment("CUST003", ShipmentStatus.IN_TRANSIT, event_age_days=0)
    ]
    await coordinator._async_update_data()

    assert issue_reg.async_get_issue(DOMAIN, "stuck_customs_CUST003") is None


# --- Auth failed issue tests ---


async def test_auth_failed_issue_created_on_get_shipments(
    hass: HomeAssistant, mock_bring_config_entry, mock_client
):
    """Test that auth issue is created when get_shipments fails."""
    from custom_components.nordic_parcel.api import CarrierAuthError

    mock_client.get_shipments.side_effect = CarrierAuthError("Bad auth")

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()

    issue_reg = ir.async_get(hass)
    issue = issue_reg.async_get_issue(DOMAIN, f"auth_failed_{mock_bring_config_entry.entry_id}")
    assert issue is not None
    assert issue.severity == ir.IssueSeverity.ERROR


async def test_auth_failed_issue_created_on_track_shipment(
    hass: HomeAssistant, mock_bring_config_entry, mock_client
):
    """Test that auth issue is created when track_shipment fails."""
    from custom_components.nordic_parcel.api import CarrierAuthError

    mock_client.track_shipment.side_effect = CarrierAuthError("Bad auth")

    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {"AUTH001": {"added": "2026-04-01T00:00:00+00:00"}},
        },
    )

    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, mock_client)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()

    issue_reg = ir.async_get(hass)
    issue = issue_reg.async_get_issue(DOMAIN, f"auth_failed_{mock_bring_config_entry.entry_id}")
    assert issue is not None
    assert issue.severity == ir.IssueSeverity.ERROR
