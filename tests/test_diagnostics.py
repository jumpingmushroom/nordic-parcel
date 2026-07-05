"""Tests for Nordic Parcel diagnostics."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.nordic_parcel.const import (
    CONF_DELIVERED_TIMESTAMPS,
    CONF_MANUAL_TRACKING,
    Carrier,
)
from custom_components.nordic_parcel.coordinator import NordicParcelCoordinator
from custom_components.nordic_parcel.diagnostics import (
    _mask_tracking_id,
    async_get_config_entry_diagnostics,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

FULL_ID = "370000000000123456"


class TestMaskTrackingId:
    def test_masks_long_id(self):
        assert _mask_tracking_id(FULL_ID) == "**************3456"

    def test_short_id_unchanged(self):
        assert _mask_tracking_id("AB") == "AB"

    def test_exactly_four_chars(self):
        assert _mask_tracking_id("ABCD") == "ABCD"

    def test_five_chars(self):
        assert _mask_tracking_id("ABCDE") == "*BCDE"


async def test_diagnostics_masks_tracking_ids_and_credentials(
    hass: HomeAssistant, mock_bring_config_entry
):
    """Full tracking IDs and credentials must not appear in diagnostics output."""
    hass.config_entries.async_update_entry(
        mock_bring_config_entry,
        data={
            **mock_bring_config_entry.data,
            CONF_MANUAL_TRACKING: {FULL_ID: {"added": "2026-04-13T00:00:00+00:00"}},
            CONF_DELIVERED_TIMESTAMPS: {FULL_ID: "2026-04-14T00:00:00+00:00"},
        },
    )

    client = AsyncMock()
    client.carrier = Carrier.BRING
    coordinator = NordicParcelCoordinator(hass, mock_bring_config_entry, client)
    coordinator.data = {}
    mock_bring_config_entry.runtime_data = coordinator

    result = await async_get_config_entry_diagnostics(hass, mock_bring_config_entry)
    serialized = json.dumps(result)

    assert FULL_ID not in serialized
    assert "test-api-key" not in serialized
    # The masked form should be present in the manual_tracking section.
    assert _mask_tracking_id(FULL_ID) in serialized
