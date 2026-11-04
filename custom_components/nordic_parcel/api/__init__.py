"""API client layer for Nordic Parcel integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from ..const import Carrier, ShipmentStatus


def ensure_aware(value: datetime) -> datetime:
    """Return a timezone-aware datetime, assuming UTC if naive.

    Carrier APIs sometimes return timestamps without a UTC offset. Leaving
    these naive causes TypeErrors when compared or subtracted against the
    aware ``datetime.now(UTC)`` used throughout the coordinator.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


@dataclass
class TrackingEvent:
    """A single tracking event in a shipment's history."""

    timestamp: datetime
    description: str
    location: str | None = None
    status: ShipmentStatus = ShipmentStatus.UNKNOWN


@dataclass
class Shipment:
    """Normalized shipment data across all carriers."""

    tracking_id: str
    carrier: Carrier
    status: ShipmentStatus = ShipmentStatus.UNKNOWN
    sender: str | None = None
    recipient: str | None = None
    estimated_delivery: datetime | None = None
    events: list[TrackingEvent] = field(default_factory=list)
    """Tracking events ordered newest-first. Carrier clients must sort before returning."""

    @property
    def last_event(self) -> TrackingEvent | None:
        """Return the most recent tracking event (first in newest-first list)."""
        return self.events[0] if self.events else None


class CarrierApiError(Exception):
    """Base exception for carrier API errors."""


class CarrierAuthError(CarrierApiError):
    """Authentication failed."""


class CarrierRateLimitError(CarrierApiError):
    """Rate limit exceeded."""


class CarrierNotFoundError(CarrierApiError):
    """Shipment not found."""


class CarrierClient(Protocol):
    """Protocol that all carrier API clients must implement."""

    @property
    def carrier(self) -> Carrier:
        """Return the carrier this client handles."""
        ...

    async def authenticate(self) -> bool:
        """Validate credentials. Return True if valid."""
        ...

    async def track_shipment(self, tracking_id: str) -> list[Shipment]:
        """Fetch tracking data for a shipment (may return multiple packages)."""
        ...
