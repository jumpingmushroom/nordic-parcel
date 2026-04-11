"""API client layer for Nordic Parcel integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from ..const import Carrier, ShipmentStatus


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
    raw_data: dict = field(default_factory=dict)

    @property
    def last_event(self) -> TrackingEvent | None:
        """Return the most recent tracking event."""
        return self.events[0] if self.events else None


class CarrierApiError(Exception):
    """Base exception for carrier API errors."""


class CarrierAuthError(CarrierApiError):
    """Authentication failed."""


class CarrierRateLimitError(CarrierApiError):
    """Rate limit exceeded."""


class CarrierNotFoundError(CarrierApiError):
    """Shipment not found."""


@runtime_checkable
class CarrierClient(Protocol):
    """Protocol that all carrier API clients must implement."""

    @property
    def carrier(self) -> Carrier:
        """Return the carrier this client handles."""
        ...

    async def authenticate(self) -> bool:
        """Validate credentials. Return True if valid."""
        ...

    async def get_shipments(self) -> list[Shipment]:
        """Fetch all shipments from the authenticated account."""
        ...

    async def track_shipment(self, tracking_id: str) -> Shipment:
        """Fetch tracking data for a single shipment by ID."""
        ...

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        ...
