"""Tests for the Bring API client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.nordic_parcel.api import (
    CarrierApiError,
    CarrierAuthError,
    CarrierNotFoundError,
    CarrierRateLimitError,
)
from custom_components.nordic_parcel.api.bring import BringApiClient, _map_status, _parse_event
from custom_components.nordic_parcel.const import Carrier, ShipmentStatus
from tests.conftest import BRING_TRACKING_RESPONSE


def _mock_response(status=200, payload=None, exception=None):
    """Create a mock aiohttp response."""
    if exception:
        return exception
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=payload or {})
    return resp


@pytest.fixture
def bring_client():
    """Create a BringApiClient with a mock session."""
    session = MagicMock()
    client = BringApiClient(session, "test@example.com", "test-key")
    return client, session


class TestAuthenticate:
    """Tests for BringApiClient.authenticate()."""

    async def test_authenticate_success(self, bring_client):
        client, session = bring_client
        session.get = AsyncMock(return_value=_mock_response(status=200))
        assert await client.authenticate() is True

    async def test_authenticate_success_on_404_body(self, bring_client):
        """A 200 with not-found body still means auth is OK."""
        client, session = bring_client
        session.get = AsyncMock(
            return_value=_mock_response(status=200, payload={"consignmentSet": []})
        )
        assert await client.authenticate() is True

    async def test_authenticate_failure_401(self, bring_client):
        client, session = bring_client
        session.get = AsyncMock(return_value=_mock_response(status=401))
        assert await client.authenticate() is False

    async def test_authenticate_failure_403(self, bring_client):
        client, session = bring_client
        session.get = AsyncMock(return_value=_mock_response(status=403))
        assert await client.authenticate() is False

    async def test_authenticate_connection_error(self, bring_client):
        client, session = bring_client
        import aiohttp

        session.get = AsyncMock(side_effect=aiohttp.ClientError("Connection refused"))
        with pytest.raises(CarrierApiError, match="Could not connect"):
            await client.authenticate()


class TestTrackShipment:
    """Tests for BringApiClient.track_shipment()."""

    async def test_track_shipment_success(self, bring_client):
        client, session = bring_client
        session.get = AsyncMock(return_value=_mock_response(payload=BRING_TRACKING_RESPONSE))
        shipments = await client.track_shipment("370000000000123456")

        assert len(shipments) == 1
        shipment = shipments[0]
        assert shipment.tracking_id == "370000000000123456"
        assert shipment.carrier == Carrier.BRING
        assert shipment.status == ShipmentStatus.IN_TRANSIT
        assert shipment.sender == "Test Sender AS"
        assert shipment.recipient == "Test Recipient"
        assert shipment.estimated_delivery is not None
        assert len(shipment.events) == 1
        assert shipment.events[0].description == "Parcel received by Bring"
        assert shipment.events[0].location == "Oslo, Norway"

    async def test_track_shipment_invalid_json_raises_api_error(self, bring_client):
        client, session = bring_client
        resp = MagicMock()
        resp.status = 200
        resp.json = AsyncMock(side_effect=ValueError("not json"))
        session.get = AsyncMock(return_value=resp)
        with pytest.raises(CarrierApiError):
            await client.track_shipment("370000000000123456")

    async def test_track_shipment_skips_malformed_event(self, bring_client):
        client, session = bring_client
        payload = {
            "consignmentSet": [
                {
                    "senderName": "Sender",
                    "packageSet": [
                        {
                            "packageNumber": "PKG1",
                            "eventSet": [
                                {"description": "no timestamp"},
                                {
                                    "dateIso": "2026-04-13T10:30:00+02:00",
                                    "status": "IN_TRANSIT",
                                    "description": "good",
                                },
                            ],
                        }
                    ],
                }
            ]
        }
        session.get = AsyncMock(return_value=_mock_response(payload=payload))
        shipments = await client.track_shipment("PKG1")
        assert len(shipments) == 1
        # Only the well-formed event survives; parsing does not crash.
        assert len(shipments[0].events) == 1

    async def test_parse_event_naive_timestamp_made_aware(self):
        """A timestamp without a UTC offset must be returned timezone-aware."""
        event = _parse_event(
            {
                "dateIso": "2026-04-13T10:30:00",
                "status": "IN_TRANSIT",
                "description": "No offset",
            }
        )
        assert event.timestamp.tzinfo is not None

    async def test_track_shipment_not_found_empty_consignment_set(self, bring_client):
        client, session = bring_client
        session.get = AsyncMock(return_value=_mock_response(payload={"consignmentSet": []}))
        with pytest.raises(CarrierNotFoundError):
            await client.track_shipment("NONEXISTENT")

    async def test_track_shipment_not_found_error_key(self, bring_client):
        client, session = bring_client
        session.get = AsyncMock(
            return_value=_mock_response(
                payload={"consignmentSet": [{"error": {"message": "No data found"}}]}
            )
        )
        with pytest.raises(CarrierNotFoundError, match="No data found"):
            await client.track_shipment("BADID")

    async def test_track_shipment_auth_error_401(self, bring_client):
        client, session = bring_client
        session.get = AsyncMock(return_value=_mock_response(status=401))
        with pytest.raises(CarrierAuthError):
            await client.track_shipment("370000000000123456")

    async def test_track_shipment_auth_error_403(self, bring_client):
        client, session = bring_client
        session.get = AsyncMock(return_value=_mock_response(status=403))
        with pytest.raises(CarrierAuthError):
            await client.track_shipment("370000000000123456")

    async def test_track_shipment_rate_limit(self, bring_client):
        client, session = bring_client
        session.get = AsyncMock(return_value=_mock_response(status=429))
        with pytest.raises(CarrierRateLimitError):
            await client.track_shipment("370000000000123456")

    async def test_track_shipment_connection_error(self, bring_client):
        client, session = bring_client
        import aiohttp

        session.get = AsyncMock(side_effect=aiohttp.ClientError("timeout"))
        with pytest.raises(CarrierApiError, match="Connection error"):
            await client.track_shipment("370000000000123456")

    async def test_track_shipment_server_error(self, bring_client):
        client, session = bring_client
        session.get = AsyncMock(return_value=_mock_response(status=500))
        with pytest.raises(CarrierApiError, match="status 500"):
            await client.track_shipment("370000000000123456")


class TestStatusMapping:
    """Tests for Bring status mapping."""

    @pytest.mark.parametrize(
        ("bring_status", "expected"),
        [
            ("IN_TRANSIT", ShipmentStatus.IN_TRANSIT),
            ("DELIVERED", ShipmentStatus.DELIVERED),
            ("PRE_NOTIFIED", ShipmentStatus.PRE_TRANSIT),
            ("INFORMATION_RECEIVED", ShipmentStatus.PRE_TRANSIT),
            ("TRANSPORT_TO_RECIPIENT", ShipmentStatus.OUT_FOR_DELIVERY),
            ("READY_FOR_PICKUP", ShipmentStatus.READY_FOR_PICKUP),
            ("RETURNED", ShipmentStatus.RETURNED),
            ("DEVIATION", ShipmentStatus.FAILED),
            ("TERMINAL", ShipmentStatus.IN_TRANSIT),
            ("CUSTOMS", ShipmentStatus.CUSTOMS),
        ],
    )
    def test_known_statuses(self, bring_status, expected):
        assert _map_status(bring_status) == expected

    def test_unknown_status(self):
        assert _map_status("COMPLETELY_MADE_UP") == ShipmentStatus.UNKNOWN

    def test_case_insensitive(self):
        assert _map_status("in_transit") == ShipmentStatus.IN_TRANSIT
        assert _map_status("Delivered") == ShipmentStatus.DELIVERED

    def test_empty_string(self):
        assert _map_status("") == ShipmentStatus.UNKNOWN


class TestCarrierProperty:
    """Tests for BringApiClient.carrier property."""

    def test_carrier_is_bring(self, bring_client):
        client, _ = bring_client
        assert client.carrier == Carrier.BRING


class TestRobustness:
    """Tests for error statuses, malformed payloads and connection handling."""

    @pytest.mark.parametrize("status", [429, 500, 503])
    async def test_authenticate_unverifiable_status_raises(self, bring_client, status):
        client, session = bring_client
        session.get = AsyncMock(return_value=_mock_response(status=status))
        with pytest.raises(CarrierApiError):
            await client.authenticate()

    async def test_authenticate_releases_response(self, bring_client):
        client, session = bring_client
        resp = _mock_response(status=404)
        session.get = AsyncMock(return_value=resp)
        assert await client.authenticate() is True
        resp.release.assert_called_once()

    async def test_track_shipment_404_is_not_found(self, bring_client):
        client, session = bring_client
        resp = _mock_response(status=404)
        session.get = AsyncMock(return_value=resp)
        with pytest.raises(CarrierNotFoundError):
            await client.track_shipment("UNKNOWN1")
        resp.release.assert_called_once()

    async def test_track_shipment_body_timeout_raises_api_error(self, bring_client):
        client, session = bring_client
        resp = _mock_response()
        resp.json = AsyncMock(side_effect=TimeoutError)
        session.get = AsyncMock(return_value=resp)
        with pytest.raises(CarrierApiError):
            await client.track_shipment("TRACK001")

    async def test_track_shipment_skips_null_fields(self, bring_client):
        client, session = bring_client
        good = {"dateIso": "2026-04-13T10:30:00+02:00", "status": "DELIVERED"}
        payload = {
            "consignmentSet": [
                {
                    "packageSet": [
                        {
                            "packageNumber": "PKG1",
                            "eventSet": [{"dateIso": None, "status": "IN_TRANSIT"}, good],
                        },
                        {
                            "packageNumber": "PKG2",
                            "eventSet": [{"dateIso": good["dateIso"], "status": None}],
                        },
                    ]
                }
            ]
        }
        session.get = AsyncMock(return_value=_mock_response(payload=payload))
        first, second = await client.track_shipment("CONSIGNMENT")
        assert first.status == ShipmentStatus.DELIVERED
        assert second.status == ShipmentStatus.UNKNOWN
