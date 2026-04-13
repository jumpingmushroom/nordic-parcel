# Code Review Fixes — Design Spec

Comprehensive fixes from security, correctness, and UX review. 16 items across critical, important, and minor severity.

## Files Modified

| File | Changes |
|------|---------|
| `sensor.py` | ENUM device class, entity removal, drop events attr, drop icon property, translation-based naming |
| `coordinator.py` | Persist delivered timestamps, batch config updates, case normalization, carrier .value fix, UpdateFailed message, step renumbering |
| `__init__.py` | runtime_data pattern, options update listener, case normalization in services |
| `config_flow.py` | Remove unused aiohttp import, FlowResult→ConfigFlowResult, hash-based unique_ids, OptionsFlow simplification |
| `api/helthjem.py` | URL-quote tracking_id, timezone-aware datetime fallback |
| `api/postnord.py` | Timezone-aware datetime fallback |
| `diagnostics.py` | Redact PII (sender, recipient, partial tracking IDs), use runtime_data |
| `manifest.json` | Remove aiohttp from requirements |
| `icons.json` | New — state-based icon mapping |
| `strings.json` | Add state translations for ShipmentStatus values |
| `translations/en.json` | Mirror strings.json |
| `translations/nb.json` | Add Norwegian state translations |

## 1. sensor.py — Entity quality overhaul

### SensorDeviceClass.ENUM
- Add `_attr_device_class = SensorDeviceClass.ENUM`
- Add `_attr_options = [s.value for s in ShipmentStatus]`
- `native_value` returns raw `shipment.status.value` (e.g. `"in_transit"`)
- State display handled via translations, not Python string formatting

### Entity removal
- Store `entity_registry` reference and entity_id on init
- On coordinator update, when a tracking ID disappears from data, call `entity_registry.async_remove(entity_id)` in the `_async_add_new_entities` callback
- Properly clean up `known_ids`

### Drop events from state attributes
- Remove `events` list from `extra_state_attributes`
- Keep: `carrier`, `tracking_id`, `sender`, `recipient`, `estimated_delivery`, `event_count`, `last_event_description`, `last_event_time`, `last_event_location`

### Icon → icons.json
- Remove `icon` property from class
- Create `icons.json` with per-state icon mapping

### Entity naming
- Keep dynamic `name` property but simplify: return sender + last 6 of tracking ID when available, otherwise full tracking ID
- Remove `_attr_translation_key` (dynamic name takes precedence and is more informative than a static template)
- The `name` property combined with `has_entity_name=True` and `device_info` produces clean names like "Device: Sender (ABC123)"

## 2. coordinator.py — Correctness fixes

### Persist delivered timestamps
- New const: `CONF_DELIVERED_TIMESTAMPS = "delivered_timestamps"`
- Load from `config_entry.data` on init
- Save back when timestamps change (as part of the batched config update)

### Batch config mutations
- Collect all manual tracking changes into a local `manual` dict
- Track whether `manual` or `delivered_timestamps` changed via a `config_changed` flag
- Single `async_update_entry` call at end of `_async_update_data` if anything changed

### Case normalization
- `add_tracking`: normalize tracking_id to uppercase before storing
- `remove_tracking`: normalize to uppercase
- `_async_update_data`: normalize result tracking IDs when comparing/storing

### Other fixes
- Line 176: `shipment.carrier` → `shipment.carrier.value`
- `UpdateFailed(retry_after=120)` → `UpdateFailed("Rate limited by carrier API")`
- Fix step comment numbering: 1, 2, 3, 4, 5

## 3. API clients

### helthjem.py
- `url = f"{TRACKING_URL}/{urllib.parse.quote(tracking_id, safe='')}/EN/false"` — prevent path injection
- `datetime.now()` → `datetime.now(timezone.utc)` at line 113

### postnord.py
- `datetime.now()` → `datetime.now(timezone.utc)` at line 56

## 4. __init__.py

### runtime_data pattern
- Replace `hass.data.setdefault(DOMAIN, {})` / `hass.data[DOMAIN][entry.entry_id]` with `entry.runtime_data`
- Remove `hass.data` cleanup from `async_unload_entry`
- Update service handlers to iterate `hass.config_entries.async_entries(DOMAIN)` and access `entry.runtime_data`

### Options update listener
```python
entry.async_on_unload(entry.add_update_listener(_async_options_updated))
```
Updates `coordinator.update_interval` when scan_interval changes.

### Case normalization in services
- `handle_add_tracking`: normalize tracking_id to uppercase
- `handle_remove_tracking`: normalize tracking_id to uppercase

## 5. config_flow.py

- Remove `import aiohttp` (line 8)
- `FlowResult` → `ConfigFlowResult`
- Postnord unique_id: `hashlib.sha256(key.encode()).hexdigest()[:8]` instead of `key[:8]`
- Helthjem unique_id: same hash approach for `client_id`
- `NordicParcelOptionsFlow`: remove `__init__`, use `self.config_entry` directly

## 6. diagnostics.py

- Add `"sender"`, `"recipient"` to `TO_REDACT`
- Partially mask tracking IDs: show only last 4 chars (e.g. `"****3456"`)
- Use `entry.runtime_data` instead of `hass.data[DOMAIN]`

## 7. manifest.json

- Remove `"aiohttp>=3.9.0"` from `requirements` (HA provides it)

## 8. New files

### icons.json
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

### strings.json state translations (addition)
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

### nb.json state translations (addition)
```json
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
```

## Verification

1. Syntax check all Python files
2. Verify `strings.json` and `en.json` are identical
3. Verify `nb.json` has all keys from `en.json`
4. Verify `icons.json` is valid JSON with all status values
5. Verify no `hass.data[DOMAIN]` references remain
6. Verify no `import aiohttp` in config_flow.py
7. Verify no `FlowResult` references (should be `ConfigFlowResult`)
8. Verify `native_value` returns raw enum values
9. Verify tracking IDs are uppercased at entry points
