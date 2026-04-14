# Nordic Parcel

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)

Track parcels from Norwegian and Nordic carriers in Home Assistant.

## Supported Carriers

| Carrier | Auth Type | Manual Tracking |
|---------|-----------|-----------------|
| **Bring** (Posten Norge) | Mybring email + API key | Yes |
| **Postnord** | API key | Yes |
| **Helthjem** | OAuth2 (Client ID + Secret) | Yes |

> **Note:** Auto-fetch (automatically discovering parcels from your account) is not supported — none of the carriers expose a public API for listing parcels tied to a consumer account. Tracking numbers must be added manually via the service call or dashboard card below.

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu → **Custom repositories**
3. Add this repository URL and select **Integration**
4. Search for "Nordic Parcel" and install
5. Restart Home Assistant

### Manual

Copy the `custom_components/nordic_parcel` directory into your Home Assistant `config/custom_components/` directory and restart.

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for "Nordic Parcel"
3. Select your carrier and enter credentials

You can add multiple carriers by adding the integration multiple times.

### Getting API Credentials

#### Bring (Posten Norge)
1. Create or log in to your [Mybring](https://www.mybring.com/) account
2. Go to **Settings → API** to find your API key
3. Your Mybring email and API key are needed

#### Postnord
1. Register at [developer.postnord.com](https://developer.postnord.com/)
2. Create an application to get your API key

#### Helthjem
1. Contact [integrations@helthjem.no](mailto:integrations@helthjem.no) to request API access
2. You will receive a Client ID and Client Secret
3. Note: You must be an existing Helthjem customer

## Usage

### Automatic Sensors

Once configured, the integration creates a sensor for each tracked parcel. Sensors show the current status (e.g., "In Transit", "Delivered") with detailed attributes.

### Adding Tracking Numbers

Use the `nordic_parcel.add_tracking` service:

```yaml
service: nordic_parcel.add_tracking
data:
  tracking_id: "370000000000123456"
  carrier: bring  # Optional: bring, postnord, or helthjem
```

### Removing Tracking Numbers

```yaml
service: nordic_parcel.remove_tracking
data:
  tracking_id: "370000000000123456"
```

### Dashboard Card

You can set up a dashboard card to add parcels and view all currently tracked parcels without using Developer Tools.

#### 1. Create helpers

Go to **Settings > Devices & Services > Helpers** and create:

- **Dropdown** named `Parcel Carrier` with options: `bring`, `postnord`, `helthjem`
- **Text** named `Parcel Tracking ID` with min length `0` and max length `50`

Or add them via YAML:

```yaml
input_select:
  parcel_carrier:
    name: Parcel Carrier
    options:
      - bring
      - postnord
      - helthjem

input_text:
  parcel_tracking_id:
    name: Parcel Tracking ID
    min: 0
    max: 50
    mode: text
    initial: ""
```

#### 2. Create automation

This automation triggers when you enter a tracking ID, adds it to the integration, and clears the field:

```yaml
automation:
  - alias: "Add parcel tracking from dashboard"
    trigger:
      - platform: state
        entity_id: input_text.parcel_tracking_id
    condition:
      - condition: template
        value_template: >-
          {{ trigger.to_state.state not in ['', 'unknown', 'unavailable']
             and trigger.to_state.state | length > 4 }}
    action:
      - service: nordic_parcel.add_tracking
        data:
          tracking_id: "{{ states('input_text.parcel_tracking_id') | string }}"
          carrier: "{{ states('input_select.parcel_carrier') | string }}"
      - service: input_text.set_value
        target:
          entity_id: input_text.parcel_tracking_id
        data:
          value: ""
```

#### 3. Add the card

Add this card to your Lovelace dashboard to get an input form and a live list of tracked parcels:

```yaml
type: vertical-stack
cards:
  - type: entities
    title: Track a Parcel
    entities:
      - entity: input_select.parcel_carrier
        name: Carrier
      - entity: input_text.parcel_tracking_id
        name: Tracking ID
  - type: markdown
    title: Current Parcels
    content: >-
      {% set icons = {
        'Pre Transit': '📦',
        'In Transit': '🚚',
        'Customs': '🛃',
        'Out For Delivery': '🏃',
        'Ready For Pickup': '📬',
        'Delivered': '✅',
        'Returned': '↩️',
        'Failed': '❌',
        'Unknown': '❓'
      } %}
      {% for state in states.sensor
         if state.attributes.get('carrier') in ['bring', 'postnord', 'helthjem'] %}
      {{ icons.get(state.state, '📦') }} **{{ state.attributes.sender or state.attributes.tracking_id }}**
      {{ state.attributes.carrier | title }} · {{ state.state }}
      {% else %}
      *No parcels being tracked.*
      {% endfor %}
```

Select a carrier, type the tracking ID, and hit enter. The parcel appears in the list below automatically.

### Sensors

#### Parcel Sensors

Each tracked parcel gets its own sensor with the following attributes:

- `carrier` — Which carrier is handling the parcel
- `tracking_id` — The tracking number
- `sender` — Sender name (when available)
- `recipient` — Recipient name (when available)
- `estimated_delivery` — Estimated delivery date/time
- `last_event_description` — Most recent tracking event
- `last_event_time` — When the last event occurred
- `last_event_location` — Where the last event occurred
- `event_count` — Number of tracking events

Possible states: Unknown, Pre-transit, In transit, Customs, Out for delivery, Ready for pickup, Delivered, Returned, Failed.

#### Summary Sensor

A global **Nordic Parcel Summary** sensor aggregates all tracked parcels across every configured carrier:

- **State:** Number of active (non-delivered) parcels
- **Attributes:**
  - Status breakdown — `in_transit`, `out_for_delivery`, `customs`, etc. (only statuses with count > 0)
  - Carrier breakdown — `carrier_bring`, `carrier_postnord`, `carrier_helthjem`
  - `total_active` — Same as state value
  - `total_delivered` — Delivered parcels still being tracked before auto-cleanup

Use this to build conditional dashboard cards (e.g., only show the parcel card when `total_active > 0`).

### Events

The integration fires events on the Home Assistant event bus that you can use in automations:

| Event | Fired when | Data |
|-------|------------|------|
| `nordic_parcel_status_changed` | Any parcel status transition | `tracking_id`, `carrier`, `sender`, `old_status`, `new_status` |
| `nordic_parcel_delivered` | A parcel is first marked as delivered | `tracking_id`, `carrier` |
| `nordic_parcel_out_for_delivery` | Parcel is out for delivery | `tracking_id`, `carrier`, `sender`, `old_status`, `new_status` |
| `nordic_parcel_ready_for_pickup` | Parcel is ready for pickup | `tracking_id`, `carrier`, `sender`, `old_status`, `new_status` |
| `nordic_parcel_returned` | Parcel was returned to sender | `tracking_id`, `carrier`, `sender`, `old_status`, `new_status` |
| `nordic_parcel_failed` | Delivery failed | `tracking_id`, `carrier`, `sender`, `old_status`, `new_status` |
| `nordic_parcel_customs` | Parcel entered customs | `tracking_id`, `carrier`, `sender`, `old_status`, `new_status` |

The granular events fire **in addition to** `nordic_parcel_status_changed`, so you can listen to either the generic event or the specific one. No events fire on the first poll after adding a parcel (only on subsequent transitions).

### Repairs

The integration surfaces issues in **Settings > System > Repairs**:

| Issue | Severity | Fixable | Condition |
|-------|----------|---------|-----------|
| Stale tracking | Warning | Yes (removes tracking) | No tracking update for 14+ days |
| Stuck in customs | Warning | No (informational) | In customs for 7+ days |
| Authentication failed | Error | No (use reauth flow) | Carrier API credentials invalid |

Issues auto-clear when conditions resolve (e.g., parcel updates, leaves customs, reauth succeeds).

### Auto-Cleanup

Delivered parcels are automatically removed after a configurable number of days (default: 3). Change this in the integration options. Set to 0 to disable auto-cleanup.

### Automation Examples

#### Notify on any parcel status change

This single automation covers all parcels — current and future — with no manual configuration:

```yaml
automation:
  - alias: "Notify on any parcel update"
    trigger:
      - platform: event
        event_type: nordic_parcel_status_changed
    action:
      - service: notify.mobile_app
        data:
          title: "Parcel Update"
          message: >-
            {{ trigger.event.data.carrier | title }}
            ({{ trigger.event.data.sender }}):
            {{ trigger.event.data.old_status | replace('_', ' ') | title }}
            → {{ trigger.event.data.new_status | replace('_', ' ') | title }}
```

#### Notify when out for delivery

```yaml
automation:
  - alias: "Notify when parcel is out for delivery"
    trigger:
      - platform: event
        event_type: nordic_parcel_out_for_delivery
    action:
      - service: notify.mobile_app
        data:
          title: "Parcel on its way!"
          message: >-
            Your {{ trigger.event.data.carrier | title }} parcel
            from {{ trigger.event.data.sender }} is out for delivery.
```

#### Notify on delivery only

```yaml
automation:
  - alias: "Notify on parcel delivery"
    trigger:
      - platform: event
        event_type: nordic_parcel_delivered
    action:
      - service: notify.mobile_app
        data:
          title: "Parcel delivered!"
          message: >-
            Your {{ trigger.event.data.carrier | title }} parcel
            {{ trigger.event.data.tracking_id }} has been delivered.
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| Update interval | 900s (15 min) | How often to poll the carrier API |
| Cleanup days | 3 | Days after delivery before removing the sensor (0 = never) |

## License

MIT
