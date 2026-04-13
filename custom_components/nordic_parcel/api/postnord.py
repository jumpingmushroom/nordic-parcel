"""Postnord tracking API client."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import aiohttp

from ..const import Carrier, ShipmentStatus
from . import (
    CarrierApiError,
    CarrierAuthError,
    CarrierNotFoundError,
    CarrierRateLimitError,
    Shipment,
    TrackingEvent,
)

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://api2.postnord.com/rest/shipment/v5/trackandtrace/findByIdentifier.json"

# Postnord status strings -> normalized ShipmentStatus
_STATUS_MAP: dict[str, ShipmentStatus] = {
    "EN_ROUTE": ShipmentStatus.IN_TRANSIT,
    "IN_TRANSIT": ShipmentStatus.IN_TRANSIT,
    "INFORMED": ShipmentStatus.PRE_TRANSIT,
    "INFORMATION_RECEIVED": ShipmentStatus.PRE_TRANSIT,
    "AVAILABLE_FOR_DELIVERY": ShipmentStatus.READY_FOR_PICKUP,
    "READY_FOR_PICKUP": ShipmentStatus.READY_FOR_PICKUP,
    "DELIVERED": ShipmentStatus.DELIVERED,
    "DELIVERY_IMPOSSIBLE": ShipmentStatus.FAILED,
    "DELIVERY_REFUSED": ShipmentStatus.FAILED,
    "RETURNED": ShipmentStatus.RETURNED,
    "RETURNING": ShipmentStatus.RETURNED,
    "CUSTOMS": ShipmentStatus.IN_TRANSIT,
    "OUT_FOR_DELIVERY": ShipmentStatus.OUT_FOR_DELIVERY,
    "TRANSPORT_TO_RECIPIENT": ShipmentStatus.OUT_FOR_DELIVERY,
}


def _map_status(postnord_status: str) -> ShipmentStatus:
    """Map a Postnord status string to normalized ShipmentStatus."""
    return _STATUS_MAP.get(postnord_status.upper(), ShipmentStatus.UNKNOWN)


def _parse_event(event: dict) -> TrackingEvent:
    """Parse a Postnord event dict into a TrackingEvent."""
    # Postnord uses eventTime as ISO string
    timestamp_str = event.get("eventTime") or event.get("eventDate", "")
    try:
        timestamp = datetime.fromisoformat(timestamp_str)
    except ValueError:
        timestamp = datetime.now(timezone.utc)

    location_data = event.get("location", {})
    location = location_data.get("displayName")

    return TrackingEvent(
        timestamp=timestamp,
        description=event.get("eventDescription", event.get("status", "")),
        location=location,
        status=_map_status(event.get("status", "")),
    )


def _parse_shipment(shipment_data: dict) -> Shipment:
    """Parse a Postnord shipment response into a Shipment."""
    tracking_id = shipment_data.get("shipmentId", "")
    sender = None
    consignor = shipment_data.get("consignor")
    if consignor:
        sender = consignor.get("name")

    # Collect events from all items
    events: list[TrackingEvent] = []
    for item in shipment_data.get("items", []):
        for event in item.get("events", []):
            events.append(_parse_event(event))

    # Sort events newest-first
    events.sort(key=lambda e: e.timestamp, reverse=True)

    status = events[0].status if events else ShipmentStatus.UNKNOWN
    # Override with top-level status if available
    top_status = shipment_data.get("status")
    if top_status:
        mapped = _map_status(top_status)
        if mapped != ShipmentStatus.UNKNOWN:
            status = mapped

    estimated_delivery = None
    eta_str = shipment_data.get("estimatedTimeOfArrival")
    if eta_str:
        try:
            estimated_delivery = datetime.fromisoformat(eta_str)
        except ValueError:
            pass

    return Shipment(
        tracking_id=tracking_id,
        carrier=Carrier.POSTNORD,
        status=status,
        sender=sender,
        recipient=None,  # Postnord API doesn't expose recipient name
        estimated_delivery=estimated_delivery,
        events=events,
        raw_data=shipment_data,
    )


class PostnordApiClient:
    """Async client for the Postnord Tracking API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
    ) -> None:
        self._session = session
        self._api_key = api_key

    @property
    def carrier(self) -> Carrier:
        return Carrier.POSTNORD

    async def authenticate(self) -> bool:
        """Validate the API key by making a test request."""
        try:
            async with asyncio.timeout(10):
                resp = await self._session.get(
                    BASE_URL,
                    params={
                        "id": "TESTPACKAGE00000",
                        "locale": "en",
                        "apikey": self._api_key,
                    },
                )
            # 401/403 = bad key, anything else = key is valid
            if resp.status in (401, 403):
                return False
            return True
        except (aiohttp.ClientError, TimeoutError):
            raise CarrierApiError("Could not connect to Postnord API")

    async def get_shipments(self) -> list[Shipment]:
        """Postnord API doesn't support listing all shipments for an account.

        Returns an empty list. Users must add tracking numbers manually.
        """
        return []

    async def track_shipment(self, tracking_id: str) -> list[Shipment]:
        """Fetch tracking data for a single shipment."""
        try:
            async with asyncio.timeout(10):
                resp = await self._session.get(
                    BASE_URL,
                    params={
                        "id": tracking_id,
                        "locale": "en",
                        "apikey": self._api_key,
                    },
                )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CarrierApiError(f"Connection error: {err}") from err

        if resp.status in (401, 403):
            raise CarrierAuthError("Invalid Postnord API key")
        if resp.status == 429:
            raise CarrierRateLimitError("Postnord API rate limit exceeded")
        if resp.status != 200:
            raise CarrierApiError(f"Postnord API returned status {resp.status}")

        data = await resp.json()

        tracking_resp = data.get("TrackingInformationResponse", {})
        shipments = tracking_resp.get("shipments", [])

        if not shipments:
            raise CarrierNotFoundError(f"No shipment found for {tracking_id}")

        return [_parse_shipment(shipments[0])]

    async def close(self) -> None:
        """No-op — session lifecycle managed externally."""
