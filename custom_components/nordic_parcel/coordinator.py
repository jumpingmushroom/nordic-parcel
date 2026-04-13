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
    CONF_DELIVERED_TIMESTAMPS,
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
        # Load persisted delivery timestamps
        self._delivered_timestamps: dict[str, datetime] = {}
        for tid, ts_str in config_entry.data.get(CONF_DELIVERED_TIMESTAMPS, {}).items():
            try:
                self._delivered_timestamps[tid] = datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                pass
        self._previous_statuses: dict[str, str] = {}

    @property
    def manual_tracking_ids(self) -> list[str]:
        """Return manually-added tracking IDs from config entry data."""
        return list(
            self.config_entry.data.get(CONF_MANUAL_TRACKING, {}).keys()
        )

    async def add_tracking(self, tracking_id: str) -> None:
        """Add a tracking number to manual tracking list."""
        tracking_id = tracking_id.upper()
        data = dict(self.config_entry.data)
        manual = dict(data.get(CONF_MANUAL_TRACKING, {}))
        manual[tracking_id] = {"added": datetime.now(timezone.utc).isoformat()}
        data[CONF_MANUAL_TRACKING] = manual
        self.hass.config_entries.async_update_entry(
            self.config_entry, data=data
        )
        await self.async_request_refresh()

    async def remove_tracking(self, tracking_id: str) -> None:
        """Remove a tracking number from manual tracking list."""
        tracking_id = tracking_id.upper()
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
        config_changed = False

        # Work on a copy of manual tracking for batched updates
        data = dict(self.config_entry.data)
        manual = dict(data.get(CONF_MANUAL_TRACKING, {}))

        # 1. Fetch auto-discovered shipments from account
        try:
            account_shipments = await self.client.get_shipments()
            for s in account_shipments:
                shipments[s.tracking_id] = s
        except CarrierAuthError as err:
            raise ConfigEntryAuthFailed from err
        except CarrierRateLimitError:
            raise UpdateFailed("Rate limited by carrier API")
        except CarrierApiError as err:
            _LOGGER.warning("Failed to fetch account shipments: %s", err)

        # 2. Fetch manually-tracked shipments
        for tracking_id in list(manual.keys()):
            if tracking_id in shipments:
                continue
            try:
                results = await self.client.track_shipment(tracking_id)
                for shipment in results:
                    shipments[shipment.tracking_id.upper()] = shipment
                # Replace consignment numbers with resolved package numbers
                result_ids = [s.tracking_id.upper() for s in results]
                if result_ids and tracking_id not in result_ids:
                    ts = manual.pop(tracking_id)
                    for new_id in result_ids:
                        if new_id not in manual:
                            manual[new_id] = ts
                    config_changed = True
                    _LOGGER.info(
                        "Replaced consignment %s with package(s): %s",
                        tracking_id, ", ".join(result_ids),
                    )
            except CarrierAuthError as err:
                raise ConfigEntryAuthFailed from err
            except CarrierRateLimitError:
                raise UpdateFailed("Rate limited by carrier API")
            except CarrierNotFoundError:
                _LOGGER.debug("Tracking ID %s not found, skipping", tracking_id)
            except CarrierApiError as err:
                _LOGGER.warning("Failed to track %s: %s", tracking_id, err)

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

        # 4. Track delivery timestamps
        for tid, shipment in shipments.items():
            if shipment.status == ShipmentStatus.DELIVERED:
                if tid not in self._delivered_timestamps:
                    self._delivered_timestamps[tid] = datetime.now(timezone.utc)
                    config_changed = True
                    self.hass.bus.async_fire(
                        f"{DOMAIN}_delivered",
                        {
                            "tracking_id": tid,
                            "carrier": shipment.carrier.value,
                        },
                    )
            else:
                if tid in self._delivered_timestamps:
                    self._delivered_timestamps.pop(tid)
                    config_changed = True

        # 5. Auto-cleanup delivered parcels past the threshold
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
                if tid in manual:
                    manual.pop(tid)
                config_changed = True

        # 6. Batch-write config entry if anything changed
        if config_changed:
            data[CONF_MANUAL_TRACKING] = manual
            data[CONF_DELIVERED_TIMESTAMPS] = {
                tid: ts.isoformat()
                for tid, ts in self._delivered_timestamps.items()
            }
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=data
            )

        return shipments
