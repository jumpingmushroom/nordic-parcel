"""Tests for the Helthjem API client."""

from __future__ import annotations

import urllib.parse
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.nordic_parcel.api import (
    CarrierApiError,
    CarrierAuthError,
    CarrierNotFoundError,
    CarrierRateLimitError,
)
from custom_components.nordic_parcel.api.helthjem import (
    HelthjemApiClient,
    _map_event_code,
)
from custom_components.nordic_parcel.const import Carrier, ShipmentStatus
from tests.conftest import HELTHJEM_TOKEN_RESPONSE, HELTHJEM_TRACKING_RESPONSE


def _mock_response(status=200, payload=None):
    """Create a mock aiohttp response."""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=payload or {})
    return resp


@pytest.fixture
def helthjem_client():
    """Create a HelthjemApiClient with a mock session."""
    session = MagicMock()
    client = HelthjemApiClient(session, "test-client-id", "test-client-secret")
    return client, session


def _setup_token_then_track(session, track_status=200, track_payload=None):
    """Set up session.post for token and session.get for tracking."""
    session.post = AsyncMock(return_value=_mock_response(payload=HELTHJEM_TOKEN_RESPONSE))
    session.get = AsyncMock(return_value=_mock_response(status=track_status, payload=track_payload))


class TestAuthenticate:
    """Tests for HelthjemApiClient.authenticate()."""

    async def test_authenticate_success(self, helthjem_client):
        client, session = helthjem_client
        session.post = AsyncMock(return_value=_mock_response(payload=HELTHJEM_TOKEN_RESPONSE))
        assert await client.authenticate() is True

    async def test_authenticate_failure_401(self, helthjem_client):
        client, session = helthjem_client
        session.post = AsyncMock(return_value=_mock_response(status=401))
        assert await client.authenticate() is False

    async def test_authenticate_failure_403(self, helthjem_client):
        client, session = helthjem_client
        session.post = AsyncMock(return_value=_mock_response(status=403))
        assert await client.authenticate() is False

    async def test_authenticate_connection_error(self, helthjem_client):
        client, session = helthjem_client
        import aiohttp

        session.post = AsyncMock(side_effect=aiohttp.ClientError("Connection refused"))
        with pytest.raises(CarrierApiError, match="Token request failed"):
            await client.authenticate()


class TestTrackShipment:
    """Tests for HelthjemApiClient.track_shipment()."""

    async def test_track_shipment_success(self, helthjem_client):
        client, session = helthjem_client
        _setup_token_then_track(session, track_payload=HELTHJEM_TRACKING_RESPONSE)
        shipments = await client.track_shipment("HJ-TEST-12345")

        assert len(shipments) == 1
        shipment = shipments[0]
        assert shipment.tracking_id == "HJ-TEST-12345"
        assert shipment.carrier == Carrier.HELTHJEM
        assert shipment.status == ShipmentStatus.IN_TRANSIT
        assert shipment.sender == "Helthjem Shop"
        assert shipment.recipient is None
        assert len(shipment.events) == 1
        assert shipment.events[0].description == "In transit"
        assert shipment.events[0].location == "Trondheim"

    async def test_track_shipment_not_found_404(self, helthjem_client):
        client, session = helthjem_client
        _setup_token_then_track(session, track_status=404)
        with pytest.raises(CarrierNotFoundError):
            await client.track_shipment("NONEXISTENT")

    async def test_track_shipment_auth_error_after_retry(self, helthjem_client):
        """If both attempts return 401, raises CarrierAuthError."""
        client, session = helthjem_client
        session.post = AsyncMock(return_value=_mock_response(payload=HELTHJEM_TOKEN_RESPONSE))
        # Both tracking attempts return 401
        session.get = AsyncMock(return_value=_mock_response(status=401))
        with pytest.raises(CarrierAuthError):
            await client.track_shipment("HJ-TEST-12345")

    async def test_track_shipment_rate_limit(self, helthjem_client):
        client, session = helthjem_client
        _setup_token_then_track(session, track_status=429)
        with pytest.raises(CarrierRateLimitError):
            await client.track_shipment("HJ-TEST-12345")

    async def test_track_shipment_connection_error(self, helthjem_client):
        client, session = helthjem_client
        import aiohttp

        session.post = AsyncMock(return_value=_mock_response(payload=HELTHJEM_TOKEN_RESPONSE))
        session.get = AsyncMock(side_effect=aiohttp.ClientError("timeout"))
        with pytest.raises(CarrierApiError, match="Connection error"):
            await client.track_shipment("HJ-TEST-12345")

    async def test_track_shipment_server_error(self, helthjem_client):
        client, session = helthjem_client
        _setup_token_then_track(session, track_status=500)
        with pytest.raises(CarrierApiError, match="status 500"):
            await client.track_shipment("HJ-TEST-12345")


class TestTokenRefreshOn401:
    """Tests for Helthjem token refresh behavior on 401."""

    async def test_retries_with_fresh_token_on_401(self, helthjem_client):
        """On first 401, clears token, gets new one, retries successfully."""
        client, session = helthjem_client
        session.post = AsyncMock(return_value=_mock_response(payload=HELTHJEM_TOKEN_RESPONSE))
        # First call returns 401, retry returns success
        session.get = AsyncMock(
            side_effect=[
                _mock_response(status=401),
                _mock_response(payload=HELTHJEM_TRACKING_RESPONSE),
            ]
        )
        shipments = await client.track_shipment("HJ-TEST-12345")
        assert len(shipments) == 1

    async def test_token_cached_after_success(self, helthjem_client):
        """Token is reused on second call (only one token request)."""
        client, session = helthjem_client
        session.post = AsyncMock(return_value=_mock_response(payload=HELTHJEM_TOKEN_RESPONSE))
        session.get = AsyncMock(return_value=_mock_response(payload=HELTHJEM_TRACKING_RESPONSE))
        await client.track_shipment("HJ-TEST-12345")
        await client.track_shipment("HJ-TEST-12345")
        # Token requested only once
        assert session.post.call_count == 1


class TestUrlEncoding:
    """Tests for URL encoding of tracking IDs with special characters."""

    async def test_tracking_id_with_slash(self, helthjem_client):
        """Tracking ID with / should be URL-encoded in the URL."""
        client, session = helthjem_client
        _setup_token_then_track(session, track_payload=HELTHJEM_TRACKING_RESPONSE)
        await client.track_shipment("HJ/2026/123")
        # Verify the URL passed to session.get contains the encoded tracking ID
        call_url = session.get.call_args[0][0]
        assert "HJ/2026/123" not in call_url
        assert urllib.parse.quote("HJ/2026/123", safe="") in call_url

    async def test_tracking_id_with_special_chars(self, helthjem_client):
        """Tracking ID with spaces should be URL-encoded."""
        client, session = helthjem_client
        _setup_token_then_track(session, track_payload=HELTHJEM_TRACKING_RESPONSE)
        await client.track_shipment("HJ 123+456")
        call_url = session.get.call_args[0][0]
        assert urllib.parse.quote("HJ 123+456", safe="") in call_url


class TestGetShipments:
    """Tests for HelthjemApiClient.get_shipments()."""

    async def test_get_shipments_returns_empty(self, helthjem_client):
        client, _ = helthjem_client
        result = await client.get_shipments()
        assert result == []


class TestEventCodeMapping:
    """Tests for Helthjem event code mapping."""

    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            ("001", ShipmentStatus.PRE_TRANSIT),
            ("003", ShipmentStatus.IN_TRANSIT),
            ("013", ShipmentStatus.DELIVERED),
            ("060", ShipmentStatus.OUT_FOR_DELIVERY),
            ("028", ShipmentStatus.RETURNED),
            ("068", ShipmentStatus.FAILED),
            ("073", ShipmentStatus.READY_FOR_PICKUP),
            ("148", ShipmentStatus.IN_TRANSIT),
        ],
    )
    def test_known_event_codes(self, code, expected):
        assert _map_event_code(code) == expected

    def test_unknown_event_code(self):
        assert _map_event_code("999") == ShipmentStatus.UNKNOWN

    def test_empty_string(self):
        assert _map_event_code("") == ShipmentStatus.UNKNOWN


class TestCarrierProperty:
    """Tests for HelthjemApiClient.carrier property."""

    def test_carrier_is_helthjem(self, helthjem_client):
        client, _ = helthjem_client
        assert client.carrier == Carrier.HELTHJEM
