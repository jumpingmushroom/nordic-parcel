"""Constants for the Nordic Parcel integration."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

DOMAIN: Final = "nordic_parcel"

DEFAULT_SCAN_INTERVAL: Final = 900  # 15 minutes
DEFAULT_CLEANUP_DAYS: Final = 3

CONF_CARRIER: Final = "carrier"
CONF_API_KEY: Final = "api_key"
CONF_API_UID: Final = "api_uid"
CONF_CLIENT_ID: Final = "client_id"
CONF_CLIENT_SECRET: Final = "client_secret"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_CLEANUP_DAYS: Final = "cleanup_days"
CONF_MANUAL_TRACKING: Final = "manual_tracking"
CONF_DELIVERED_TIMESTAMPS: Final = "delivered_timestamps"


class Carrier(StrEnum):
    """Supported parcel carriers."""

    BRING = "bring"
    POSTNORD = "postnord"
    HELTHJEM = "helthjem"


class ShipmentStatus(StrEnum):
    """Normalized shipment statuses across all carriers."""

    UNKNOWN = "unknown"
    PRE_TRANSIT = "pre_transit"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    READY_FOR_PICKUP = "ready_for_pickup"
    DELIVERED = "delivered"
    RETURNED = "returned"
    FAILED = "failed"
