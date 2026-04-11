"""Bring (Posten Norge) tracking API client."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

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

BASE_URL = "https://api.bring.com/tracking/api/v2/tracking.json"

# Bring status codes -> normalized ShipmentStatus
_STATUS_MAP: dict[str, ShipmentStatus] = {
    "PRE_NOTIFIED": ShipmentStatus.PRE_TRANSIT,
    "INFORMATION_RECEIVED": ShipmentStatus.PRE_TRANSIT,
    "IN_TRANSIT": ShipmentStatus.IN_TRANSIT,
    "TRANSPORT_TO_RECIPIENT": ShipmentStatus.OUT_FOR_DELIVERY,
    "READY_FOR_PICKUP": ShipmentStatus.READY_FOR_PICKUP,
    "NOTIFICATION_SENT": ShipmentStatus.READY_FOR_PICKUP,
    "DELIVERED": ShipmentStatus.DELIVERED,
    "RETURNED": ShipmentStatus.RETURNED,
    "DEVIATION": ShipmentStatus.FAILED,
}


def _map_status(bring_status: str) -> ShipmentStatus:
    """Map a Bring status string to a normalized ShipmentStatus."""
    return _STATUS_MAP.get(bring_status.upper(), ShipmentStatus.UNKNOWN)


def _parse_event(event: dict) -> TrackingEvent:
    """Parse a single Bring event dict into a TrackingEvent."""
    timestamp = datetime.fromisoformat(event["dateIso"])
    location_parts = [event.get("city"), event.get("country")]
    location = ", ".join(p for p in location_parts if p) or None

    return TrackingEvent(
        timestamp=timestamp,
        description=event.get("description", ""),
        location=location,
        status=_map_status(event.get("status", "")),
    )


def _parse_consignment(consignment: dict) -> list[Shipment]:
    """Parse a Bring consignment into one Shipment per package."""
    shipments: list[Shipment] = []
    sender = consignment.get("senderName")
    recipient = consignment.get("recipientName")

    for package in consignment.get("packageSet", []):
        tracking_id = package.get("packageNumber", "")
        events = [_parse_event(e) for e in package.get("eventSet", [])]
        # Events are newest-first from Bring
        status = events[0].status if events else ShipmentStatus.UNKNOWN

        estimated_delivery = None
        date_str = package.get("dateOfEstimatedDelivery")
        if date_str:
            try:
                estimated_delivery = datetime.fromisoformat(date_str)
            except ValueError:
                pass

        shipments.append(
            Shipment(
                tracking_id=tracking_id,
                carrier=Carrier.BRING,
                status=status,
                sender=sender,
                recipient=recipient,
                estimated_delivery=estimated_delivery,
                events=events,
                raw_data=package,
            )
        )

    return shipments


class BringApiClient:
    """Async client for the Bring Tracking API v2."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_uid: str,
        api_key: str,
    ) -> None:
        self._session = session
        self._api_uid = api_uid
        self._api_key = api_key

    @property
    def carrier(self) -> Carrier:
        return Carrier.BRING

    def _headers(self) -> dict[str, str]:
        return {
            "X-Mybring-API-Uid": self._api_uid,
            "X-Mybring-API-Key": self._api_key,
            "X-Bring-Client-URL": "homeassistant-nordic-parcel",
            "Accept": "application/json",
        }

    async def authenticate(self) -> bool:
        """Validate credentials by making a test tracking request."""
        try:
            # Use a dummy tracking number — a 404 (not found) means auth is OK
            async with asyncio.timeout(10):
                resp = await self._session.get(
                    BASE_URL,
                    params={"q": "TESTPACKAGE00000"},
                    headers=self._headers(),
                )
            if resp.status == 401:
                return False
            if resp.status == 403:
                return False
            # 200 or 404-style responses in body mean auth succeeded
            return True
        except (aiohttp.ClientError, TimeoutError):
            raise CarrierApiError("Could not connect to Bring API")

    async def get_shipments(self) -> list[Shipment]:
        """Bring API doesn't support listing all shipments for an account.

        Returns an empty list. Users must add tracking numbers manually
        or rely on external automation.
        """
        return []

    async def track_shipment(self, tracking_id: str) -> Shipment:
        """Fetch tracking data for a single shipment."""
        try:
            async with asyncio.timeout(10):
                resp = await self._session.get(
                    BASE_URL,
                    params={"q": tracking_id, "lang": "en"},
                    headers=self._headers(),
                )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CarrierApiError(f"Connection error: {err}") from err

        if resp.status == 401 or resp.status == 403:
            raise CarrierAuthError("Invalid Bring API credentials")
        if resp.status == 429:
            raise CarrierRateLimitError("Bring API rate limit exceeded")
        if resp.status != 200:
            raise CarrierApiError(f"Bring API returned status {resp.status}")

        data = await resp.json()

        consignment_set = data.get("consignmentSet", [])
        if not consignment_set:
            raise CarrierNotFoundError(f"No shipment found for {tracking_id}")

        consignment = consignment_set[0]

        # Check for error response
        if "error" in consignment:
            error = consignment["error"]
            raise CarrierNotFoundError(
                error.get("message", f"Shipment {tracking_id} not found")
            )

        shipments = _parse_consignment(consignment)
        if not shipments:
            raise CarrierNotFoundError(f"No packages found for {tracking_id}")

        return shipments[0]

    async def close(self) -> None:
        """No-op — session lifecycle managed externally."""
