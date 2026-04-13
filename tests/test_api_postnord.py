"""Tests for the Postnord API client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.nordic_parcel.api import (
    CarrierApiError,
    CarrierAuthError,
    CarrierNotFoundError,
    CarrierRateLimitError,
)
from custom_components.nordic_parcel.api.postnord import (
    PostnordApiClient,
    _map_status,
)
from custom_components.nordic_parcel.const import Carrier, ShipmentStatus
from tests.conftest import POSTNORD_TRACKING_RESPONSE


def _mock_response(status=200, payload=None):
    """Create a mock aiohttp response."""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=payload or {})
    return resp


@pytest.fixture
def postnord_client():
    """Create a PostnordApiClient with a mock session."""
    session = MagicMock()
    client = PostnordApiClient(session, "test-postnord-key")
    return client, session


class TestAuthenticate:
    """Tests for PostnordApiClient.authenticate()."""

    async def test_authenticate_success(self, postnord_client):
        client, session = postnord_client
        session.get = AsyncMock(return_value=_mock_response(status=200))
        assert await client.authenticate() is True

    async def test_authenticate_failure_401(self, postnord_client):
        client, session = postnord_client
        session.get = AsyncMock(return_value=_mock_response(status=401))
        assert await client.authenticate() is False

    async def test_authenticate_failure_403(self, postnord_client):
        client, session = postnord_client
        session.get = AsyncMock(return_value=_mock_response(status=403))
        assert await client.authenticate() is False

    async def test_authenticate_connection_error(self, postnord_client):
        client, session = postnord_client
        import aiohttp

        session.get = AsyncMock(side_effect=aiohttp.ClientError("Connection refused"))
        with pytest.raises(CarrierApiError, match="Could not connect"):
            await client.authenticate()


class TestTrackShipment:
    """Tests for PostnordApiClient.track_shipment()."""

    async def test_track_shipment_success(self, postnord_client):
        client, session = postnord_client
        session.get = AsyncMock(return_value=_mock_response(payload=POSTNORD_TRACKING_RESPONSE))
        shipments = await client.track_shipment("00340000000000000001")

        assert len(shipments) == 1
        shipment = shipments[0]
        assert shipment.tracking_id == "00340000000000000001"
        assert shipment.carrier == Carrier.POSTNORD
        assert shipment.status == ShipmentStatus.IN_TRANSIT
        assert shipment.sender == "PostNord Sender AB"
        assert shipment.recipient is None
        assert shipment.estimated_delivery is not None
        assert len(shipment.events) == 1
        assert shipment.events[0].description == "In transit"
        assert shipment.events[0].location == "Stockholm"

    async def test_track_shipment_not_found(self, postnord_client):
        client, session = postnord_client
        session.get = AsyncMock(
            return_value=_mock_response(payload={"TrackingInformationResponse": {"shipments": []}})
        )
        with pytest.raises(CarrierNotFoundError):
            await client.track_shipment("NONEXISTENT")

    async def test_track_shipment_auth_error_401(self, postnord_client):
        client, session = postnord_client
        session.get = AsyncMock(return_value=_mock_response(status=401))
        with pytest.raises(CarrierAuthError):
            await client.track_shipment("00340000000000000001")

    async def test_track_shipment_auth_error_403(self, postnord_client):
        client, session = postnord_client
        session.get = AsyncMock(return_value=_mock_response(status=403))
        with pytest.raises(CarrierAuthError):
            await client.track_shipment("00340000000000000001")

    async def test_track_shipment_rate_limit(self, postnord_client):
        client, session = postnord_client
        session.get = AsyncMock(return_value=_mock_response(status=429))
        with pytest.raises(CarrierRateLimitError):
            await client.track_shipment("00340000000000000001")

    async def test_track_shipment_connection_error(self, postnord_client):
        client, session = postnord_client
        import aiohttp

        session.get = AsyncMock(side_effect=aiohttp.ClientError("timeout"))
        with pytest.raises(CarrierApiError, match="Connection error"):
            await client.track_shipment("00340000000000000001")

    async def test_track_shipment_server_error(self, postnord_client):
        client, session = postnord_client
        session.get = AsyncMock(return_value=_mock_response(status=500))
        with pytest.raises(CarrierApiError, match="status 500"):
            await client.track_shipment("00340000000000000001")


class TestGetShipments:
    """Tests for PostnordApiClient.get_shipments()."""

    async def test_get_shipments_returns_empty(self, postnord_client):
        client, _ = postnord_client
        result = await client.get_shipments()
        assert result == []


class TestStatusMapping:
    """Tests for Postnord status mapping."""

    @pytest.mark.parametrize(
        ("postnord_status", "expected"),
        [
            ("EN_ROUTE", ShipmentStatus.IN_TRANSIT),
            ("IN_TRANSIT", ShipmentStatus.IN_TRANSIT),
            ("INFORMED", ShipmentStatus.PRE_TRANSIT),
            ("INFORMATION_RECEIVED", ShipmentStatus.PRE_TRANSIT),
            ("AVAILABLE_FOR_DELIVERY", ShipmentStatus.READY_FOR_PICKUP),
            ("READY_FOR_PICKUP", ShipmentStatus.READY_FOR_PICKUP),
            ("DELIVERED", ShipmentStatus.DELIVERED),
            ("DELIVERY_IMPOSSIBLE", ShipmentStatus.FAILED),
            ("RETURNED", ShipmentStatus.RETURNED),
            ("RETURNING", ShipmentStatus.RETURNED),
            ("OUT_FOR_DELIVERY", ShipmentStatus.OUT_FOR_DELIVERY),
            ("CUSTOMS", ShipmentStatus.IN_TRANSIT),
        ],
    )
    def test_known_statuses(self, postnord_status, expected):
        assert _map_status(postnord_status) == expected

    def test_unknown_status(self):
        assert _map_status("COMPLETELY_MADE_UP") == ShipmentStatus.UNKNOWN

    def test_case_insensitive(self):
        assert _map_status("en_route") == ShipmentStatus.IN_TRANSIT
        assert _map_status("Delivered") == ShipmentStatus.DELIVERED

    def test_empty_string(self):
        assert _map_status("") == ShipmentStatus.UNKNOWN


class TestCarrierProperty:
    """Tests for PostnordApiClient.carrier property."""

    def test_carrier_is_postnord(self, postnord_client):
        client, _ = postnord_client
        assert client.carrier == Carrier.POSTNORD
