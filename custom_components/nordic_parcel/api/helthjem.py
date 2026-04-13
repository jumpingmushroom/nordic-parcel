"""Helthjem tracking API client."""

from __future__ import annotations

import asyncio
import logging
import time
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

TOKEN_URL = "https://api.helthjem.no/auth/oauth2/v1/token"
TRACKING_URL = "https://api.helthjem.no/parcels/v1/tracking/fetch"

# Token refresh buffer — refresh 5 min before expiry
_TOKEN_BUFFER_SECONDS = 300

# Helthjem event codes -> normalized ShipmentStatus
# Based on their 9 categories and 50+ event codes
_EVENT_STATUS_MAP: dict[str, ShipmentStatus] = {
    # Booking
    "001": ShipmentStatus.PRE_TRANSIT,  # Transport booked
    # Transportation
    "002": ShipmentStatus.IN_TRANSIT,   # Loaded
    "003": ShipmentStatus.IN_TRANSIT,   # In transit
    "004": ShipmentStatus.IN_TRANSIT,   # In transit
    "006": ShipmentStatus.IN_TRANSIT,   # In transit
    "062": ShipmentStatus.IN_TRANSIT,   # In transit
    "063": ShipmentStatus.IN_TRANSIT,   # In transit
    "104": ShipmentStatus.IN_TRANSIT,   # In transit
    "148": ShipmentStatus.IN_TRANSIT,   # Delivered to service point
    # Status — delivery
    "013": ShipmentStatus.DELIVERED,    # Delivered
    "015": ShipmentStatus.DELIVERED,    # Delivered
    "057": ShipmentStatus.DELIVERED,    # Delivered
    # Status — out for delivery
    "060": ShipmentStatus.OUT_FOR_DELIVERY,
    "061": ShipmentStatus.OUT_FOR_DELIVERY,
    # Status — returns
    "028": ShipmentStatus.RETURNED,
    "029": ShipmentStatus.RETURNED,
    "030": ShipmentStatus.RETURNED,
    "031": ShipmentStatus.RETURNED,
    "032": ShipmentStatus.RETURNED,
    "033": ShipmentStatus.RETURNED,
    "034": ShipmentStatus.RETURNED,
    "035": ShipmentStatus.RETURNED,
    # Status — failed/cancelled
    "068": ShipmentStatus.FAILED,
    "069": ShipmentStatus.FAILED,
    # Status — ready for pickup
    "073": ShipmentStatus.READY_FOR_PICKUP,
    "076": ShipmentStatus.READY_FOR_PICKUP,
    "077": ShipmentStatus.READY_FOR_PICKUP,
    # Status — other
    "093": ShipmentStatus.IN_TRANSIT,
    "095": ShipmentStatus.IN_TRANSIT,
    "100": ShipmentStatus.IN_TRANSIT,
    "112": ShipmentStatus.IN_TRANSIT,
    "113": ShipmentStatus.IN_TRANSIT,
    "117": ShipmentStatus.IN_TRANSIT,
    "118": ShipmentStatus.IN_TRANSIT,
    "119": ShipmentStatus.IN_TRANSIT,
    "120": ShipmentStatus.IN_TRANSIT,
    "121": ShipmentStatus.IN_TRANSIT,
    "122": ShipmentStatus.IN_TRANSIT,
    "125": ShipmentStatus.IN_TRANSIT,
    "136": ShipmentStatus.IN_TRANSIT,
    "151": ShipmentStatus.IN_TRANSIT,
    "154": ShipmentStatus.IN_TRANSIT,
    # Scanner events
    "016": ShipmentStatus.IN_TRANSIT,
    "017": ShipmentStatus.IN_TRANSIT,
    "018": ShipmentStatus.IN_TRANSIT,
    "019": ShipmentStatus.IN_TRANSIT,
    "022": ShipmentStatus.IN_TRANSIT,
    "024": ShipmentStatus.IN_TRANSIT,
    "107": ShipmentStatus.IN_TRANSIT,
    "115": ShipmentStatus.IN_TRANSIT,
    "116": ShipmentStatus.IN_TRANSIT,
    "149": ShipmentStatus.IN_TRANSIT,
    "150": ShipmentStatus.IN_TRANSIT,
    # Export / partner carrier handoffs
    "026": ShipmentStatus.IN_TRANSIT,
    "126": ShipmentStatus.IN_TRANSIT,
    "147": ShipmentStatus.IN_TRANSIT,
}


def _map_event_code(code: str) -> ShipmentStatus:
    """Map a Helthjem event code to normalized ShipmentStatus."""
    return _EVENT_STATUS_MAP.get(code, ShipmentStatus.UNKNOWN)


def _parse_event(event: dict) -> TrackingEvent:
    """Parse a Helthjem tracking event."""
    timestamp_str = event.get("timestamp") or event.get("eventTime", "")
    try:
        timestamp = datetime.fromisoformat(timestamp_str)
    except ValueError:
        timestamp = datetime.now()

    event_code = str(event.get("eventCode", event.get("code", "")))
    description = event.get("description", event.get("text", ""))
    location = event.get("location") or event.get("city")

    return TrackingEvent(
        timestamp=timestamp,
        description=description,
        location=location,
        status=_map_event_code(event_code),
    )


class HelthjemApiClient:
    """Async client for the Helthjem Tracking API with OAuth2 auth."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        client_id: str,
        client_secret: str,
    ) -> None:
        self._session = session
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token: str | None = None
        self._token_expires_at: float = 0

    @property
    def carrier(self) -> Carrier:
        return Carrier.HELTHJEM

    async def _ensure_token(self) -> str:
        """Obtain or refresh the OAuth2 access token."""
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        try:
            async with asyncio.timeout(10):
                resp = await self._session.post(
                    TOKEN_URL,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CarrierApiError(f"Token request failed: {err}") from err

        if resp.status in (401, 403):
            raise CarrierAuthError("Invalid Helthjem client credentials")
        if resp.status != 200:
            raise CarrierApiError(f"Helthjem token endpoint returned {resp.status}")

        data = await resp.json()
        self._access_token = data["access_token"]
        expires_in = data.get("expires_in", 86400)  # Default 24h
        self._token_expires_at = time.time() + expires_in - _TOKEN_BUFFER_SECONDS

        return self._access_token

    def _auth_headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    async def authenticate(self) -> bool:
        """Validate credentials by obtaining a token."""
        try:
            await self._ensure_token()
            return True
        except CarrierAuthError:
            return False

    async def get_shipments(self) -> list[Shipment]:
        """Helthjem API doesn't support listing all shipments for an account.

        Returns an empty list. Users must add tracking numbers manually.
        """
        return []

    async def track_shipment(self, tracking_id: str) -> list[Shipment]:
        """Fetch tracking data for a single shipment."""
        token = await self._ensure_token()

        url = f"{TRACKING_URL}/{tracking_id}/EN/false"

        try:
            async with asyncio.timeout(10):
                resp = await self._session.get(
                    url,
                    headers=self._auth_headers(token),
                )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CarrierApiError(f"Connection error: {err}") from err

        if resp.status in (401, 403):
            # Token might be stale, clear and retry once
            self._access_token = None
            token = await self._ensure_token()
            try:
                async with asyncio.timeout(10):
                    resp = await self._session.get(
                        url,
                        headers=self._auth_headers(token),
                    )
            except (aiohttp.ClientError, TimeoutError) as err:
                raise CarrierApiError(f"Connection error: {err}") from err

            if resp.status in (401, 403):
                raise CarrierAuthError("Invalid Helthjem credentials")

        if resp.status == 429:
            raise CarrierRateLimitError("Helthjem API rate limit exceeded")
        if resp.status == 404:
            raise CarrierNotFoundError(f"No shipment found for {tracking_id}")
        if resp.status != 200:
            raise CarrierApiError(f"Helthjem API returned status {resp.status}")

        data = await resp.json()

        # Response may contain multiple parcels for a single shipment
        parcels = data if isinstance(data, list) else [data]
        if not parcels:
            raise CarrierNotFoundError(f"No tracking data for {tracking_id}")

        # Collect events from all parcels
        events: list[TrackingEvent] = []
        raw_data = parcels[0] if len(parcels) == 1 else {"parcels": parcels}

        for parcel in parcels:
            for event in parcel.get("events", []):
                events.append(_parse_event(event))

        events.sort(key=lambda e: e.timestamp, reverse=True)
        status = events[0].status if events else ShipmentStatus.UNKNOWN

        return [Shipment(
            tracking_id=tracking_id,
            carrier=Carrier.HELTHJEM,
            status=status,
            sender=parcels[0].get("shop", {}).get("name") if parcels else None,
            recipient=None,
            estimated_delivery=None,
            events=events,
            raw_data=raw_data,
        )]

    async def close(self) -> None:
        """No-op — session lifecycle managed externally."""
