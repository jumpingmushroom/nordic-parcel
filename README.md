# Nordic Parcel

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)

Track parcels from Norwegian and Nordic carriers in Home Assistant.

## Supported Carriers

| Carrier | Auth Type | Auto-fetch | Manual Tracking |
|---------|-----------|------------|-----------------|
| **Bring** (Posten Norge) | Mybring email + API key | — | Yes |
| **Postnord** | API key | — | Yes |
| **Helthjem** | OAuth2 (Client ID + Secret) | — | Yes |

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

### Sensor Attributes

Each parcel sensor includes:
- `carrier` — Which carrier is handling the parcel
- `tracking_id` — The tracking number
- `sender` — Sender name (when available)
- `recipient` — Recipient name (when available)
- `estimated_delivery` — Estimated delivery date/time
- `last_event_description` — Most recent tracking event
- `last_event_time` — When the last event occurred
- `last_event_location` — Where the last event occurred
- `events` — List of recent tracking events (up to 10)

### Auto-Cleanup

Delivered parcels are automatically removed after a configurable number of days (default: 3). Change this in the integration options. Set to 0 to disable auto-cleanup.

A `nordic_parcel_delivered` event is fired when a parcel is first marked as delivered, which you can use in automations.

### Automation Example

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
          message: "Your {{ trigger.event.data.carrier }} parcel {{ trigger.event.data.tracking_id }} has been delivered."
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| Update interval | 900s (15 min) | How often to poll the carrier API |
| Cleanup days | 3 | Days after delivery before removing the sensor (0 = never) |

## License

MIT
