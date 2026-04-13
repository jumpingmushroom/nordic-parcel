"""Tests for the Bring API client."""

from __future__ import annotations

import re

import aiohttp
import pytest
from aioresponses import aioresponses

from tests.conftest import BRING_TRACKING_RESPONSE
from custom_components.nordic_parcel.api import (
    CarrierApiError,
    CarrierAuthError,
    CarrierNotFoundError,
    CarrierRateLimitError,
)
from custom_components.nordic_parcel.api.bring import BASE_URL, BringApiClient, _map_status
from custom_components.nordic_parcel.const import Carrier, ShipmentStatus

# Pattern that matches the Bring base URL with any query parameters
BRING_URL_PATTERN = re.compile(r"^https://api\.bring\.com/tracking/api/v2/tracking\.json")


@pytest.fixture
def bring_client():
    """Factory fixture that creates a BringApiClient with a real session."""

    async def _create():
        session = aiohttp.ClientSession()
        client = BringApiClient(session, "test@example.com", "test-key")
        return client, session

    return _create


class TestAuthenticate:
    """Tests for BringApiClient.authenticate()."""

    async def test_authenticate_success(self, bring_client):
        client, session = await bring_client()
        try:
            with aioresponses() as m:
                m.get(BRING_URL_PATTERN, status=200, payload={})
                result = await client.authenticate()
            assert result is True
        finally:
            await session.close()

    async def test_authenticate_success_on_404_body(self, bring_client):
        """A 200 with not-found body still means auth is OK."""
        client, session = await bring_client()
        try:
            with aioresponses() as m:
                m.get(BRING_URL_PATTERN, status=200, payload={"consignmentSet": []})
                result = await client.authenticate()
            assert result is True
        finally:
            await session.close()

    async def test_authenticate_failure_401(self, bring_client):
        client, session = await bring_client()
        try:
            with aioresponses() as m:
                m.get(BRING_URL_PATTERN, status=401)
                result = await client.authenticate()
            assert result is False
        finally:
            await session.close()

    async def test_authenticate_failure_403(self, bring_client):
        client, session = await bring_client()
        try:
            with aioresponses() as m:
                m.get(BRING_URL_PATTERN, status=403)
                result = await client.authenticate()
            assert result is False
        finally:
            await session.close()

    async def test_authenticate_connection_error(self, bring_client):
        client, session = await bring_client()
        try:
            with aioresponses() as m:
                m.get(
                    BRING_URL_PATTERN,
                    exception=aiohttp.ClientConnectionError("Connection refused"),
                )
                with pytest.raises(CarrierApiError, match="Could not connect"):
                    await client.authenticate()
        finally:
            await session.close()


class TestTrackShipment:
    """Tests for BringApiClient.track_shipment()."""

    async def test_track_shipment_success(self, bring_client):
        client, session = await bring_client()
        try:
            with aioresponses() as m:
                m.get(BRING_URL_PATTERN, payload=BRING_TRACKING_RESPONSE)
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
            assert shipment.events[0].status == ShipmentStatus.IN_TRANSIT
        finally:
            await session.close()

    async def test_track_shipment_not_found_empty_consignment_set(self, bring_client):
        client, session = await bring_client()
        try:
            with aioresponses() as m:
                m.get(BRING_URL_PATTERN, payload={"consignmentSet": []})
                with pytest.raises(CarrierNotFoundError):
                    await client.track_shipment("NONEXISTENT")
        finally:
            await session.close()

    async def test_track_shipment_not_found_error_key(self, bring_client):
        client, session = await bring_client()
        try:
            with aioresponses() as m:
                m.get(
                    BRING_URL_PATTERN,
                    payload={
                        "consignmentSet": [
                            {"error": {"message": "No data found"}}
                        ]
                    },
                )
                with pytest.raises(CarrierNotFoundError, match="No data found"):
                    await client.track_shipment("BADID")
        finally:
            await session.close()

    async def test_track_shipment_auth_error_401(self, bring_client):
        client, session = await bring_client()
        try:
            with aioresponses() as m:
                m.get(BRING_URL_PATTERN, status=401)
                with pytest.raises(CarrierAuthError):
                    await client.track_shipment("370000000000123456")
        finally:
            await session.close()

    async def test_track_shipment_auth_error_403(self, bring_client):
        client, session = await bring_client()
        try:
            with aioresponses() as m:
                m.get(BRING_URL_PATTERN, status=403)
                with pytest.raises(CarrierAuthError):
                    await client.track_shipment("370000000000123456")
        finally:
            await session.close()

    async def test_track_shipment_rate_limit(self, bring_client):
        client, session = await bring_client()
        try:
            with aioresponses() as m:
                m.get(BRING_URL_PATTERN, status=429)
                with pytest.raises(CarrierRateLimitError):
                    await client.track_shipment("370000000000123456")
        finally:
            await session.close()

    async def test_track_shipment_connection_error(self, bring_client):
        client, session = await bring_client()
        try:
            with aioresponses() as m:
                m.get(
                    BRING_URL_PATTERN,
                    exception=aiohttp.ClientConnectionError("timeout"),
                )
                with pytest.raises(CarrierApiError, match="Connection error"):
                    await client.track_shipment("370000000000123456")
        finally:
            await session.close()

    async def test_track_shipment_server_error(self, bring_client):
        client, session = await bring_client()
        try:
            with aioresponses() as m:
                m.get(BRING_URL_PATTERN, status=500)
                with pytest.raises(CarrierApiError, match="status 500"):
                    await client.track_shipment("370000000000123456")
        finally:
            await session.close()


class TestGetShipments:
    """Tests for BringApiClient.get_shipments()."""

    async def test_get_shipments_returns_empty(self, bring_client):
        client, session = await bring_client()
        try:
            result = await client.get_shipments()
            assert result == []
        finally:
            await session.close()


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
            ("CUSTOMS", ShipmentStatus.IN_TRANSIT),
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

    async def test_carrier_is_bring(self, bring_client):
        client, session = await bring_client()
        try:
            assert client.carrier == Carrier.BRING
        finally:
            await session.close()
