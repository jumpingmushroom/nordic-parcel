"""Build the API client for a carrier."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import aiohttp

from ..const import (
    CONF_API_KEY,
    CONF_API_UID,
    CONF_CARRIER,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    Carrier,
)
from . import CarrierClient
from .bring import BringApiClient
from .helthjem import HelthjemApiClient
from .postnord import PostnordApiClient


def create_client(session: aiohttp.ClientSession, data: Mapping[str, Any]) -> CarrierClient:
    """Create the client for the carrier and credentials in ``data``."""
    carrier = Carrier(data[CONF_CARRIER])
    if carrier == Carrier.BRING:
        return BringApiClient(session, data[CONF_API_UID], data[CONF_API_KEY])
    if carrier == Carrier.POSTNORD:
        return PostnordApiClient(session, data[CONF_API_KEY])
    return HelthjemApiClient(session, data[CONF_CLIENT_ID], data[CONF_CLIENT_SECRET])
