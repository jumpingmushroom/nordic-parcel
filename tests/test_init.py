"""Tests for Nordic Parcel integration setup, unload, and services."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.nordic_parcel.const import (
    CONF_MANUAL_TRACKING,
    CONF_SCAN_INTERVAL,
    DOMAIN,
    Carrier,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

MOCK_SESSION = "custom_components.nordic_parcel.config_flow.async_get_clientsession"


def _mock_client(carrier: Carrier = Carrier.BRING) -> AsyncMock:
    """Create a mock CarrierClient."""
    client = AsyncMock()
    client.carrier = carrier
    client.get_shipments = AsyncMock(return_value=[])
    client.track_shipment = AsyncMock(return_value=[])
    client.close = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# Setup / unload tests
# ---------------------------------------------------------------------------


async def test_async_setup_entry_success(hass: HomeAssistant, mock_bring_config_entry) -> None:
    """Test successful setup creates coordinator and registers services."""
    client = _mock_client()
    with patch("custom_components.nordic_parcel._create_client", return_value=client):
        await hass.config_entries.async_setup(mock_bring_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_bring_config_entry.state is ConfigEntryState.LOADED
    assert DOMAIN in hass.data
    assert mock_bring_config_entry.entry_id in hass.data[DOMAIN]["coordinators"]
    assert hass.services.has_service(DOMAIN, "add_tracking")
    assert hass.services.has_service(DOMAIN, "remove_tracking")


async def test_async_setup_entry_auth_failure(hass: HomeAssistant, mock_bring_config_entry) -> None:
    """Test setup fails gracefully on auth error."""
    from custom_components.nordic_parcel.api import CarrierAuthError

    client = _mock_client()
    client.get_shipments.side_effect = CarrierAuthError("Bad auth")

    with patch("custom_components.nordic_parcel._create_client", return_value=client):
        await hass.config_entries.async_setup(mock_bring_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_bring_config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_async_unload_entry(hass: HomeAssistant) -> None:
    """Test unloading one entry keeps services and other entry intact."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.nordic_parcel.const import CONF_API_KEY, CONF_API_UID, CONF_CARRIER

    bring_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bring",
        data={CONF_CARRIER: Carrier.BRING, CONF_API_UID: "a@b.com", CONF_API_KEY: "k1"},
        unique_id="bring_unload_test",
    )
    postnord_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Postnord",
        data={CONF_CARRIER: Carrier.POSTNORD, CONF_API_KEY: "k2"},
        unique_id="postnord_unload_test",
    )
    bring_entry.add_to_hass(hass)
    postnord_entry.add_to_hass(hass)

    bring_client = _mock_client(Carrier.BRING)
    postnord_client = _mock_client(Carrier.POSTNORD)

    with patch(
        "custom_components.nordic_parcel._create_client",
        side_effect=[bring_client, postnord_client],
    ):
        # Setting up the first entry triggers domain setup which loads both
        await hass.config_entries.async_setup(bring_entry.entry_id)
        await hass.async_block_till_done()

    assert bring_entry.state is ConfigEntryState.LOADED
    assert postnord_entry.state is ConfigEntryState.LOADED

    # Unload Bring entry
    await hass.config_entries.async_unload(bring_entry.entry_id)
    await hass.async_block_till_done()

    assert bring_entry.state is ConfigEntryState.NOT_LOADED
    assert postnord_entry.state is ConfigEntryState.LOADED
    # Services should still exist (Postnord is still loaded)
    assert hass.services.has_service(DOMAIN, "add_tracking")
    # Bring coordinator removed
    assert bring_entry.entry_id not in hass.data[DOMAIN]["coordinators"]


async def test_summary_survives_unload_of_owning_entry(hass: HomeAssistant) -> None:
    """Unloading the entry that created the summary must not orphan it.

    The summary entity is added via the first entry's platform. After that
    entry unloads, the shared reference must be cleared so a later setup
    recreates a working summary instead of writing state on a removed entity.
    """
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.nordic_parcel.const import CONF_API_KEY, CONF_API_UID, CONF_CARRIER

    bring_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bring",
        data={CONF_CARRIER: Carrier.BRING, CONF_API_UID: "a@b.com", CONF_API_KEY: "k1"},
        unique_id="bring_summary_test",
    )
    postnord_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Postnord",
        data={CONF_CARRIER: Carrier.POSTNORD, CONF_API_KEY: "k2"},
        unique_id="postnord_summary_test",
    )
    bring_entry.add_to_hass(hass)
    postnord_entry.add_to_hass(hass)

    with patch(
        "custom_components.nordic_parcel._create_client",
        side_effect=[_mock_client(Carrier.BRING), _mock_client(Carrier.POSTNORD)],
    ):
        await hass.config_entries.async_setup(bring_entry.entry_id)
        await hass.async_block_till_done()

    summary = hass.data[DOMAIN].get("summary_entity")
    assert summary is not None and summary.added

    # Unload the entry that created the summary; the stale reference must go.
    await hass.config_entries.async_unload(bring_entry.entry_id)
    await hass.async_block_till_done()

    orphan = hass.data[DOMAIN].get("summary_entity")
    assert orphan is None or orphan.added

    # Reloading the entry must recreate a working summary without raising.
    with patch(
        "custom_components.nordic_parcel._create_client",
        return_value=_mock_client(Carrier.BRING),
    ):
        await hass.config_entries.async_setup(bring_entry.entry_id)
        await hass.async_block_till_done()

    recreated = hass.data[DOMAIN].get("summary_entity")
    assert recreated is not None and recreated.added
    assert bring_entry.state is ConfigEntryState.LOADED
    assert postnord_entry.state is ConfigEntryState.LOADED


async def test_async_unload_failure_keeps_shared_state(
    hass: HomeAssistant, mock_bring_config_entry
) -> None:
    """If platform unload fails, coordinator and services must remain."""
    client = _mock_client()
    with patch("custom_components.nordic_parcel._create_client", return_value=client):
        await hass.config_entries.async_setup(mock_bring_config_entry.entry_id)
        await hass.async_block_till_done()

    entry_id = mock_bring_config_entry.entry_id
    assert entry_id in hass.data[DOMAIN]["coordinators"]

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
        return_value=False,
    ):
        result = await hass.config_entries.async_unload(entry_id)
        await hass.async_block_till_done()

    assert result is False
    # Shared state must survive a failed unload.
    assert entry_id in hass.data[DOMAIN]["coordinators"]
    assert hass.services.has_service(DOMAIN, "add_tracking")


async def test_async_unload_last_entry(hass: HomeAssistant, mock_bring_config_entry) -> None:
    """Test unloading last entry removes services and domain data."""
    client = _mock_client()
    with patch("custom_components.nordic_parcel._create_client", return_value=client):
        await hass.config_entries.async_setup(mock_bring_config_entry.entry_id)
        await hass.async_block_till_done()

    await hass.config_entries.async_unload(mock_bring_config_entry.entry_id)
    await hass.async_block_till_done()

    assert not hass.services.has_service(DOMAIN, "add_tracking")
    assert not hass.services.has_service(DOMAIN, "remove_tracking")
    assert DOMAIN not in hass.data


async def test_options_update_changes_scan_interval(
    hass: HomeAssistant, mock_bring_config_entry
) -> None:
    """Test options listener updates coordinator scan interval."""
    client = _mock_client()
    with patch("custom_components.nordic_parcel._create_client", return_value=client):
        await hass.config_entries.async_setup(mock_bring_config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = mock_bring_config_entry.runtime_data
    assert coordinator.update_interval == timedelta(seconds=900)

    hass.config_entries.async_update_entry(
        mock_bring_config_entry, options={CONF_SCAN_INTERVAL: 300}
    )
    await hass.async_block_till_done()

    assert coordinator.update_interval == timedelta(seconds=300)


# ---------------------------------------------------------------------------
# Service handler tests
# ---------------------------------------------------------------------------


async def test_add_tracking_service(hass: HomeAssistant, mock_bring_config_entry) -> None:
    """Test add_tracking service calls coordinator.add_tracking."""
    client = _mock_client()
    with patch("custom_components.nordic_parcel._create_client", return_value=client):
        await hass.config_entries.async_setup(mock_bring_config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = mock_bring_config_entry.runtime_data
    with patch.object(coordinator, "add_tracking", new_callable=AsyncMock) as mock_add:
        await hass.services.async_call(
            DOMAIN,
            "add_tracking",
            {"tracking_id": "test123"},
            blocking=True,
        )
        mock_add.assert_awaited_once_with("TEST123")


async def test_add_tracking_strips_whitespace(hass: HomeAssistant, mock_bring_config_entry) -> None:
    """Test add_tracking strips whitespace from tracking ID."""
    client = _mock_client()
    with patch("custom_components.nordic_parcel._create_client", return_value=client):
        await hass.config_entries.async_setup(mock_bring_config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = mock_bring_config_entry.runtime_data
    with patch.object(coordinator, "add_tracking", new_callable=AsyncMock) as mock_add:
        await hass.services.async_call(
            DOMAIN,
            "add_tracking",
            {"tracking_id": "  abc456  "},
            blocking=True,
        )
        mock_add.assert_awaited_once_with("ABC456")


async def test_add_tracking_coerces_int_to_str(
    hass: HomeAssistant, mock_bring_config_entry
) -> None:
    """Pure-digit tracking IDs are coerced to str when HA's template renderer
    produces an int via literal_eval (regression: vol.All(str, ...) rejected ints)."""
    client = _mock_client()
    with patch("custom_components.nordic_parcel._create_client", return_value=client):
        await hass.config_entries.async_setup(mock_bring_config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = mock_bring_config_entry.runtime_data
    with patch.object(coordinator, "add_tracking", new_callable=AsyncMock) as mock_add:
        await hass.services.async_call(
            DOMAIN,
            "add_tracking",
            {"tracking_id": 70727320765017543},
            blocking=True,
        )
        mock_add.assert_awaited_once_with("70727320765017543")


async def test_add_tracking_with_carrier_filter(hass: HomeAssistant) -> None:
    """Test add_tracking filters by carrier when specified."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.nordic_parcel.const import CONF_API_KEY, CONF_API_UID, CONF_CARRIER

    bring_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bring",
        data={CONF_CARRIER: Carrier.BRING, CONF_API_UID: "a@b.com", CONF_API_KEY: "k1"},
        unique_id="bring_filter_test",
    )
    postnord_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Postnord",
        data={CONF_CARRIER: Carrier.POSTNORD, CONF_API_KEY: "k2"},
        unique_id="postnord_filter_test",
    )
    bring_entry.add_to_hass(hass)
    postnord_entry.add_to_hass(hass)

    bring_client = _mock_client(Carrier.BRING)
    postnord_client = _mock_client(Carrier.POSTNORD)

    with patch(
        "custom_components.nordic_parcel._create_client",
        side_effect=[bring_client, postnord_client],
    ):
        # Setting up the first entry triggers domain setup which loads both
        await hass.config_entries.async_setup(bring_entry.entry_id)
        await hass.async_block_till_done()

    postnord_coordinator = postnord_entry.runtime_data
    with patch.object(postnord_coordinator, "add_tracking", new_callable=AsyncMock) as mock_add:
        await hass.services.async_call(
            DOMAIN,
            "add_tracking",
            {"tracking_id": "PN123", "carrier": Carrier.POSTNORD},
            blocking=True,
        )
        mock_add.assert_awaited_once_with("PN123")


async def test_add_tracking_probes_carriers_when_ambiguous(hass: HomeAssistant) -> None:
    """With multiple carriers and no filter, the ID goes to the one that resolves it."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.nordic_parcel.api import Shipment
    from custom_components.nordic_parcel.const import CONF_API_KEY, CONF_API_UID, CONF_CARRIER

    bring_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bring",
        data={CONF_CARRIER: Carrier.BRING, CONF_API_UID: "a@b.com", CONF_API_KEY: "k1"},
        unique_id="bring_probe_test",
    )
    postnord_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Postnord",
        data={CONF_CARRIER: Carrier.POSTNORD, CONF_API_KEY: "k2"},
        unique_id="postnord_probe_test",
    )
    bring_entry.add_to_hass(hass)
    postnord_entry.add_to_hass(hass)

    from custom_components.nordic_parcel.api import CarrierNotFoundError

    bring_client = _mock_client(Carrier.BRING)
    bring_client.track_shipment.side_effect = CarrierNotFoundError("nope")
    postnord_client = _mock_client(Carrier.POSTNORD)
    postnord_client.track_shipment.return_value = [
        Shipment(tracking_id="PN999", carrier=Carrier.POSTNORD)
    ]

    with patch(
        "custom_components.nordic_parcel._create_client",
        side_effect=[bring_client, postnord_client],
    ):
        await hass.config_entries.async_setup(bring_entry.entry_id)
        await hass.async_block_till_done()

    bring_coordinator = bring_entry.runtime_data
    postnord_coordinator = postnord_entry.runtime_data
    with (
        patch.object(bring_coordinator, "add_tracking", new_callable=AsyncMock) as bring_add,
        patch.object(postnord_coordinator, "add_tracking", new_callable=AsyncMock) as pn_add,
    ):
        await hass.services.async_call(
            DOMAIN, "add_tracking", {"tracking_id": "PN999"}, blocking=True
        )
        bring_add.assert_not_awaited()
        pn_add.assert_awaited_once_with("PN999")


async def test_add_tracking_ambiguous_none_recognizes_raises(hass: HomeAssistant) -> None:
    """With multiple carriers and no filter, an unrecognized ID raises rather than silently adding."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.nordic_parcel.api import CarrierNotFoundError
    from custom_components.nordic_parcel.const import CONF_API_KEY, CONF_API_UID, CONF_CARRIER

    bring_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bring",
        data={CONF_CARRIER: Carrier.BRING, CONF_API_UID: "a@b.com", CONF_API_KEY: "k1"},
        unique_id="bring_probe_none",
    )
    postnord_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Postnord",
        data={CONF_CARRIER: Carrier.POSTNORD, CONF_API_KEY: "k2"},
        unique_id="postnord_probe_none",
    )
    bring_entry.add_to_hass(hass)
    postnord_entry.add_to_hass(hass)

    bring_client = _mock_client(Carrier.BRING)
    bring_client.track_shipment.side_effect = CarrierNotFoundError("nope")
    postnord_client = _mock_client(Carrier.POSTNORD)
    postnord_client.track_shipment.side_effect = CarrierNotFoundError("nope")

    with patch(
        "custom_components.nordic_parcel._create_client",
        side_effect=[bring_client, postnord_client],
    ):
        await hass.config_entries.async_setup(bring_entry.entry_id)
        await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "add_tracking", {"tracking_id": "UNKNOWN1"}, blocking=True
        )


async def test_add_tracking_no_matching_carrier(
    hass: HomeAssistant, mock_bring_config_entry
) -> None:
    """Test add_tracking raises error when no carrier matches."""
    client = _mock_client(Carrier.BRING)
    with patch("custom_components.nordic_parcel._create_client", return_value=client):
        await hass.config_entries.async_setup(mock_bring_config_entry.entry_id)
        await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "add_tracking",
            {"tracking_id": "TEST123", "carrier": Carrier.HELTHJEM},
            blocking=True,
        )


async def test_remove_tracking_service(hass: HomeAssistant, mock_bring_config_entry) -> None:
    """Test remove_tracking service calls coordinator.remove_tracking."""
    client = _mock_client()
    with patch("custom_components.nordic_parcel._create_client", return_value=client):
        await hass.config_entries.async_setup(mock_bring_config_entry.entry_id)
        await hass.async_block_till_done()

    # Add a tracking ID to the coordinator's manual list
    coordinator = mock_bring_config_entry.runtime_data
    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {"TRACK001": {"added": "2026-04-13T00:00:00+00:00"}},
        },
    )

    with patch.object(coordinator, "remove_tracking", new_callable=AsyncMock) as mock_remove:
        await hass.services.async_call(
            DOMAIN,
            "remove_tracking",
            {"tracking_id": "track001"},
            blocking=True,
        )
        mock_remove.assert_awaited_once_with("TRACK001")


async def test_remove_tracking_not_found(hass: HomeAssistant, mock_bring_config_entry) -> None:
    """Test remove_tracking raises error when tracking ID not found."""
    client = _mock_client()
    with patch("custom_components.nordic_parcel._create_client", return_value=client):
        await hass.config_entries.async_setup(mock_bring_config_entry.entry_id)
        await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "remove_tracking",
            {"tracking_id": "DOESNOTEXIST"},
            blocking=True,
        )
