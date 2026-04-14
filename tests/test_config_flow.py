"""Tests for the Nordic Parcel config flow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.nordic_parcel.api import CarrierApiError
from custom_components.nordic_parcel.const import (
    CONF_API_KEY,
    CONF_API_UID,
    CONF_CARRIER,
    CONF_CLEANUP_DAYS,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_SCAN_INTERVAL,
    DOMAIN,
    Carrier,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

MOCK_SESSION = "custom_components.nordic_parcel.config_flow.async_get_clientsession"
MOCK_SETUP = "custom_components.nordic_parcel.async_setup_entry"


# ---------------------------------------------------------------------------
# User step
# ---------------------------------------------------------------------------


async def test_user_step_shows_carrier_form(hass: HomeAssistant) -> None:
    """Test that the user step shows a carrier selection form."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


# ---------------------------------------------------------------------------
# Bring flow
# ---------------------------------------------------------------------------


async def test_bring_flow_success(hass: HomeAssistant) -> None:
    """Test successful Bring config flow creates an entry."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

    with (
        patch(MOCK_SESSION, return_value=MagicMock()),
        patch(MOCK_SETUP, return_value=True),
        patch(
            "custom_components.nordic_parcel.config_flow.BringApiClient.authenticate",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_CARRIER: Carrier.BRING},
        )
        # Now on the bring step form
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "bring"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_API_UID: "test@example.com",
                CONF_API_KEY: "test-key-123",
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Bring (test@example.com)"
    assert result["data"] == {
        CONF_CARRIER: Carrier.BRING,
        CONF_API_UID: "test@example.com",
        CONF_API_KEY: "test-key-123",
    }


async def test_bring_flow_auth_failure(hass: HomeAssistant) -> None:
    """Test Bring flow shows error on invalid credentials."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_CARRIER: Carrier.BRING},
    )

    with (
        patch(MOCK_SESSION, return_value=MagicMock()),
        patch(
            "custom_components.nordic_parcel.config_flow.BringApiClient.authenticate",
            return_value=False,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_API_UID: "bad@example.com",
                CONF_API_KEY: "bad-key",
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bring"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_bring_flow_connection_error(hass: HomeAssistant) -> None:
    """Test Bring flow shows error on connection failure."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_CARRIER: Carrier.BRING},
    )

    with (
        patch(MOCK_SESSION, return_value=MagicMock()),
        patch(
            "custom_components.nordic_parcel.config_flow.BringApiClient.authenticate",
            side_effect=CarrierApiError("Connection failed"),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_API_UID: "test@example.com",
                CONF_API_KEY: "test-key",
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bring"
    assert result["errors"] == {"base": "cannot_connect"}


# ---------------------------------------------------------------------------
# Postnord flow
# ---------------------------------------------------------------------------


async def test_postnord_flow_success(hass: HomeAssistant) -> None:
    """Test successful Postnord config flow creates an entry."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

    with (
        patch(MOCK_SESSION, return_value=MagicMock()),
        patch(MOCK_SETUP, return_value=True),
        patch(
            "custom_components.nordic_parcel.config_flow.PostnordApiClient.authenticate",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_CARRIER: Carrier.POSTNORD},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "postnord"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "postnord-key-456"},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Postnord"
    assert result["data"][CONF_CARRIER] == Carrier.POSTNORD
    assert result["data"][CONF_API_KEY] == "postnord-key-456"


async def test_postnord_flow_auth_failure(hass: HomeAssistant) -> None:
    """Test Postnord flow shows error on invalid credentials."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_CARRIER: Carrier.POSTNORD},
    )

    with (
        patch(MOCK_SESSION, return_value=MagicMock()),
        patch(
            "custom_components.nordic_parcel.config_flow.PostnordApiClient.authenticate",
            return_value=False,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "bad-key"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "postnord"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_postnord_flow_connection_error(hass: HomeAssistant) -> None:
    """Test Postnord flow shows error on connection failure."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_CARRIER: Carrier.POSTNORD},
    )

    with (
        patch(MOCK_SESSION, return_value=MagicMock()),
        patch(
            "custom_components.nordic_parcel.config_flow.PostnordApiClient.authenticate",
            side_effect=CarrierApiError("Connection failed"),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "some-key"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "postnord"
    assert result["errors"] == {"base": "cannot_connect"}


# ---------------------------------------------------------------------------
# Helthjem flow
# ---------------------------------------------------------------------------


async def test_helthjem_flow_success(hass: HomeAssistant) -> None:
    """Test successful Helthjem config flow creates an entry."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

    with (
        patch(MOCK_SESSION, return_value=MagicMock()),
        patch(MOCK_SETUP, return_value=True),
        patch(
            "custom_components.nordic_parcel.config_flow.HelthjemApiClient.authenticate",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_CARRIER: Carrier.HELTHJEM},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "helthjem"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_CLIENT_ID: "helthjem-client-id",
                CONF_CLIENT_SECRET: "helthjem-secret",
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Helthjem"
    assert result["data"][CONF_CARRIER] == Carrier.HELTHJEM
    assert result["data"][CONF_CLIENT_ID] == "helthjem-client-id"
    assert result["data"][CONF_CLIENT_SECRET] == "helthjem-secret"


async def test_helthjem_flow_auth_failure(hass: HomeAssistant) -> None:
    """Test Helthjem flow shows error on invalid credentials."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_CARRIER: Carrier.HELTHJEM},
    )

    with (
        patch(MOCK_SESSION, return_value=MagicMock()),
        patch(
            "custom_components.nordic_parcel.config_flow.HelthjemApiClient.authenticate",
            return_value=False,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_CLIENT_ID: "bad-id",
                CONF_CLIENT_SECRET: "bad-secret",
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "helthjem"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_helthjem_flow_connection_error(hass: HomeAssistant) -> None:
    """Test Helthjem flow shows error on connection failure."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_CARRIER: Carrier.HELTHJEM},
    )

    with (
        patch(MOCK_SESSION, return_value=MagicMock()),
        patch(
            "custom_components.nordic_parcel.config_flow.HelthjemApiClient.authenticate",
            side_effect=CarrierApiError("Connection failed"),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_CLIENT_ID: "some-id",
                CONF_CLIENT_SECRET: "some-secret",
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "helthjem"
    assert result["errors"] == {"base": "cannot_connect"}


# ---------------------------------------------------------------------------
# Reauth flows
# ---------------------------------------------------------------------------


async def test_reauth_bring_success(hass: HomeAssistant, mock_bring_config_entry) -> None:
    """Test successful Bring reauthentication updates the entry."""
    with patch(MOCK_SETUP, return_value=True):
        await hass.config_entries.async_setup(mock_bring_config_entry.entry_id)
        await hass.async_block_till_done()

    result = await mock_bring_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_bring"

    with (
        patch(MOCK_SESSION, return_value=MagicMock()),
        patch(MOCK_SETUP, return_value=True),
        patch(
            "custom_components.nordic_parcel.config_flow.BringApiClient.authenticate",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_UID: "new@example.com", CONF_API_KEY: "new-key"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_bring_config_entry.data[CONF_API_UID] == "new@example.com"
    assert mock_bring_config_entry.data[CONF_API_KEY] == "new-key"


async def test_reauth_bring_invalid_auth(hass: HomeAssistant, mock_bring_config_entry) -> None:
    """Test Bring reauth shows error on invalid credentials."""
    with patch(MOCK_SETUP, return_value=True):
        await hass.config_entries.async_setup(mock_bring_config_entry.entry_id)
        await hass.async_block_till_done()

    result = await mock_bring_config_entry.start_reauth_flow(hass)

    with (
        patch(MOCK_SESSION, return_value=MagicMock()),
        patch(
            "custom_components.nordic_parcel.config_flow.BringApiClient.authenticate",
            return_value=False,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_UID: "bad@example.com", CONF_API_KEY: "bad-key"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reauth_bring_cannot_connect(hass: HomeAssistant, mock_bring_config_entry) -> None:
    """Test Bring reauth shows error on connection failure."""
    with patch(MOCK_SETUP, return_value=True):
        await hass.config_entries.async_setup(mock_bring_config_entry.entry_id)
        await hass.async_block_till_done()

    result = await mock_bring_config_entry.start_reauth_flow(hass)

    with (
        patch(MOCK_SESSION, return_value=MagicMock()),
        patch(
            "custom_components.nordic_parcel.config_flow.BringApiClient.authenticate",
            side_effect=CarrierApiError("Connection failed"),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_UID: "test@example.com", CONF_API_KEY: "test-key"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reauth_postnord_success(hass: HomeAssistant, mock_postnord_config_entry) -> None:
    """Test successful Postnord reauthentication updates the entry."""
    with patch(MOCK_SETUP, return_value=True):
        await hass.config_entries.async_setup(mock_postnord_config_entry.entry_id)
        await hass.async_block_till_done()

    result = await mock_postnord_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_postnord"

    with (
        patch(MOCK_SESSION, return_value=MagicMock()),
        patch(MOCK_SETUP, return_value=True),
        patch(
            "custom_components.nordic_parcel.config_flow.PostnordApiClient.authenticate",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "new-postnord-key"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_postnord_config_entry.data[CONF_API_KEY] == "new-postnord-key"


async def test_reauth_postnord_invalid_auth(
    hass: HomeAssistant, mock_postnord_config_entry
) -> None:
    """Test Postnord reauth shows error on invalid credentials."""
    with patch(MOCK_SETUP, return_value=True):
        await hass.config_entries.async_setup(mock_postnord_config_entry.entry_id)
        await hass.async_block_till_done()

    result = await mock_postnord_config_entry.start_reauth_flow(hass)

    with (
        patch(MOCK_SESSION, return_value=MagicMock()),
        patch(
            "custom_components.nordic_parcel.config_flow.PostnordApiClient.authenticate",
            return_value=False,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "bad-key"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reauth_postnord_cannot_connect(
    hass: HomeAssistant, mock_postnord_config_entry
) -> None:
    """Test Postnord reauth shows error on connection failure."""
    with patch(MOCK_SETUP, return_value=True):
        await hass.config_entries.async_setup(mock_postnord_config_entry.entry_id)
        await hass.async_block_till_done()

    result = await mock_postnord_config_entry.start_reauth_flow(hass)

    with (
        patch(MOCK_SESSION, return_value=MagicMock()),
        patch(
            "custom_components.nordic_parcel.config_flow.PostnordApiClient.authenticate",
            side_effect=CarrierApiError("Connection failed"),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_API_KEY: "some-key"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reauth_helthjem_success(hass: HomeAssistant, mock_helthjem_config_entry) -> None:
    """Test successful Helthjem reauthentication updates the entry."""
    with patch(MOCK_SETUP, return_value=True):
        await hass.config_entries.async_setup(mock_helthjem_config_entry.entry_id)
        await hass.async_block_till_done()

    result = await mock_helthjem_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_helthjem"

    with (
        patch(MOCK_SESSION, return_value=MagicMock()),
        patch(MOCK_SETUP, return_value=True),
        patch(
            "custom_components.nordic_parcel.config_flow.HelthjemApiClient.authenticate",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_CLIENT_ID: "new-client-id", CONF_CLIENT_SECRET: "new-secret"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_helthjem_config_entry.data[CONF_CLIENT_ID] == "new-client-id"
    assert mock_helthjem_config_entry.data[CONF_CLIENT_SECRET] == "new-secret"


async def test_reauth_helthjem_invalid_auth(
    hass: HomeAssistant, mock_helthjem_config_entry
) -> None:
    """Test Helthjem reauth shows error on invalid credentials."""
    with patch(MOCK_SETUP, return_value=True):
        await hass.config_entries.async_setup(mock_helthjem_config_entry.entry_id)
        await hass.async_block_till_done()

    result = await mock_helthjem_config_entry.start_reauth_flow(hass)

    with (
        patch(MOCK_SESSION, return_value=MagicMock()),
        patch(
            "custom_components.nordic_parcel.config_flow.HelthjemApiClient.authenticate",
            return_value=False,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_CLIENT_ID: "bad-id", CONF_CLIENT_SECRET: "bad-secret"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reauth_helthjem_cannot_connect(
    hass: HomeAssistant, mock_helthjem_config_entry
) -> None:
    """Test Helthjem reauth shows error on connection failure."""
    with patch(MOCK_SETUP, return_value=True):
        await hass.config_entries.async_setup(mock_helthjem_config_entry.entry_id)
        await hass.async_block_till_done()

    result = await mock_helthjem_config_entry.start_reauth_flow(hass)

    with (
        patch(MOCK_SESSION, return_value=MagicMock()),
        patch(
            "custom_components.nordic_parcel.config_flow.HelthjemApiClient.authenticate",
            side_effect=CarrierApiError("Connection failed"),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_CLIENT_ID: "some-id", CONF_CLIENT_SECRET: "some-secret"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------


async def test_options_flow(hass: HomeAssistant, mock_bring_config_entry) -> None:
    """Test the options flow allows changing scan_interval and cleanup_days."""
    entry = mock_bring_config_entry

    with patch("custom_components.nordic_parcel.async_setup_entry", return_value=True):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_SCAN_INTERVAL: 600,
            CONF_CLEANUP_DAYS: 7,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_SCAN_INTERVAL: 600,
        CONF_CLEANUP_DAYS: 7,
    }
