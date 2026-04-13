"""Shared test fixtures for Nordic Parcel tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.nordic_parcel.const import (
    CONF_API_KEY,
    CONF_API_UID,
    CONF_CARRIER,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    DOMAIN,
    Carrier,
)


@pytest.fixture
def mock_bring_config_entry(hass: HomeAssistant):
    """Create a mock Bring config entry."""
    from homeassistant.config_entries import ConfigEntry

    entry = ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Bring (test@example.com)",
        data={
            CONF_CARRIER: Carrier.BRING,
            CONF_API_UID: "test@example.com",
            CONF_API_KEY: "test-api-key",
        },
        source="user",
        unique_id="bring_test@example.com",
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_postnord_config_entry(hass: HomeAssistant):
    """Create a mock Postnord config entry."""
    from homeassistant.config_entries import ConfigEntry

    entry = ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Postnord",
        data={
            CONF_CARRIER: Carrier.POSTNORD,
            CONF_API_KEY: "test-postnord-key",
        },
        source="user",
        unique_id="postnord_abc12345",
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_helthjem_config_entry(hass: HomeAssistant):
    """Create a mock Helthjem config entry."""
    from homeassistant.config_entries import ConfigEntry

    entry = ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Helthjem",
        data={
            CONF_CARRIER: Carrier.HELTHJEM,
            CONF_CLIENT_ID: "test-client-id",
            CONF_CLIENT_SECRET: "test-client-secret",
        },
        source="user",
        unique_id="helthjem_abc12345",
    )
    entry.add_to_hass(hass)
    return entry


# Sample API response data

BRING_TRACKING_RESPONSE = {
    "consignmentSet": [
        {
            "consignmentId": "TESTCONS123",
            "senderName": "Test Sender AS",
            "senderAddress": {"city": "Oslo", "countryCode": "NO"},
            "recipientName": "Test Recipient",
            "recipientAddress": {"city": "Bergen", "countryCode": "NO"},
            "packageSet": [
                {
                    "packageNumber": "370000000000123456",
                    "senderName": "Test Sender AS",
                    "recipientName": "Test Recipient",
                    "dateOfEstimatedDelivery": "2026-04-15",
                    "eventSet": [
                        {
                            "dateIso": "2026-04-13T10:30:00+02:00",
                            "status": "IN_TRANSIT",
                            "description": "Parcel received by Bring",
                            "city": "Oslo",
                            "country": "Norway",
                        }
                    ],
                }
            ],
        }
    ]
}

POSTNORD_TRACKING_RESPONSE = {
    "TrackingInformationResponse": {
        "shipments": [
            {
                "shipmentId": "00340000000000000001",
                "status": "EN_ROUTE",
                "consignor": {"name": "PostNord Sender AB"},
                "estimatedTimeOfArrival": "2026-04-15T14:00:00+02:00",
                "items": [
                    {
                        "events": [
                            {
                                "eventTime": "2026-04-13T08:00:00+02:00",
                                "status": "EN_ROUTE",
                                "eventDescription": "In transit",
                                "location": {"displayName": "Stockholm"},
                            }
                        ]
                    }
                ],
            }
        ]
    }
}

HELTHJEM_TRACKING_RESPONSE = [
    {
        "shop": {"name": "Helthjem Shop"},
        "events": [
            {
                "timestamp": "2026-04-13T09:00:00+02:00",
                "eventCode": "003",
                "description": "In transit",
                "location": "Trondheim",
            }
        ],
    }
]

HELTHJEM_TOKEN_RESPONSE = {
    "access_token": "test-access-token-123",
    "expires_in": 86400,
    "token_type": "Bearer",
}
