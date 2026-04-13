"""Tests for the Helthjem API client."""

from __future__ import annotations

import urllib.parse

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.nordic_parcel.api import (
    CarrierApiError,
    CarrierAuthError,
    CarrierNotFoundError,
    CarrierRateLimitError,
)
from custom_components.nordic_parcel.api.helthjem import (
    TOKEN_URL,
    TRACKING_URL,
    HelthjemApiClient,
    _map_event_code,
)
from custom_components.nordic_parcel.const import Carrier, ShipmentStatus
from tests.conftest import HELTHJEM_TOKEN_RESPONSE, HELTHJEM_TRACKING_RESPONSE

TRACKING_ID = "HJ-TEST-12345"
EXPECTED_TRACK_URL = f"{TRACKING_URL}/{urllib.parse.quote(TRACKING_ID, safe='')}/EN/false"


@pytest.fixture
async def helthjem_client():
    """Create a HelthjemApiClient with a real session, cleaned up after test."""
    session = aiohttp.ClientSession()
    client = HelthjemApiClient(session, "test-client-id", "test-client-secret")
    yield client
    await session.close()


def _mock_token(m):
    """Helper to register a successful token response."""
    m.post(TOKEN_URL, payload=HELTHJEM_TOKEN_RESPONSE)


class TestAuthenticate:
    """Tests for HelthjemApiClient.authenticate()."""

    async def test_authenticate_success(self, helthjem_client):
        with aioresponses() as m:
            _mock_token(m)
            assert await helthjem_client.authenticate() is True

    async def test_authenticate_failure_401(self, helthjem_client):
        with aioresponses() as m:
            m.post(TOKEN_URL, status=401)
            assert await helthjem_client.authenticate() is False

    async def test_authenticate_failure_403(self, helthjem_client):
        with aioresponses() as m:
            m.post(TOKEN_URL, status=403)
            assert await helthjem_client.authenticate() is False

    async def test_authenticate_connection_error(self, helthjem_client):
        with aioresponses() as m:
            m.post(
                TOKEN_URL,
                exception=aiohttp.ClientConnectionError("Connection refused"),
            )
            with pytest.raises(CarrierApiError, match="Token request failed"):
                await helthjem_client.authenticate()


class TestTrackShipment:
    """Tests for HelthjemApiClient.track_shipment()."""

    async def test_track_shipment_success(self, helthjem_client):
        with aioresponses() as m:
            _mock_token(m)
            m.get(EXPECTED_TRACK_URL, payload=HELTHJEM_TRACKING_RESPONSE)
            shipments = await helthjem_client.track_shipment(TRACKING_ID)

        assert len(shipments) == 1
        shipment = shipments[0]
        assert shipment.tracking_id == TRACKING_ID
        assert shipment.carrier == Carrier.HELTHJEM
        assert shipment.status == ShipmentStatus.IN_TRANSIT
        assert shipment.sender == "Helthjem Shop"
        assert shipment.recipient is None
        assert len(shipment.events) == 1
        assert shipment.events[0].description == "In transit"
        assert shipment.events[0].location == "Trondheim"
        assert shipment.events[0].status == ShipmentStatus.IN_TRANSIT

    async def test_track_shipment_not_found_404(self, helthjem_client):
        with aioresponses() as m:
            _mock_token(m)
            m.get(EXPECTED_TRACK_URL, status=404)
            with pytest.raises(CarrierNotFoundError):
                await helthjem_client.track_shipment(TRACKING_ID)

    async def test_track_shipment_auth_error_after_retry(self, helthjem_client):
        """If both attempts return 401/403, raises CarrierAuthError."""
        with aioresponses() as m:
            _mock_token(m)
            m.get(EXPECTED_TRACK_URL, status=401)
            _mock_token(m)
            m.get(EXPECTED_TRACK_URL, status=401)
            with pytest.raises(CarrierAuthError):
                await helthjem_client.track_shipment(TRACKING_ID)

    async def test_track_shipment_rate_limit(self, helthjem_client):
        with aioresponses() as m:
            _mock_token(m)
            m.get(EXPECTED_TRACK_URL, status=429)
            with pytest.raises(CarrierRateLimitError):
                await helthjem_client.track_shipment(TRACKING_ID)

    async def test_track_shipment_connection_error(self, helthjem_client):
        with aioresponses() as m:
            _mock_token(m)
            m.get(
                EXPECTED_TRACK_URL,
                exception=aiohttp.ClientConnectionError("timeout"),
            )
            with pytest.raises(CarrierApiError, match="Connection error"):
                await helthjem_client.track_shipment(TRACKING_ID)

    async def test_track_shipment_server_error(self, helthjem_client):
        with aioresponses() as m:
            _mock_token(m)
            m.get(EXPECTED_TRACK_URL, status=500)
            with pytest.raises(CarrierApiError, match="status 500"):
                await helthjem_client.track_shipment(TRACKING_ID)


class TestTokenRefreshOn401:
    """Tests for Helthjem token refresh behavior on 401."""

    async def test_retries_with_fresh_token_on_401(self, helthjem_client):
        """On first 401, clears token, gets new one, retries successfully."""
        with aioresponses() as m:
            _mock_token(m)
            m.get(EXPECTED_TRACK_URL, status=401)
            _mock_token(m)
            m.get(EXPECTED_TRACK_URL, payload=HELTHJEM_TRACKING_RESPONSE)
            shipments = await helthjem_client.track_shipment(TRACKING_ID)

        assert len(shipments) == 1
        assert shipments[0].tracking_id == TRACKING_ID

    async def test_token_cached_after_success(self, helthjem_client):
        """Token is reused on second call (no second token request needed)."""
        with aioresponses() as m:
            _mock_token(m)
            m.get(EXPECTED_TRACK_URL, payload=HELTHJEM_TRACKING_RESPONSE)
            m.get(EXPECTED_TRACK_URL, payload=HELTHJEM_TRACKING_RESPONSE)

            await helthjem_client.track_shipment(TRACKING_ID)
            shipments = await helthjem_client.track_shipment(TRACKING_ID)
            assert len(shipments) == 1


class TestUrlEncoding:
    """Tests for URL encoding of tracking IDs with special characters."""

    async def test_tracking_id_with_slash(self, helthjem_client):
        """Tracking ID with / should be URL-encoded."""
        tracking_id = "HJ/2026/123"
        encoded_id = urllib.parse.quote(tracking_id, safe="")
        expected_url = f"{TRACKING_URL}/{encoded_id}/EN/false"
        with aioresponses() as m:
            _mock_token(m)
            m.get(expected_url, payload=HELTHJEM_TRACKING_RESPONSE)
            shipments = await helthjem_client.track_shipment(tracking_id)
        assert len(shipments) == 1
        assert shipments[0].tracking_id == tracking_id

    async def test_tracking_id_with_special_chars(self, helthjem_client):
        """Tracking ID with spaces and special chars should be URL-encoded."""
        tracking_id = "HJ 123+456"
        encoded_id = urllib.parse.quote(tracking_id, safe="")
        expected_url = f"{TRACKING_URL}/{encoded_id}/EN/false"
        with aioresponses() as m:
            _mock_token(m)
            m.get(expected_url, payload=HELTHJEM_TRACKING_RESPONSE)
            shipments = await helthjem_client.track_shipment(tracking_id)
        assert len(shipments) == 1


class TestGetShipments:
    """Tests for HelthjemApiClient.get_shipments()."""

    async def test_get_shipments_returns_empty(self, helthjem_client):
        result = await helthjem_client.get_shipments()
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

    async def test_carrier_is_helthjem(self, helthjem_client):
        assert helthjem_client.carrier == Carrier.HELTHJEM
