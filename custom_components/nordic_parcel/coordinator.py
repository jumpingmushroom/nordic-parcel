"""DataUpdateCoordinator for Nordic Parcel integration."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    CarrierAuthError,
    CarrierApiError,
    CarrierClient,
    CarrierNotFoundError,
    CarrierRateLimitError,
    Shipment,
)
from .const import (
    CONF_CLEANUP_DAYS,
    CONF_MANUAL_TRACKING,
    CONF_SCAN_INTERVAL,
    DEFAULT_CLEANUP_DAYS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ShipmentStatus,
)

_LOGGER = logging.getLogger(__name__)

type NordicParcelConfigEntry = ConfigEntry[NordicParcelCoordinator]


class NordicParcelCoordinator(DataUpdateCoordinator[dict[str, Shipment]]):
    """Coordinate data fetching from carrier APIs."""

    config_entry: NordicParcelConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: NordicParcelConfigEntry,
        client: CarrierClient,
    ) -> None:
        scan_interval = config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{config_entry.entry_id}",
            config_entry=config_entry,
            update_interval=timedelta(seconds=scan_interval),
            always_update=False,
        )
        self.client = client
        self._delivered_timestamps: dict[str, datetime] = {}
        self._previous_statuses: dict[str, str] = {}

    @property
    def manual_tracking_ids(self) -> list[str]:
        """Return manually-added tracking IDs from config entry data."""
        return list(
            self.config_entry.data.get(CONF_MANUAL_TRACKING, {}).keys()
        )

    async def add_tracking(self, tracking_id: str) -> None:
        """Add a tracking number to manual tracking list."""
        data = dict(self.config_entry.data)
        manual = dict(data.get(CONF_MANUAL_TRACKING, {}))
        manual[tracking_id] = {"added": datetime.now(timezone.utc).isoformat()}
        data[CONF_MANUAL_TRACKING] = manual
        self.hass.config_entries.async_update_entry(
            self.config_entry, data=data
        )
        # Trigger an immediate refresh
        await self.async_request_refresh()

    async def remove_tracking(self, tracking_id: str) -> None:
        """Remove a tracking number from manual tracking list."""
        data = dict(self.config_entry.data)
        manual = dict(data.get(CONF_MANUAL_TRACKING, {}))
        manual.pop(tracking_id, None)
        data[CONF_MANUAL_TRACKING] = manual
        self.hass.config_entries.async_update_entry(
            self.config_entry, data=data
        )
        await self.async_request_refresh()

    async def _async_update_data(self) -> dict[str, Shipment]:
        """Fetch tracking data from the carrier API."""
        shipments: dict[str, Shipment] = {}

        # 1. Fetch auto-discovered shipments from account
        try:
            account_shipments = await self.client.get_shipments()
            for s in account_shipments:
                shipments[s.tracking_id] = s
        except CarrierAuthError as err:
            raise ConfigEntryAuthFailed from err
        except CarrierRateLimitError:
            raise UpdateFailed(retry_after=120)
        except CarrierApiError as err:
            _LOGGER.warning("Failed to fetch account shipments: %s", err)

        # 2. Fetch manually-tracked shipments
        ids_to_replace: dict[str, list[str]] = {}
        for tracking_id in self.manual_tracking_ids:
            if tracking_id in shipments:
                continue  # Already fetched via account
            try:
                results = await self.client.track_shipment(tracking_id)
                for shipment in results:
                    shipments[shipment.tracking_id] = shipment
                # If the query ID resolved to different package IDs, schedule replacement
                result_ids = [s.tracking_id for s in results]
                if result_ids and tracking_id not in result_ids:
                    ids_to_replace[tracking_id] = result_ids
            except CarrierAuthError as err:
                raise ConfigEntryAuthFailed from err
            except CarrierRateLimitError:
                raise UpdateFailed(retry_after=120)
            except CarrierNotFoundError:
                _LOGGER.debug("Tracking ID %s not found, skipping", tracking_id)
            except CarrierApiError as err:
                _LOGGER.warning("Failed to track %s: %s", tracking_id, err)

        # 2.5 Replace consignment numbers with resolved package numbers
        if ids_to_replace:
            data = dict(self.config_entry.data)
            manual = dict(data.get(CONF_MANUAL_TRACKING, {}))
            for old_id, new_ids in ids_to_replace.items():
                ts = manual.pop(old_id, {"added": datetime.now(timezone.utc).isoformat()})
                for new_id in new_ids:
                    if new_id not in manual:
                        manual[new_id] = ts
                _LOGGER.info(
                    "Replaced consignment %s with package(s): %s",
                    old_id, ", ".join(new_ids),
                )
            data[CONF_MANUAL_TRACKING] = manual
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=data
            )

        # 3. Fire status change events
        for tid, shipment in shipments.items():
            old_status = self._previous_statuses.get(tid)
            new_status = shipment.status.value
            if old_status is not None and old_status != new_status:
                self.hass.bus.async_fire(
                    f"{DOMAIN}_status_changed",
                    {
                        "tracking_id": tid,
                        "carrier": shipment.carrier.value,
                        "sender": shipment.sender,
                        "old_status": old_status,
                        "new_status": new_status,
                    },
                )
            self._previous_statuses[tid] = new_status

        # 4. Track delivery timestamps for auto-cleanup
        for tid, shipment in shipments.items():
            if shipment.status == ShipmentStatus.DELIVERED:
                if tid not in self._delivered_timestamps:
                    self._delivered_timestamps[tid] = datetime.now(timezone.utc)
                    # Fire delivered event
                    self.hass.bus.async_fire(
                        f"{DOMAIN}_delivered",
                        {
                            "tracking_id": tid,
                            "carrier": shipment.carrier,
                        },
                    )
            else:
                # Was delivered but status changed (rare) — reset
                self._delivered_timestamps.pop(tid, None)

        # 4. Auto-cleanup delivered parcels past the threshold
        cleanup_days = self.config_entry.options.get(
            CONF_CLEANUP_DAYS, DEFAULT_CLEANUP_DAYS
        )
        if cleanup_days > 0:
            now = datetime.now(timezone.utc)
            expired = [
                tid
                for tid, delivered_at in self._delivered_timestamps.items()
                if (now - delivered_at).days >= cleanup_days
            ]
            for tid in expired:
                shipments.pop(tid, None)
                self._delivered_timestamps.pop(tid, None)
                self._previous_statuses.pop(tid, None)
                # Also remove from manual tracking
                if tid in self.manual_tracking_ids:
                    data = dict(self.config_entry.data)
                    manual = dict(data.get(CONF_MANUAL_TRACKING, {}))
                    manual.pop(tid, None)
                    data[CONF_MANUAL_TRACKING] = manual
                    self.hass.config_entries.async_update_entry(
                        self.config_entry, data=data
                    )

        return shipments
