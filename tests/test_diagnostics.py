"""Tests for Nordic Parcel diagnostics."""

from __future__ import annotations

from custom_components.nordic_parcel.diagnostics import _mask_tracking_id


class TestMaskTrackingId:
    def test_masks_long_id(self):
        assert _mask_tracking_id("370000000000123456") == "**************3456"

    def test_short_id_unchanged(self):
        assert _mask_tracking_id("AB") == "AB"

    def test_exactly_four_chars(self):
        assert _mask_tracking_id("ABCD") == "ABCD"

    def test_five_chars(self):
        assert _mask_tracking_id("ABCDE") == "*BCDE"
