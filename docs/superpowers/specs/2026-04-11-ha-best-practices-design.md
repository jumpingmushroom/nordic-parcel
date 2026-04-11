# Nordic Parcel: HA Best Practices Compliance

Bring the integration up to Home Assistant best practices by filling in missing infrastructure and fixing incomplete areas.

## Scope

Items addressed (from gap analysis):

**Missing entirely:**
1. `strings.json` — canonical English string source
2. `diagnostics.py` — debug info export for users
3. Device info — group sensors under carrier devices

**Incomplete:**
4. Manifest placeholders — codeowners, URLs, integration_type
5. `hacs.json` — missing minimum HA version
6. Reauth flow — no pre-fill, no context message, creates new entry instead of updating
7. Service translations — services not translatable

**Out of scope:** Tests, CI/CD, reconfigure flow, entity registry cleanup, SensorDeviceClass.

---

## 1. strings.json + Translation Pipeline

**New file:** `custom_components/nordic_parcel/strings.json`

Create from current `translations/en.json` content, extended with:

- **Service strings** under `"services"` key:
  ```json
  "services": {
    "add_tracking": {
      "name": "Add tracking",
      "description": "Add a parcel tracking number to monitor.",
      "fields": {
        "tracking_id": {
          "name": "Tracking ID",
          "description": "The parcel tracking number."
        },
        "carrier": {
          "name": "Carrier",
          "description": "Which carrier to track with. If omitted, uses the first configured carrier."
        }
      }
    },
    "remove_tracking": {
      "name": "Remove tracking",
      "description": "Stop tracking a parcel.",
      "fields": {
        "tracking_id": {
          "name": "Tracking ID",
          "description": "The tracking number to remove."
        }
      }
    }
  }
  ```

- **Reauth step strings** under `"config.step"` (see Section 4 for details)

**File changes:**
- `translations/en.json` — becomes a copy of `strings.json`
- `translations/nb.json` — add Norwegian translations for new service + reauth keys

---

## 2. Device Info

Each config entry registers as a service device. Sensors group under it.

**File:** `custom_components/nordic_parcel/sensor.py`

Add `device_info` property to `NordicParcelSensor`:

```python
@property
def device_info(self) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
        name=self.coordinator.config_entry.title,
        manufacturer=self.coordinator.client.carrier.value.title(),
        model="Parcel Tracking",
        entry_type=DeviceEntryType.SERVICE,
    )
```

**Entity naming update:**

With device info, `has_entity_name=True` makes the entity name relative to the device. The carrier prefix moves out of the sensor name into the device name.

Updated `name` property:
```python
@property
def name(self) -> str:
    shipment = self._shipment
    if shipment and shipment.sender:
        return f"{shipment.sender} ({self._tracking_id[-6:]})"
    return self._tracking_id
```

Result: Device "Bring (user@email.com)" contains sensor "Yanwen Logistics (0014no)".

---

## 3. Diagnostics

**New file:** `custom_components/nordic_parcel/diagnostics.py`

Implements `async_get_config_entry_diagnostics`.

**Redaction:** Uses `async_redact_data()` with:
```python
TO_REDACT = {CONF_API_KEY, CONF_API_UID, CONF_CLIENT_ID, CONF_CLIENT_SECRET}
```

**Output structure:**
```python
{
    "config_entry": {
        # Full entry dict with credentials replaced by **REDACTED**
    },
    "coordinator_data": {
        "<tracking_id>": {
            "carrier": "bring",
            "status": "in_transit",
            "sender": "...",
            "recipient": "...",
            "estimated_delivery": "...",
            "event_count": 5,
            "events": [
                {
                    "timestamp": "...",
                    "description": "...",
                    "location": "...",
                    "status": "..."
                }
            ]
        }
    }
}
```

---

## 4. Manifest, HACS, and Reauth

### manifest.json

```json
{
  "domain": "nordic_parcel",
  "name": "Nordic Parcel",
  "codeowners": ["@jumpingmushroom"],
  "config_flow": true,
  "documentation": "https://github.com/jumpingmushroom/nordic-parcel",
  "integration_type": "service",
  "iot_class": "cloud_polling",
  "issue_tracker": "https://github.com/jumpingmushroom/nordic-parcel/issues",
  "requirements": ["aiohttp>=3.9.0"],
  "version": "0.1.0"
}
```

### hacs.json

```json
{
  "name": "Nordic Parcel",
  "homeassistant": "2024.1.0",
  "render_readme": true
}
```

### Reauth Flow

**Current problem:** `async_step_reauth` routes directly to the setup steps, which create new entries instead of updating the existing one. No pre-fill, no context.

**Fix:** Create dedicated reauth steps per carrier:

- `async_step_reauth` — stores reauth entry reference, routes to `async_step_reauth_bring` / `_postnord` / `_helthjem`
- Each reauth step:
  - Pre-fills non-secret identifiers (API UID for Bring, Client ID for Helthjem) as default values in the schema
  - Shows reauth-specific description string explaining credentials expired
  - On successful auth, calls `self.async_update_reload_and_abort()` to update the existing entry

**New translation strings for reauth steps:**
```json
"reauth_confirm": {
  "title": "Re-authenticate {carrier}",
  "description": "Your {carrier} credentials have expired or become invalid. Please re-enter them."
},
"reauth_bring": {
  "title": "Re-authenticate Bring",
  "description": "Please re-enter your Mybring API credentials.",
  "data": {
    "api_uid": "Mybring email",
    "api_key": "API key"
  }
},
"reauth_postnord": { ... },
"reauth_helthjem": { ... }
```

### Service Translations

Add `"services"` key to `strings.json`, `translations/en.json`, and `translations/nb.json` as described in Section 1.

---

## Files Modified

| File | Change |
|------|--------|
| `strings.json` | **New** — canonical English strings with services + reauth |
| `translations/en.json` | Copy of strings.json |
| `translations/nb.json` | Add service + reauth translations |
| `sensor.py` | Add device_info, update name property |
| `diagnostics.py` | **New** — config entry diagnostics |
| `manifest.json` | Fix codeowners, URLs, add integration_type |
| `hacs.json` | Add homeassistant minimum version |
| `config_flow.py` | Reauth: dedicated steps, pre-fill, update-and-reload |

## Verification

1. Load integration in HA dev environment
2. Confirm sensors appear under a device in the device registry
3. Confirm device name matches config entry title
4. Download diagnostics from the integration page — verify credentials are redacted, shipment data present
5. Trigger reauth (temporarily invalidate credentials) — verify pre-fill and context message appear
6. Check Developer Tools > Services — verify service descriptions are translated
7. Verify `strings.json` and `translations/en.json` have identical structure
8. Validate manifest with `python -m script.hassfest` if available, or manual review
