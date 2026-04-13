# Code Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 16 issues from the security, correctness, and UX code review to bring the integration up to HA best practices.

**Architecture:** Single coordinated pass across all integration files. Tasks ordered by dependency: API clients first (no dependencies), then coordinator (depends on API changes), then sensor (depends on coordinator), then __init__ (depends on coordinator), then config_flow, diagnostics, metadata, and translations last.

**Tech Stack:** Home Assistant custom integration, Python 3.14, aiohttp, voluptuous

**Spec:** `docs/superpowers/specs/2026-04-13-code-review-fixes-design.md`

---

## File Map

| File | Action | Changes |
|------|--------|---------|
| `api/helthjem.py` | Modify | URL-quote tracking_id, timezone-aware fallback |
| `api/postnord.py` | Modify | Timezone-aware fallback |
| `const.py` | Modify | Add CONF_DELIVERED_TIMESTAMPS |
| `coordinator.py` | Modify | Persist timestamps, batch updates, case normalization, carrier .value, UpdateFailed msg |
| `sensor.py` | Modify | ENUM device class, entity removal, drop events attr, drop icon prop, keep dynamic name |
| `__init__.py` | Modify | runtime_data, options listener, case normalization in services |
| `config_flow.py` | Modify | Remove aiohttp import, ConfigFlowResult, hash unique_ids, simplify OptionsFlow |
| `diagnostics.py` | Modify | Redact PII, use runtime_data |
| `manifest.json` | Modify | Remove aiohttp requirement |
| `icons.json` | Create | State-based icon mapping |
| `strings.json` | Modify | Add state translations, remove entity name template |
| `translations/en.json` | Modify | Mirror strings.json |
| `translations/nb.json` | Modify | Add Norwegian state translations |

---

### Task 1: Fix API client security and correctness issues

**Files:**
- Modify: `custom_components/nordic_parcel/api/helthjem.py`
- Modify: `custom_components/nordic_parcel/api/postnord.py`

- [ ] **Step 1: Fix Helthjem URL path injection**

In `custom_components/nordic_parcel/api/helthjem.py`, add `import urllib.parse` to the imports (after `import time`), then change the URL construction in `track_shipment`:

Replace line 201:
```python
        url = f"{TRACKING_URL}/{tracking_id}/EN/false"
```
With:
```python
        url = f"{TRACKING_URL}/{urllib.parse.quote(tracking_id, safe='')}/EN/false"
```

- [ ] **Step 2: Fix Helthjem naive datetime fallback**

In `custom_components/nordic_parcel/api/helthjem.py`, add `timezone` to the datetime import:

```python
from datetime import datetime, timezone
```

Then change line 113 in `_parse_event`:
```python
    except ValueError:
        timestamp = datetime.now()
```
To:
```python
    except ValueError:
        timestamp = datetime.now(timezone.utc)
```

- [ ] **Step 3: Fix Postnord naive datetime fallback**

In `custom_components/nordic_parcel/api/postnord.py`, add `timezone` to the datetime import:

```python
from datetime import datetime, timezone
```

Then change line 56 in `_parse_event`:
```python
    except ValueError:
        timestamp = datetime.now()
```
To:
```python
    except ValueError:
        timestamp = datetime.now(timezone.utc)
```

- [ ] **Step 4: Verify syntax**

Run:
```bash
python3 -c "
import ast
for f in ['custom_components/nordic_parcel/api/helthjem.py', 'custom_components/nordic_parcel/api/postnord.py']:
    with open(f) as fh: ast.parse(fh.read())
    print(f'{f} OK')
"
```

- [ ] **Step 5: Commit**

```bash
git add custom_components/nordic_parcel/api/helthjem.py custom_components/nordic_parcel/api/postnord.py
git commit -m "Fix Helthjem URL injection and naive datetime fallbacks"
```

---

### Task 2: Add const and fix coordinator correctness

**Files:**
- Modify: `custom_components/nordic_parcel/const.py`
- Modify: `custom_components/nordic_parcel/coordinator.py`

- [ ] **Step 1: Add CONF_DELIVERED_TIMESTAMPS to const.py**

In `custom_components/nordic_parcel/const.py`, add after `CONF_MANUAL_TRACKING` (line 20):

```python
CONF_DELIVERED_TIMESTAMPS: Final = "delivered_timestamps"
```

- [ ] **Step 2: Rewrite coordinator.py**

Replace the entire content of `custom_components/nordic_parcel/coordinator.py` with:

```python
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
```

- [ ] **Step 3: Verify syntax**

Run:
```bash
python3 -c "
import ast
for f in ['custom_components/nordic_parcel/const.py', 'custom_components/nordic_parcel/coordinator.py']:
    with open(f) as fh: ast.parse(fh.read())
    print(f'{f} OK')
"
```

- [ ] **Step 4: Commit**

```bash
git add custom_components/nordic_parcel/const.py custom_components/nordic_parcel/coordinator.py
git commit -m "Fix coordinator: persist timestamps, batch updates, case normalization"
```

---

### Task 3: Overhaul sensor.py — ENUM, entity removal, cleanup

**Files:**
- Modify: `custom_components/nordic_parcel/sensor.py`

- [ ] **Step 1: Replace sensor.py**

Replace the entire content of `custom_components/nordic_parcel/sensor.py` with:

```python
"""Sensor platform for Nordic Parcel integration."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Shipment
from .const import DOMAIN, ShipmentStatus
from .coordinator import NordicParcelCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Nordic Parcel sensors from a config entry."""
    coordinator: NordicParcelCoordinator = entry.runtime_data

    known_ids: set[str] = set()
    entity_id_map: dict[str, str] = {}  # tracking_id -> entity_id

    @callback
    def _async_add_new_entities() -> None:
        """Add sensors for newly discovered shipments."""
        if not coordinator.data:
            return

        new_entities = []
        current_ids = set(coordinator.data.keys())

        for tracking_id in current_ids - known_ids:
            sensor = NordicParcelSensor(coordinator, tracking_id)
            new_entities.append(sensor)
            known_ids.add(tracking_id)

        # Remove entities for cleaned-up shipments
        removed = known_ids - current_ids
        if removed:
            registry = er.async_get(hass)
            for tracking_id in removed:
                entity_id = entity_id_map.pop(tracking_id, None)
                if entity_id and registry.async_get(entity_id):
                    registry.async_remove(entity_id)
            known_ids.difference_update(removed)

        if new_entities:
            async_add_entities(new_entities)
            # Map tracking IDs to entity IDs after registration
            for sensor in new_entities:
                if sensor.entity_id:
                    entity_id_map[sensor._tracking_id] = sensor.entity_id

    _async_add_new_entities()

    entry.async_on_unload(
        coordinator.async_add_listener(_async_add_new_entities)
    )


class NordicParcelSensor(CoordinatorEntity[NordicParcelCoordinator], SensorEntity):
    """Sensor representing a tracked parcel."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [s.value for s in ShipmentStatus]

    def __init__(
        self,
        coordinator: NordicParcelCoordinator,
        tracking_id: str,
    ) -> None:
        super().__init__(coordinator, context=tracking_id)
        self._tracking_id = tracking_id
        self._attr_unique_id = f"{DOMAIN}_{tracking_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name=coordinator.config_entry.title,
            manufacturer=coordinator.client.carrier.value.title(),
            model="Parcel Tracking",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _shipment(self) -> Shipment | None:
        """Get the current shipment data from coordinator."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._tracking_id)

    @property
    def available(self) -> bool:
        """Return True if the shipment data is available."""
        return super().available and self._shipment is not None

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        shipment = self._shipment
        if shipment and shipment.sender:
            return f"{shipment.sender} ({self._tracking_id[-6:]})"
        return self._tracking_id

    @property
    def native_value(self) -> str | None:
        """Return the shipment status as the sensor state."""
        shipment = self._shipment
        if not shipment:
            return None
        return shipment.status.value

    @property
    def extra_state_attributes(self) -> dict:
        """Return detailed shipment attributes."""
        shipment = self._shipment
        if not shipment:
            return {}

        attrs = {
            "carrier": shipment.carrier.value,
            "tracking_id": shipment.tracking_id,
            "sender": shipment.sender,
            "recipient": shipment.recipient,
            "estimated_delivery": (
                shipment.estimated_delivery.isoformat()
                if shipment.estimated_delivery
                else None
            ),
            "event_count": len(shipment.events),
        }

        last = shipment.last_event
        if last:
            attrs["last_event_description"] = last.description
            attrs["last_event_time"] = last.timestamp.isoformat()
            attrs["last_event_location"] = last.location

        return attrs
```

- [ ] **Step 2: Verify syntax**

Run:
```bash
python3 -c "
import ast
with open('custom_components/nordic_parcel/sensor.py') as f: ast.parse(f.read())
print('sensor.py OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add custom_components/nordic_parcel/sensor.py
git commit -m "Overhaul sensor: ENUM device class, entity removal, drop events attr"
```

---

### Task 4: Update __init__.py — runtime_data, options listener, case normalization

**Files:**
- Modify: `custom_components/nordic_parcel/__init__.py`

- [ ] **Step 1: Replace __init__.py**

Replace the entire content of `custom_components/nordic_parcel/__init__.py` with:

```python
"""Nordic Parcel — Track parcels from Bring, Postnord, and Helthjem."""

from __future__ import annotations

import logging
from datetime import timedelta

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.bring import BringApiClient
from .api.helthjem import HelthjemApiClient
from .api.postnord import PostnordApiClient
from .const import (
    CONF_API_KEY,
    CONF_API_UID,
    CONF_CARRIER,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    Carrier,
)
from .coordinator import NordicParcelCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

SERVICE_ADD_TRACKING = "add_tracking"
SERVICE_REMOVE_TRACKING = "remove_tracking"

SERVICE_ADD_SCHEMA = vol.Schema(
    {
        vol.Required("tracking_id"): str,
        vol.Optional("carrier"): vol.In(
            [Carrier.BRING, Carrier.POSTNORD, Carrier.HELTHJEM]
        ),
    }
)

SERVICE_REMOVE_SCHEMA = vol.Schema(
    {
        vol.Required("tracking_id"): str,
    }
)


def _create_client(
    hass: HomeAssistant, entry: ConfigEntry
) -> BringApiClient | PostnordApiClient | HelthjemApiClient:
    """Create the appropriate API client for a config entry."""
    session = async_get_clientsession(hass)
    carrier = Carrier(entry.data[CONF_CARRIER])

    if carrier == Carrier.BRING:
        return BringApiClient(
            session,
            entry.data[CONF_API_UID],
            entry.data[CONF_API_KEY],
        )
    if carrier == Carrier.POSTNORD:
        return PostnordApiClient(session, entry.data[CONF_API_KEY])
    return HelthjemApiClient(
        session,
        entry.data[CONF_CLIENT_ID],
        entry.data[CONF_CLIENT_SECRET],
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Nordic Parcel from a config entry."""
    client = _create_client(hass, entry)
    coordinator = NordicParcelCoordinator(hass, entry, client)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services (once, when first entry loads)
    if not hass.services.has_service(DOMAIN, SERVICE_ADD_TRACKING):
        _register_services(hass)

    # Listen for options changes to update scan interval
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    coordinator: NordicParcelCoordinator = entry.runtime_data
    coordinator.update_interval = timedelta(
        seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Unregister services if no entries remain
    remaining = [
        e for e in hass.config_entries.async_entries(DOMAIN)
        if e.entry_id != entry.entry_id
    ]
    if not remaining:
        hass.services.async_remove(DOMAIN, SERVICE_ADD_TRACKING)
        hass.services.async_remove(DOMAIN, SERVICE_REMOVE_TRACKING)

    return unload_ok


def _register_services(hass: HomeAssistant) -> None:
    """Register integration services."""

    async def handle_add_tracking(call: ServiceCall) -> None:
        """Handle the add_tracking service call."""
        tracking_id = call.data["tracking_id"].upper()
        carrier_filter = call.data.get("carrier")

        coordinators: list[NordicParcelCoordinator] = [
            entry.runtime_data
            for entry in hass.config_entries.async_entries(DOMAIN)
            if hasattr(entry, "runtime_data") and entry.runtime_data
        ]

        if carrier_filter:
            coordinators = [
                c for c in coordinators if c.client.carrier == carrier_filter
            ]

        if not coordinators:
            _LOGGER.error(
                "No matching carrier configured for tracking %s", tracking_id
            )
            return

        await coordinators[0].add_tracking(tracking_id)

    async def handle_remove_tracking(call: ServiceCall) -> None:
        """Handle the remove_tracking service call."""
        tracking_id = call.data["tracking_id"].upper()

        for entry in hass.config_entries.async_entries(DOMAIN):
            if not hasattr(entry, "runtime_data") or not entry.runtime_data:
                continue
            coordinator: NordicParcelCoordinator = entry.runtime_data
            if tracking_id in coordinator.manual_tracking_ids:
                await coordinator.remove_tracking(tracking_id)
                return

        _LOGGER.warning("Tracking ID %s not found in any carrier", tracking_id)

    hass.services.async_register(
        DOMAIN, SERVICE_ADD_TRACKING, handle_add_tracking, schema=SERVICE_ADD_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_TRACKING,
        handle_remove_tracking,
        schema=SERVICE_REMOVE_SCHEMA,
    )
```

- [ ] **Step 2: Verify syntax**

Run:
```bash
python3 -c "
import ast
with open('custom_components/nordic_parcel/__init__.py') as f: ast.parse(f.read())
print('__init__.py OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add custom_components/nordic_parcel/__init__.py
git commit -m "Update __init__: runtime_data, options listener, case normalization"
```

---

### Task 5: Update config_flow.py — imports, hash IDs, OptionsFlow

**Files:**
- Modify: `custom_components/nordic_parcel/config_flow.py`

- [ ] **Step 1: Fix imports**

In `custom_components/nordic_parcel/config_flow.py`:

Remove line 8 (`import aiohttp`).

Change line 12:
```python
from homeassistant.data_entry_flow import FlowResult
```
To:
```python
import hashlib
```

Change all `-> FlowResult:` return type annotations to `-> ConfigFlowResult:`.

Add `ConfigFlowResult` to the import from `homeassistant.config_entries`:
```python
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
```

- [ ] **Step 2: Hash-based unique IDs for Postnord and Helthjem**

Replace the Postnord unique_id line (inside `async_step_postnord`):
```python
                    await self.async_set_unique_id(
                        f"postnord_{user_input[CONF_API_KEY][:8]}"
                    )
```
With:
```python
                    await self.async_set_unique_id(
                        f"postnord_{hashlib.sha256(user_input[CONF_API_KEY].encode()).hexdigest()[:8]}"
                    )
```

Replace the Helthjem unique_id line (inside `async_step_helthjem`):
```python
                    await self.async_set_unique_id(
                        f"helthjem_{user_input[CONF_CLIENT_ID][:8]}"
                    )
```
With:
```python
                    await self.async_set_unique_id(
                        f"helthjem_{hashlib.sha256(user_input[CONF_CLIENT_ID].encode()).hexdigest()[:8]}"
                    )
```

- [ ] **Step 3: Simplify NordicParcelOptionsFlow**

Replace the `NordicParcelOptionsFlow` class with:

```python
class NordicParcelOptionsFlow(OptionsFlow):
    """Handle options for Nordic Parcel."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage integration options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=60, max=86400)),
                    vol.Optional(
                        CONF_CLEANUP_DAYS,
                        default=self.config_entry.options.get(
                            CONF_CLEANUP_DAYS, DEFAULT_CLEANUP_DAYS
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=30)),
                }
            ),
        )
```

- [ ] **Step 4: Verify syntax**

Run:
```bash
python3 -c "
import ast
with open('custom_components/nordic_parcel/config_flow.py') as f: ast.parse(f.read())
print('config_flow.py OK')
"
```

- [ ] **Step 5: Commit**

```bash
git add custom_components/nordic_parcel/config_flow.py
git commit -m "Update config_flow: remove aiohttp, hash unique_ids, ConfigFlowResult"
```

---

### Task 6: Update diagnostics.py — PII redaction, runtime_data

**Files:**
- Modify: `custom_components/nordic_parcel/diagnostics.py`

- [ ] **Step 1: Replace diagnostics.py**

Replace the entire content of `custom_components/nordic_parcel/diagnostics.py` with:

```python
"""Diagnostics support for Nordic Parcel integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_API_KEY, CONF_API_UID, CONF_CLIENT_ID, CONF_CLIENT_SECRET
from .coordinator import NordicParcelCoordinator

TO_REDACT = {CONF_API_KEY, CONF_API_UID, CONF_CLIENT_ID, CONF_CLIENT_SECRET}


def _mask_tracking_id(tracking_id: str) -> str:
    """Partially mask a tracking ID, showing only last 4 characters."""
    if len(tracking_id) <= 4:
        return tracking_id
    return "*" * (len(tracking_id) - 4) + tracking_id[-4:]


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: NordicParcelCoordinator = entry.runtime_data

    shipments_data = {}
    if coordinator.data:
        for tracking_id, shipment in coordinator.data.items():
            masked_id = _mask_tracking_id(tracking_id)
            shipments_data[masked_id] = {
                "carrier": shipment.carrier.value,
                "status": shipment.status.value,
                "sender": "**REDACTED**" if shipment.sender else None,
                "recipient": "**REDACTED**" if shipment.recipient else None,
                "estimated_delivery": (
                    shipment.estimated_delivery.isoformat()
                    if shipment.estimated_delivery
                    else None
                ),
                "event_count": len(shipment.events),
                "events": [
                    {
                        "timestamp": e.timestamp.isoformat(),
                        "description": e.description,
                        "location": "**REDACTED**" if e.location else None,
                        "status": e.status.value,
                    }
                    for e in shipment.events
                ],
            }

    return {
        "config_entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "coordinator_data": shipments_data,
    }
```

- [ ] **Step 2: Verify syntax**

Run:
```bash
python3 -c "
import ast
with open('custom_components/nordic_parcel/diagnostics.py') as f: ast.parse(f.read())
print('diagnostics.py OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add custom_components/nordic_parcel/diagnostics.py
git commit -m "Redact PII in diagnostics and use runtime_data"
```

---

### Task 7: Create icons.json, update translations, fix manifest

**Files:**
- Create: `custom_components/nordic_parcel/icons.json`
- Modify: `custom_components/nordic_parcel/manifest.json`
- Modify: `custom_components/nordic_parcel/strings.json`
- Modify: `custom_components/nordic_parcel/translations/en.json`
- Modify: `custom_components/nordic_parcel/translations/nb.json`

- [ ] **Step 1: Create icons.json**

Create `custom_components/nordic_parcel/icons.json`:

```json
{
  "entity": {
    "sensor": {
      "parcel": {
        "default": "mdi:package-variant",
        "state": {
          "unknown": "mdi:package-variant",
          "pre_transit": "mdi:package-variant-closed",
          "in_transit": "mdi:truck-delivery",
          "out_for_delivery": "mdi:truck-fast",
          "ready_for_pickup": "mdi:mailbox-up",
          "delivered": "mdi:package-variant-closed-check",
          "returned": "mdi:package-variant-closed-minus",
          "failed": "mdi:package-variant-closed-remove"
        }
      }
    }
  }
}
```

- [ ] **Step 2: Update manifest.json — remove aiohttp requirement**

In `custom_components/nordic_parcel/manifest.json`, change:
```json
  "requirements": ["aiohttp>=3.9.0"],
```
To:
```json
  "requirements": [],
```

- [ ] **Step 3: Update strings.json — add state translations**

In `custom_components/nordic_parcel/strings.json`, replace the `"entity"` section with:

```json
  "entity": {
    "sensor": {
      "parcel": {
        "state": {
          "unknown": "Unknown",
          "pre_transit": "Pre-transit",
          "in_transit": "In transit",
          "out_for_delivery": "Out for delivery",
          "ready_for_pickup": "Ready for pickup",
          "delivered": "Delivered",
          "returned": "Returned",
          "failed": "Failed"
        }
      }
    }
  }
```

- [ ] **Step 4: Update translations/en.json**

Replace `translations/en.json` with an exact copy of the updated `strings.json`.

- [ ] **Step 5: Update translations/nb.json — add state translations**

In `custom_components/nordic_parcel/translations/nb.json`, replace the `"entity"` section with:

```json
  "entity": {
    "sensor": {
      "parcel": {
        "state": {
          "unknown": "Ukjent",
          "pre_transit": "Forhåndsvarslet",
          "in_transit": "Under transport",
          "out_for_delivery": "Ute for levering",
          "ready_for_pickup": "Klar for henting",
          "delivered": "Levert",
          "returned": "Returnert",
          "failed": "Mislykket"
        }
      }
    }
  }
```

- [ ] **Step 6: Verify JSON files**

Run:
```bash
python3 -c "
import json
for f in [
    'custom_components/nordic_parcel/icons.json',
    'custom_components/nordic_parcel/manifest.json',
    'custom_components/nordic_parcel/strings.json',
    'custom_components/nordic_parcel/translations/en.json',
    'custom_components/nordic_parcel/translations/nb.json',
]:
    with open(f) as fh: json.load(fh)
    print(f'{f} OK')
"
```

- [ ] **Step 7: Verify strings.json and en.json match**

Run:
```bash
diff custom_components/nordic_parcel/strings.json custom_components/nordic_parcel/translations/en.json
```
Expected: no output.

- [ ] **Step 8: Commit**

```bash
git add custom_components/nordic_parcel/icons.json custom_components/nordic_parcel/manifest.json custom_components/nordic_parcel/strings.json custom_components/nordic_parcel/translations/en.json custom_components/nordic_parcel/translations/nb.json
git commit -m "Add icons.json, state translations, remove aiohttp requirement"
```

---

### Task 8: Final verification

- [ ] **Step 1: Verify all Python files parse**

Run:
```bash
python3 -c "
import ast, pathlib
for f in pathlib.Path('custom_components/nordic_parcel').rglob('*.py'):
    if '__pycache__' in str(f): continue
    with open(f) as fh: ast.parse(fh.read())
    print(f'{f} OK')
"
```

- [ ] **Step 2: Verify no hass.data[DOMAIN] references remain**

Run:
```bash
grep -rn 'hass\.data\[DOMAIN\]' custom_components/nordic_parcel/ --include='*.py' || echo "No hass.data[DOMAIN] references found — good"
```

- [ ] **Step 3: Verify no FlowResult references remain**

Run:
```bash
grep -rn 'FlowResult' custom_components/nordic_parcel/ --include='*.py' || echo "No FlowResult references found — good"
```

- [ ] **Step 4: Verify no import aiohttp in config_flow**

Run:
```bash
grep -n 'import aiohttp' custom_components/nordic_parcel/config_flow.py || echo "No aiohttp import — good"
```

- [ ] **Step 5: Verify native_value returns raw enum values**

Run:
```bash
grep -A3 'def native_value' custom_components/nordic_parcel/sensor.py
```
Expected: should show `return shipment.status.value` (no `.replace` or `.title()`).

- [ ] **Step 6: Verify tracking IDs are uppercased at entry points**

Run:
```bash
grep -n '\.upper()' custom_components/nordic_parcel/coordinator.py custom_components/nordic_parcel/__init__.py
```
Expected: should show `.upper()` calls in add_tracking, remove_tracking, service handlers, and track_shipment result handling.
