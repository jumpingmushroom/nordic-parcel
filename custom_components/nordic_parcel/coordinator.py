"""DataUpdateCoordinator for Nordic Parcel integration."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    CarrierApiError,
    CarrierAuthError,
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

# Statuses that fire a dedicated event in addition to the generic status_changed event
_GRANULAR_EVENTS: dict[ShipmentStatus, str] = {
    ShipmentStatus.OUT_FOR_DELIVERY: f"{DOMAIN}_out_for_delivery",
    ShipmentStatus.READY_FOR_PICKUP: f"{DOMAIN}_ready_for_pickup",
    ShipmentStatus.RETURNED: f"{DOMAIN}_returned",
    ShipmentStatus.FAILED: f"{DOMAIN}_failed",
    ShipmentStatus.CUSTOMS: f"{DOMAIN}_customs",
}

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
        scan_interval = config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
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
                _LOGGER.warning("Invalid delivered timestamp for %s: %s", tid, ts_str)
        self._previous_statuses: dict[str, str] = {}

    @property
    def manual_tracking_ids(self) -> list[str]:
        """Return manually-added tracking IDs from config entry data."""
        return list(self.config_entry.data.get(CONF_MANUAL_TRACKING, {}).keys())

    async def add_tracking(self, tracking_id: str) -> None:
        """Add a tracking number to manual tracking list."""
        tracking_id = tracking_id.strip().upper()
        data = dict(self.config_entry.data)
        manual = dict(data.get(CONF_MANUAL_TRACKING, {}))
        manual[tracking_id] = {"added": datetime.now(UTC).isoformat()}
        data[CONF_MANUAL_TRACKING] = manual
        self.hass.config_entries.async_update_entry(self.config_entry, data=data)
        await self.async_request_refresh()

    async def remove_tracking(self, tracking_id: str) -> None:
        """Remove a tracking number from manual tracking list."""
        tracking_id = tracking_id.strip().upper()
        data = dict(self.config_entry.data)
        manual = dict(data.get(CONF_MANUAL_TRACKING, {}))
        manual.pop(tracking_id, None)
        data[CONF_MANUAL_TRACKING] = manual
        self.hass.config_entries.async_update_entry(self.config_entry, data=data)
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
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"auth_failed_{self.config_entry.entry_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="auth_failed",
                translation_placeholders={"carrier": self.client.carrier.value},
            )
            raise ConfigEntryAuthFailed from err
        except CarrierRateLimitError as err:
            raise UpdateFailed("Rate limited by carrier API") from err
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
                        tracking_id,
                        ", ".join(result_ids),
                    )
            except CarrierAuthError as err:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    f"auth_failed_{self.config_entry.entry_id}",
                    is_fixable=False,
                    severity=ir.IssueSeverity.ERROR,
                    translation_key="auth_failed",
                    translation_placeholders={"carrier": self.client.carrier.value},
                )
                raise ConfigEntryAuthFailed from err
            except CarrierRateLimitError as err:
                raise UpdateFailed("Rate limited by carrier API") from err
            except CarrierNotFoundError:
                _LOGGER.debug("Tracking ID %s not found, skipping", tracking_id)
            except CarrierApiError as err:
                _LOGGER.warning("Failed to track %s: %s", tracking_id, err)

        # 3. Fire status change events
        for tid, shipment in shipments.items():
            old_status = self._previous_statuses.get(tid)
            new_status = shipment.status.value
            if old_status is not None and old_status != new_status:
                event_data = {
                    "tracking_id": tid,
                    "carrier": shipment.carrier.value,
                    "sender": shipment.sender,
                    "old_status": old_status,
                    "new_status": new_status,
                }
                self.hass.bus.async_fire(
                    f"{DOMAIN}_status_changed",
                    event_data,
                )
                # Fire granular event for specific status transitions
                granular_event = _GRANULAR_EVENTS.get(shipment.status)
                if granular_event:
                    self.hass.bus.async_fire(granular_event, event_data)
            self._previous_statuses[tid] = new_status

        # 3.5 Detect repair issues
        now = datetime.now(UTC)
        for tid, shipment in shipments.items():
            # Stale tracking: no update for 14+ days, not delivered
            stale_issue_id = f"stale_tracking_{tid}"
            last = shipment.last_event
            if (
                last
                and shipment.status != ShipmentStatus.DELIVERED
                and (now - last.timestamp).days >= 14
            ):
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    stale_issue_id,
                    is_fixable=True,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="stale_tracking",
                    translation_placeholders={
                        "tracking_id": tid,
                        "carrier": shipment.carrier.value,
                        "days": str((now - last.timestamp).days),
                    },
                    data={"tracking_id": tid, "carrier": shipment.carrier.value},
                )
            else:
                ir.async_delete_issue(self.hass, DOMAIN, stale_issue_id)

            # Stuck in customs: 7+ days
            customs_issue_id = f"stuck_customs_{tid}"
            if (
                shipment.status == ShipmentStatus.CUSTOMS
                and last
                and (now - last.timestamp).days >= 7
            ):
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    customs_issue_id,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="stuck_customs",
                    translation_placeholders={
                        "tracking_id": tid,
                        "carrier": shipment.carrier.value,
                        "days": str((now - last.timestamp).days),
                    },
                )
            else:
                ir.async_delete_issue(self.hass, DOMAIN, customs_issue_id)

        # 4. Track delivery timestamps
        for tid, shipment in shipments.items():
            if shipment.status == ShipmentStatus.DELIVERED:
                if tid not in self._delivered_timestamps:
                    self._delivered_timestamps[tid] = datetime.now(UTC)
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
        cleanup_days = self.config_entry.options.get(CONF_CLEANUP_DAYS, DEFAULT_CLEANUP_DAYS)
        if cleanup_days > 0:
            now = datetime.now(UTC)
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
            # Re-read config entry data to avoid overwriting concurrent changes
            # from add_tracking/remove_tracking that ran during API calls above
            fresh_data = dict(self.config_entry.data)
            fresh_data[CONF_MANUAL_TRACKING] = manual
            fresh_data[CONF_DELIVERED_TIMESTAMPS] = {
                tid: ts.isoformat() for tid, ts in self._delivered_timestamps.items()
            }
            self.hass.config_entries.async_update_entry(self.config_entry, data=fresh_data)

        return shipments
