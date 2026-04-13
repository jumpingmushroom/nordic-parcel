# Contributing to Nordic Parcel

## Development Setup

1. Clone the repository
2. Create a virtual environment: `python -m venv .venv && source .venv/bin/activate`
3. Install test dependencies: `pip install -r requirements_test.txt`
4. Run tests: `pytest tests/ -v`
5. Run linting: `ruff check custom_components/ tests/`

## Adding a New Carrier

1. **Create the API client** at `custom_components/nordic_parcel/api/<carrier>.py`
   - Implement the `CarrierClient` protocol from `custom_components/nordic_parcel/api/__init__.py`
   - Required methods: `authenticate()`, `get_shipments()`, `track_shipment()`, `close()`
   - Map carrier-specific statuses to `ShipmentStatus` enum values

2. **Add the carrier enum** in `custom_components/nordic_parcel/const.py`:
   ```python
   class Carrier(StrEnum):
       ...
       NEW_CARRIER = "new_carrier"
   ```

3. **Add config flow steps** in `custom_components/nordic_parcel/config_flow.py`:
   - `async_step_<carrier>()` for initial setup
   - `async_step_reauth_<carrier>()` for reauthentication
   - Add the carrier to `async_step_user()` selection

4. **Register the client** in `custom_components/nordic_parcel/__init__.py`:
   - Import the client class
   - Add a branch in `_create_client()`

5. **Add translations** in `strings.json` and `translations/`:
   - Config flow step labels and descriptions
   - Error messages

6. **Write tests** in `tests/`:
   - `tests/test_api_<carrier>.py` — API client tests with mocked HTTP responses
   - Add config flow test cases to `tests/test_config_flow.py`
   - Add sample response data to `tests/conftest.py`

7. **Update documentation**:
   - Add the carrier to the table in `README.md`
   - Add credential instructions under "Getting API Credentials"

## Code Style

- Run `ruff check` and `ruff format` before submitting
- All async code uses `asyncio.timeout()` (not `async_timeout`)
- Type hints on all function signatures
- Tracking IDs are always uppercased

## Testing

Tests use `pytest` with `pytest-homeassistant-custom-component` for HA fixtures and `aioresponses` for HTTP mocking.

```bash
# Run all tests
pytest tests/ -v

# Run a specific test file
pytest tests/test_api_bring.py -v

# Run a specific test
pytest tests/test_api_bring.py::TestBringTrackShipment::test_track_success -v
```
