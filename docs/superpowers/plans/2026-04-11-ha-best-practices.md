# HA Best Practices Compliance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring Nordic Parcel integration up to Home Assistant best practices — add strings.json, diagnostics, device_info, fix manifest/hacs metadata, improve reauth flow, and add service translations.

**Architecture:** Seven changes across 8 files. Each task is independent except Task 2 (device_info) affects the sensor name logic, and Task 4 (reauth) adds translation keys consumed by Task 1. Tasks should be done in order 1-7 to avoid merge conflicts in shared files.

**Tech Stack:** Home Assistant custom integration, Python, voluptuous, aiohttp

**Spec:** `docs/superpowers/specs/2026-04-11-ha-best-practices-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `custom_components/nordic_parcel/strings.json` | Create | Canonical English strings |
| `custom_components/nordic_parcel/translations/en.json` | Modify | Copy of strings.json |
| `custom_components/nordic_parcel/translations/nb.json` | Modify | Norwegian translations |
| `custom_components/nordic_parcel/diagnostics.py` | Create | Debug info export |
| `custom_components/nordic_parcel/sensor.py` | Modify | Add device_info, update name |
| `custom_components/nordic_parcel/manifest.json` | Modify | Fix metadata |
| `hacs.json` | Modify | Add HA min version |
| `custom_components/nordic_parcel/config_flow.py` | Modify | Reauth improvements |

---

### Task 1: Create strings.json and add service translations

**Files:**
- Create: `custom_components/nordic_parcel/strings.json`
- Modify: `custom_components/nordic_parcel/translations/en.json`
- Modify: `custom_components/nordic_parcel/translations/nb.json`

- [ ] **Step 1: Create strings.json**

Create `custom_components/nordic_parcel/strings.json` with the full content from `translations/en.json` plus the new `services` section. This is the canonical English string source.

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Nordic Parcel",
        "description": "Select the parcel carrier to set up.",
        "data": {
          "carrier": "Carrier"
        }
      },
      "bring": {
        "title": "Bring (Posten Norge)",
        "description": "Enter your Mybring API credentials. Get them at {docs_url}",
        "data": {
          "api_uid": "Mybring email",
          "api_key": "API key"
        }
      },
      "postnord": {
        "title": "Postnord",
        "description": "Enter your Postnord API key. Get one at {docs_url}",
        "data": {
          "api_key": "API key"
        }
      },
      "helthjem": {
        "title": "Helthjem",
        "description": "Enter your Helthjem API credentials. Contact integrations@helthjem.no or see {docs_url}",
        "data": {
          "client_id": "Client ID",
          "client_secret": "Client secret"
        }
      },
      "reauth_bring": {
        "title": "Re-authenticate Bring",
        "description": "Your Bring credentials have expired or become invalid. Please re-enter your API credentials.",
        "data": {
          "api_uid": "Mybring email",
          "api_key": "API key"
        }
      },
      "reauth_postnord": {
        "title": "Re-authenticate Postnord",
        "description": "Your Postnord credentials have expired or become invalid. Please re-enter your API key.",
        "data": {
          "api_key": "API key"
        }
      },
      "reauth_helthjem": {
        "title": "Re-authenticate Helthjem",
        "description": "Your Helthjem credentials have expired or become invalid. Please re-enter your API credentials.",
        "data": {
          "client_id": "Client ID",
          "client_secret": "Client secret"
        }
      }
    },
    "error": {
      "cannot_connect": "Failed to connect to the carrier API.",
      "invalid_auth": "Invalid credentials. Please check and try again.",
      "unknown": "An unexpected error occurred."
    },
    "abort": {
      "already_configured": "This carrier account is already configured.",
      "reauth_successful": "Re-authentication successful."
    }
  },
  "options": {
    "step": {
      "init": {
        "title": "Nordic Parcel Options",
        "data": {
          "scan_interval": "Update interval (seconds)",
          "cleanup_days": "Remove delivered parcels after (days, 0 = never)"
        }
      }
    }
  },
  "entity": {
    "sensor": {
      "parcel": {
        "name": "Parcel {tracking_id}"
      }
    }
  },
  "services": {
    "add_tracking": {
      "name": "Add tracking",
      "description": "Start tracking a parcel by its tracking number.",
      "fields": {
        "tracking_id": {
          "name": "Tracking ID",
          "description": "The tracking number from the carrier."
        },
        "carrier": {
          "name": "Carrier",
          "description": "Which carrier to use. If omitted, the tracking number is added to the first configured carrier."
        }
      }
    },
    "remove_tracking": {
      "name": "Remove tracking",
      "description": "Stop tracking a parcel and remove its sensor.",
      "fields": {
        "tracking_id": {
          "name": "Tracking ID",
          "description": "The tracking number to stop tracking."
        }
      }
    }
  }
}
```

- [ ] **Step 2: Update translations/en.json to match strings.json**

Replace the entire content of `custom_components/nordic_parcel/translations/en.json` with an exact copy of `strings.json` from Step 1.

- [ ] **Step 3: Update translations/nb.json with new keys**

Add the reauth steps, reauth abort, and services sections to `translations/nb.json`. The full file should be:

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Nordic Parcel",
        "description": "Velg pakketransportør for oppsett.",
        "data": {
          "carrier": "Transportør"
        }
      },
      "bring": {
        "title": "Bring (Posten Norge)",
        "description": "Skriv inn dine Mybring API-legitimasjoner. Hent dem på {docs_url}",
        "data": {
          "api_uid": "Mybring e-post",
          "api_key": "API-nøkkel"
        }
      },
      "postnord": {
        "title": "Postnord",
        "description": "Skriv inn din Postnord API-nøkkel. Hent en på {docs_url}",
        "data": {
          "api_key": "API-nøkkel"
        }
      },
      "helthjem": {
        "title": "Helthjem",
        "description": "Skriv inn dine Helthjem API-legitimasjoner. Kontakt integrations@helthjem.no eller se {docs_url}",
        "data": {
          "client_id": "Klient-ID",
          "client_secret": "Klienthemmelighet"
        }
      },
      "reauth_bring": {
        "title": "Autentiser Bring på nytt",
        "description": "Bring-legitimasjonene dine har utløpt eller blitt ugyldige. Vennligst skriv inn API-legitimasjonene dine på nytt.",
        "data": {
          "api_uid": "Mybring e-post",
          "api_key": "API-nøkkel"
        }
      },
      "reauth_postnord": {
        "title": "Autentiser Postnord på nytt",
        "description": "Postnord-legitimasjonene dine har utløpt eller blitt ugyldige. Vennligst skriv inn API-nøkkelen din på nytt.",
        "data": {
          "api_key": "API-nøkkel"
        }
      },
      "reauth_helthjem": {
        "title": "Autentiser Helthjem på nytt",
        "description": "Helthjem-legitimasjonene dine har utløpt eller blitt ugyldige. Vennligst skriv inn API-legitimasjonene dine på nytt.",
        "data": {
          "client_id": "Klient-ID",
          "client_secret": "Klienthemmelighet"
        }
      }
    },
    "error": {
      "cannot_connect": "Kunne ikke koble til transportørens API.",
      "invalid_auth": "Ugyldige legitimasjoner. Vennligst sjekk og prøv igjen.",
      "unknown": "En uventet feil oppstod."
    },
    "abort": {
      "already_configured": "Denne transportørkontoen er allerede konfigurert.",
      "reauth_successful": "Autentisering på nytt var vellykket."
    }
  },
  "options": {
    "step": {
      "init": {
        "title": "Nordic Parcel-innstillinger",
        "data": {
          "scan_interval": "Oppdateringsintervall (sekunder)",
          "cleanup_days": "Fjern leverte pakker etter (dager, 0 = aldri)"
        }
      }
    }
  },
  "entity": {
    "sensor": {
      "parcel": {
        "name": "Pakke {tracking_id}"
      }
    }
  },
  "services": {
    "add_tracking": {
      "name": "Legg til sporing",
      "description": "Begynn å spore en pakke med sporingsnummeret.",
      "fields": {
        "tracking_id": {
          "name": "Sporings-ID",
          "description": "Sporingsnummeret fra transportøren."
        },
        "carrier": {
          "name": "Transportør",
          "description": "Hvilken transportør som skal brukes. Hvis utelatt, legges sporingsnummeret til den første konfigurerte transportøren."
        }
      }
    },
    "remove_tracking": {
      "name": "Fjern sporing",
      "description": "Slutt å spore en pakke og fjern sensoren.",
      "fields": {
        "tracking_id": {
          "name": "Sporings-ID",
          "description": "Sporingsnummeret som skal sluttes å spores."
        }
      }
    }
  }
}
```

- [ ] **Step 4: Commit**

```bash
git add custom_components/nordic_parcel/strings.json custom_components/nordic_parcel/translations/en.json custom_components/nordic_parcel/translations/nb.json
git commit -m "Add strings.json and service/reauth translations"
```

---

### Task 2: Add device_info and update sensor naming

**Files:**
- Modify: `custom_components/nordic_parcel/sensor.py:1-10` (imports)
- Modify: `custom_components/nordic_parcel/sensor.py:62-96` (class definition, device_info, name)

- [ ] **Step 1: Add imports to sensor.py**

Add `DeviceInfo` and `DeviceEntryType` imports. Replace the existing import block at the top of `sensor.py`:

```python
"""Sensor platform for Nordic Parcel integration."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Shipment
from .const import DOMAIN
from .coordinator import NordicParcelCoordinator
```

The key additions are `DeviceEntryType` and `DeviceInfo`.

- [ ] **Step 2: Add device_info property to NordicParcelSensor**

Add this property to the `NordicParcelSensor` class, after the `__init__` method (after line 75):

```python
    @property
    def device_info(self) -> DeviceInfo:
        """Return device info to group sensors under carrier account."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name=self.coordinator.config_entry.title,
            manufacturer=self.coordinator.client.carrier.value.title(),
            model="Parcel Tracking",
            entry_type=DeviceEntryType.SERVICE,
        )
```

- [ ] **Step 3: Update the name property**

The carrier prefix now lives in the device name. Update the `name` property to remove the carrier prefix:

Replace the existing `name` property:

```python
    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        shipment = self._shipment
        if shipment and shipment.sender:
            return f"{shipment.sender} ({self._tracking_id[-6:]})"
        return self._tracking_id
```

- [ ] **Step 4: Commit**

```bash
git add custom_components/nordic_parcel/sensor.py
git commit -m "Add device_info and simplify sensor naming"
```

---

### Task 3: Add diagnostics.py

**Files:**
- Create: `custom_components/nordic_parcel/diagnostics.py`

- [ ] **Step 1: Create diagnostics.py**

Create `custom_components/nordic_parcel/diagnostics.py`:

```python
"""Diagnostics support for Nordic Parcel integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_API_KEY, CONF_API_UID, CONF_CLIENT_ID, CONF_CLIENT_SECRET
from .coordinator import NordicParcelCoordinator, DOMAIN

TO_REDACT = {CONF_API_KEY, CONF_API_UID, CONF_CLIENT_ID, CONF_CLIENT_SECRET}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: NordicParcelCoordinator = hass.data[DOMAIN][entry.entry_id]

    shipments_data = {}
    if coordinator.data:
        for tracking_id, shipment in coordinator.data.items():
            shipments_data[tracking_id] = {
                "carrier": shipment.carrier.value,
                "status": shipment.status.value,
                "sender": shipment.sender,
                "recipient": shipment.recipient,
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
                        "location": e.location,
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

- [ ] **Step 2: Commit**

```bash
git add custom_components/nordic_parcel/diagnostics.py
git commit -m "Add diagnostics support with credential redaction"
```

---

### Task 4: Fix manifest.json and hacs.json

**Files:**
- Modify: `custom_components/nordic_parcel/manifest.json`
- Modify: `hacs.json`

- [ ] **Step 1: Update manifest.json**

Replace the full content of `custom_components/nordic_parcel/manifest.json`:

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

Changes: `codeowners` populated, `documentation` and `issue_tracker` URLs fixed, `integration_type` added.

- [ ] **Step 2: Update hacs.json**

Replace the full content of `hacs.json`:

```json
{
  "name": "Nordic Parcel",
  "homeassistant": "2024.1.0",
  "render_readme": true
}
```

Change: added `homeassistant` minimum version.

- [ ] **Step 3: Commit**

```bash
git add custom_components/nordic_parcel/manifest.json hacs.json
git commit -m "Fix manifest metadata and add HA minimum version to hacs.json"
```

---

### Task 5: Improve reauth flow

**Files:**
- Modify: `custom_components/nordic_parcel/config_flow.py`

This is the most involved change. The reauth flow needs dedicated steps that pre-fill non-secret fields and update the existing entry instead of creating a new one.

- [ ] **Step 1: Update async_step_reauth to store entry reference and route to dedicated steps**

Replace the existing `async_step_reauth` method (lines 194-203 of `config_flow.py`) with:

```python
    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Handle reauthentication."""
        self._reauth_entry = self._get_reauth_entry()
        carrier = Carrier(entry_data[CONF_CARRIER])
        if carrier == Carrier.BRING:
            return await self.async_step_reauth_bring()
        if carrier == Carrier.POSTNORD:
            return await self.async_step_reauth_postnord()
        return await self.async_step_reauth_helthjem()
```

- [ ] **Step 2: Add async_step_reauth_bring**

Add this method to `NordicParcelConfigFlow`, after `async_step_reauth`:

```python
    async def async_step_reauth_bring(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle Bring reauthentication."""
        errors: dict[str, str] = {}
        entry = self._reauth_entry

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = BringApiClient(
                session, user_input[CONF_API_UID], user_input[CONF_API_KEY]
            )
            try:
                if await client.authenticate():
                    return self.async_update_reload_and_abort(
                        entry,
                        data={
                            **entry.data,
                            CONF_API_UID: user_input[CONF_API_UID],
                            CONF_API_KEY: user_input[CONF_API_KEY],
                        },
                    )
                errors["base"] = "invalid_auth"
            except CarrierApiError:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reauth_bring",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_API_UID,
                        default=entry.data.get(CONF_API_UID, ""),
                    ): str,
                    vol.Required(CONF_API_KEY): str,
                }
            ),
            errors=errors,
        )
```

- [ ] **Step 3: Add async_step_reauth_postnord**

Add this method after `async_step_reauth_bring`:

```python
    async def async_step_reauth_postnord(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle Postnord reauthentication."""
        errors: dict[str, str] = {}
        entry = self._reauth_entry

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = PostnordApiClient(session, user_input[CONF_API_KEY])
            try:
                if await client.authenticate():
                    return self.async_update_reload_and_abort(
                        entry,
                        data={
                            **entry.data,
                            CONF_API_KEY: user_input[CONF_API_KEY],
                        },
                    )
                errors["base"] = "invalid_auth"
            except CarrierApiError:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reauth_postnord",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): str,
                }
            ),
            errors=errors,
        )
```

- [ ] **Step 4: Add async_step_reauth_helthjem**

Add this method after `async_step_reauth_postnord`:

```python
    async def async_step_reauth_helthjem(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle Helthjem reauthentication."""
        errors: dict[str, str] = {}
        entry = self._reauth_entry

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = HelthjemApiClient(
                session, user_input[CONF_CLIENT_ID], user_input[CONF_CLIENT_SECRET]
            )
            try:
                if await client.authenticate():
                    return self.async_update_reload_and_abort(
                        entry,
                        data={
                            **entry.data,
                            CONF_CLIENT_ID: user_input[CONF_CLIENT_ID],
                            CONF_CLIENT_SECRET: user_input[CONF_CLIENT_SECRET],
                        },
                    )
                errors["base"] = "invalid_auth"
            except CarrierApiError:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reauth_helthjem",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CLIENT_ID,
                        default=entry.data.get(CONF_CLIENT_ID, ""),
                    ): str,
                    vol.Required(CONF_CLIENT_SECRET): str,
                }
            ),
            errors=errors,
        )
```

- [ ] **Step 5: Commit**

```bash
git add custom_components/nordic_parcel/config_flow.py
git commit -m "Improve reauth flow with pre-fill and entry update"
```

---

### Task 6: Remove service descriptions from services.yaml

Now that service names and descriptions live in `strings.json` (the HA-standard location), `services.yaml` should only contain field schemas/selectors — not duplicated `name`/`description` strings.

**Files:**
- Modify: `custom_components/nordic_parcel/services.yaml`

- [ ] **Step 1: Strip name/description from services.yaml**

Replace `custom_components/nordic_parcel/services.yaml` with selector-only content:

```yaml
add_tracking:
  fields:
    tracking_id:
      required: true
      example: "370000000000123456"
      selector:
        text:
    carrier:
      required: false
      selector:
        select:
          options:
            - label: "Bring (Posten Norge)"
              value: "bring"
            - label: "Postnord"
              value: "postnord"
            - label: "Helthjem"
              value: "helthjem"

remove_tracking:
  fields:
    tracking_id:
      required: true
      example: "370000000000123456"
      selector:
        text:
```

- [ ] **Step 2: Commit**

```bash
git add custom_components/nordic_parcel/services.yaml
git commit -m "Remove duplicated strings from services.yaml (now in strings.json)"
```

---

### Task 7: Final verification

- [ ] **Step 1: Verify file structure**

Run:
```bash
find custom_components/nordic_parcel -type f | sort
```

Expected output should include all expected files:
```
custom_components/nordic_parcel/__init__.py
custom_components/nordic_parcel/api/__init__.py
custom_components/nordic_parcel/api/bring.py
custom_components/nordic_parcel/api/helthjem.py
custom_components/nordic_parcel/api/postnord.py
custom_components/nordic_parcel/config_flow.py
custom_components/nordic_parcel/const.py
custom_components/nordic_parcel/coordinator.py
custom_components/nordic_parcel/diagnostics.py        <-- NEW
custom_components/nordic_parcel/manifest.json
custom_components/nordic_parcel/sensor.py
custom_components/nordic_parcel/services.yaml
custom_components/nordic_parcel/strings.json           <-- NEW
custom_components/nordic_parcel/translations/en.json
custom_components/nordic_parcel/translations/nb.json
```

- [ ] **Step 2: Verify strings.json and en.json are identical**

Run:
```bash
diff custom_components/nordic_parcel/strings.json custom_components/nordic_parcel/translations/en.json
```

Expected: no output (files identical).

- [ ] **Step 3: Verify nb.json has all keys from en.json**

Run:
```bash
python3 -c "
import json
with open('custom_components/nordic_parcel/translations/en.json') as f:
    en = json.load(f)
with open('custom_components/nordic_parcel/translations/nb.json') as f:
    nb = json.load(f)

def check_keys(en_dict, nb_dict, path=''):
    for key in en_dict:
        full_path = f'{path}.{key}' if path else key
        if key not in nb_dict:
            print(f'MISSING in nb.json: {full_path}')
        elif isinstance(en_dict[key], dict) and isinstance(nb_dict[key], dict):
            check_keys(en_dict[key], nb_dict[key], full_path)

check_keys(en, nb)
print('Key check complete.')
"
```

Expected: "Key check complete." with no MISSING lines.

- [ ] **Step 4: Verify manifest.json is valid**

Run:
```bash
python3 -c "
import json
with open('custom_components/nordic_parcel/manifest.json') as f:
    m = json.load(f)
assert m['codeowners'] == ['@jumpingmushroom'], 'codeowners wrong'
assert 'yourusername' not in m['documentation'], 'placeholder URL'
assert 'yourusername' not in m['issue_tracker'], 'placeholder URL'
assert m.get('integration_type') == 'service', 'missing integration_type'
print('manifest.json OK')
"
```

- [ ] **Step 5: Verify diagnostics imports correctly**

Run:
```bash
python3 -c "
import ast
with open('custom_components/nordic_parcel/diagnostics.py') as f:
    tree = ast.parse(f.read())
funcs = [node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
assert 'async_get_config_entry_diagnostics' in funcs, 'missing diagnostics function'
print('diagnostics.py structure OK')
"
```

- [ ] **Step 6: Verify sensor.py has device_info**

Run:
```bash
python3 -c "
import ast
with open('custom_components/nordic_parcel/sensor.py') as f:
    tree = ast.parse(f.read())
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and node.name == 'NordicParcelSensor':
        methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        assert 'device_info' in methods, 'missing device_info property'
        print('sensor.py has device_info OK')
        break
"
```

- [ ] **Step 7: Verify config_flow.py has reauth steps**

Run:
```bash
python3 -c "
import ast
with open('custom_components/nordic_parcel/config_flow.py') as f:
    tree = ast.parse(f.read())
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and node.name == 'NordicParcelConfigFlow':
        methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for step in ['async_step_reauth_bring', 'async_step_reauth_postnord', 'async_step_reauth_helthjem']:
            assert step in methods, f'missing {step}'
        print('config_flow.py reauth steps OK')
        break
"
```
