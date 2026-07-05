# Code Review — Nordic Parcel — 2026-07-05 — reviewed by Fable 5

## Summary
Nordic Parcel is a small (~1,900 LOC source, ~3,000 LOC tests), well-structured Home Assistant custom integration for tracking parcels from Bring, Postnord, and Helthjem. The architecture is clean: one config entry per carrier, a `DataUpdateCoordinator` per entry, thin typed API clients behind a shared protocol, and good test coverage of the happy paths and most error paths. Credentials are handled correctly (stored in config entries, redacted in diagnostics), and there are no security vulnerabilities of consequence. The main risks are correctness/reliability issues: timezone-naive timestamps from carrier APIs can crash the entire update cycle, the cross-entry summary sensor breaks when the entry that created it is unloaded, and a documented-as-fixed race in the coordinator can still silently drop a user's manually added tracking ID.

## Findings

### [SEV-2] Timezone-naive carrier timestamps crash the coordinator update
> **FIXED:** Added `ensure_aware()` helper in api/__init__.py; all three `_parse_event` functions now normalize naive timestamps to UTC. Added a naive-timestamp test per client.
- **File:** custom_components/nordic_parcel/api/postnord.py:53-57, custom_components/nordic_parcel/api/helthjem.py:110-114, custom_components/nordic_parcel/api/bring.py:57, custom_components/nordic_parcel/coordinator.py:198-227
- **Issue:** All three clients parse event timestamps with `datetime.fromisoformat()`, which happily returns a **naive** datetime when the carrier omits a UTC offset (e.g. `"2026-07-01T10:00:00"`). The coordinator then computes `(now - last.timestamp)` with an aware `now = datetime.now(UTC)` (coordinator.py:194, 198-203, 223-227), which raises `TypeError: can't subtract offset-naive and offset-aware datetimes`. The exception escapes `_async_update_data` as an "unexpected error", marking every sensor for that entry unavailable — permanently, until the carrier stops returning that shipment.
- **Evidence:** Two independent crash paths: (1) the repair-issue checks in coordinator.py:198-227 subtract naive event timestamps from aware `now`; (2) `events.sort(key=lambda e: e.timestamp)` in postnord.py:85 and helthjem.py:251 raises `TypeError` when the list mixes naive parsed timestamps with the aware `datetime.now(UTC)` fallback used for unparseable strings (postnord.py:57, helthjem.py:114). All test fixtures use offset-bearing timestamps, so tests never exercise the naive case.
- **Suggested fix:** Normalize in one place: after `fromisoformat`, if `timestamp.tzinfo is None`, attach the carrier's local timezone (or UTC) with `.replace(tzinfo=...)`, ideally via a shared helper used by all three `_parse_event` functions. `homeassistant.util.dt.parse_datetime` + `dt_util.as_utc` is the idiomatic HA way.
- **Verification:** Add a test per client with an offset-less `eventTime`/`timestamp`/`dateIso`, assert the returned `TrackingEvent.timestamp.tzinfo` is not None; add a coordinator test where a shipment's last event is naive and assert the update succeeds and the stale-tracking check doesn't raise.

### [SEV-2] Summary sensor is destroyed when the config entry that created it unloads
> **FIXED:** `async_will_remove_from_hass` now always drops the stale `summary_entity` reference; setup reuses it only when still added (new `added` property). Added a multi-entry unload/reload test.
- **File:** custom_components/nordic_parcel/sensor.py:67-75, 229-237
- **Issue:** The global summary sensor is added via the **first** entry's `async_add_entities`, so it belongs to that entry's sensor platform. Unloading that entry (reload, reconfigure, or removal) removes the summary entity from HA even when other carrier entries remain loaded. Worse, `async_will_remove_from_hass` leaves the stale object in `hass.data[DOMAIN]["summary_entity"]` whenever any coordinators remain (sensor.py:236-237), so the next entry to set up takes the `add_coordinator` path (sensor.py:74-75) and calls `async_write_ha_state()` on an entity that is no longer added to hass — raising and failing that entry's sensor platform setup.
- **Evidence:** `async_will_remove_from_hass` unsubscribes **all** coordinator listeners (including other entries') and only pops `summary_entity` from `domain_data` if `coordinators` is empty. With two carriers configured, reloading carrier A removes the summary entity, orphans the reference, and stops summary updates from carrier B; a subsequent setup of any entry then writes state on a removed entity.
- **Suggested fix:** Either give the summary its own lifecycle (recreate it in whichever entry's platform sets up while none exists, and always pop the stale reference on removal), or drop the shared-entity approach and let each entry own the aggregation via a device-less template pattern. Simplest robust fix: in `async_will_remove_from_hass`, always `domain_data.pop("summary_entity", None)`; in `async_setup_entry`, if the stored summary exists but `summary.hass is None`/not added, recreate it.
- **Verification:** Test: set up two entries, unload the first, assert the summary entity still exists (or is recreated) and updates when the second entry's coordinator refreshes; assert setting up a third entry does not raise.

### [SEV-3] Coordinator batch-write can still drop a concurrently added tracking ID
> **FIXED:** Step 6 now re-reads `manual_tracking` fresh and merges only this cycle's tracked add/remove deltas instead of writing the stale snapshot. Added a concurrent-add regression test.
- **File:** custom_components/nordic_parcel/coordinator.py:107-109, 279-288
- **Issue:** `_async_update_data` snapshots `manual = dict(...)` before its `await` points, then at step 6 writes `fresh_data[CONF_MANUAL_TRACKING] = manual` — the **stale snapshot** — back to the config entry. If a user calls `add_tracking` while the update is awaiting a carrier API call and the update ends with `config_changed = True` (delivery detected, cleanup, consignment replacement), the freshly added ID is silently erased from the entry data. The comment at lines 281-282 claims re-reading `fresh_data` avoids exactly this, but only non-manual keys are protected; `CONF_MANUAL_TRACKING` itself is clobbered.
- **Evidence:** `add_tracking` (coordinator.py:82-90) runs on the event loop between the coordinator's awaits; its `async_update_entry` write is overwritten at coordinator.py:284 because `manual` was copied at line 109 before the API awaits. The queued `async_request_refresh` then re-reads the clobbered data, so the ID is gone for good.
- **Suggested fix:** At step 6, merge instead of replace: re-read `fresh_manual = dict(self.config_entry.data.get(CONF_MANUAL_TRACKING, {}))`, apply this cycle's *deltas* (IDs removed by replacement/cleanup, IDs added by replacement) to `fresh_manual`, and write that. Alternatively serialize `add_tracking`/`remove_tracking`/step-6 writes behind an `asyncio.Lock`.
- **Verification:** Test: start a refresh whose mocked `track_shipment` awaits an event; while pending, call `add_tracking("NEW123")`; complete the refresh with a delivery (forcing `config_changed`); assert `"NEW123"` is still in `entry.data[CONF_MANUAL_TRACKING]`.

### [SEV-3] Response body parsing sits outside the error handling in all three API clients
> **FIXED:** Wrapped every `resp.json()` (including Helthjem's token endpoint) to raise `CarrierApiError` on non-JSON/decoding failures; Bring now skips malformed individual events instead of failing the whole shipment. Added tests per client.
- **File:** custom_components/nordic_parcel/api/bring.py:185, custom_components/nordic_parcel/api/postnord.py:174, custom_components/nordic_parcel/api/helthjem.py:170, 236
- **Issue:** `await resp.json()` is called outside the `try` blocks that translate `aiohttp.ClientError` into `CarrierApiError`. A 200 response with a non-JSON body (HTML error page from a proxy/CDN, truncated payload) raises `aiohttp.ContentTypeError`/`JSONDecodeError`, which bypasses the typed error hierarchy. In the coordinator this becomes an "unexpected error" (entities unavailable, traceback in logs); in `HelthjemApiClient._ensure_token` (helthjem.py:170) it escapes `authenticate()` entirely, so the config flow's `except CarrierApiError` (config_flow.py:163) does not catch it and the flow aborts with an unknown-error traceback. Relatedly, `bring._parse_event` (bring.py:57) does `event["dateIso"]` — a `KeyError`/`ValueError` on one malformed event kills the whole update.
- **Evidence:** In `track_shipment` the `try` covers only the `session.get`; body reading and parsing follow after the status checks with no exception handling.
- **Suggested fix:** Wrap `resp.json()` (and Bring's per-event parsing) in the same `try`/`except` that raises `CarrierApiError`, e.g. catch `(aiohttp.ClientError, ValueError, KeyError)` around body parse; skip-and-log individual malformed events rather than failing the shipment.
- **Verification:** Test per client: mock a 200 response with `text/html` body and assert `CarrierApiError` is raised (not `ContentTypeError`); test Bring parse with an event missing `dateIso` and assert the shipment still parses.

### [SEV-3] Stale-tracking / stuck-customs repair issues are orphaned when the shipment disappears
> **FIXED:** Coordinator now tracks tids with open issues (`_issue_tids`) and deletes both issue types for any tid no longer present in the current shipment set. Added a disappearing-shipment test.
- **File:** custom_components/nordic_parcel/coordinator.py:195-242
- **Issue:** Issue deletion only happens in the `else` branches of the per-shipment loop — i.e. only while the tracking ID is still present in this cycle's `shipments`. If the shipment vanishes for any other reason (user calls `remove_tracking` directly, auto-cleanup, carrier starts returning 404), the `stale_tracking_<tid>` / `stuck_customs_<tid>` issue is never deleted and sits in the repairs dashboard forever. The README's claim that "Issues auto-clear when conditions resolve" doesn't hold for this path. (The repair *fix flow* deletes its own issue, but that's only one of the removal paths.)
- **Evidence:** The loop iterates `shipments.items()`; a tid absent from `shipments` is simply never visited, so neither create nor delete runs for it.
- **Suggested fix:** Track which issue IDs were created (or derive them from the previous cycle's data / `_previous_statuses` keys) and delete issues for any tid no longer in `shipments`. Also delete both issues in `remove_tracking()`.
- **Verification:** Test: create a stale-tracking issue via a 14-day-old shipment, then remove the tracking via `remove_tracking` and refresh; assert the issue registry no longer contains `stale_tracking_<tid>`.

### [SEV-3] hacs.json advertises HA 2024.1.0 but the code requires much newer core APIs
> **FIXED:** Raised `homeassistant` minimum in hacs.json to `2024.12.0` (the floor set by `ConfigFlow._get_reauth_entry`).
- **File:** hacs.json:3, custom_components/nordic_parcel/__init__.py:94, custom_components/nordic_parcel/config_flow.py:10, 180
- **Issue:** `"homeassistant": "2024.1.0"` lets HACS install this on cores where it cannot run: `ConfigEntry.runtime_data` and `ConfigFlowResult` landed in HA 2024.4, and `ConfigFlow._get_reauth_entry()` (config_flow.py:180) landed around 2024.11–2024.12. The `type NordicParcelConfigEntry = ...` statement (coordinator.py:44) also requires Python 3.12, which HA 2024.1 didn't guarantee. Users on older cores get import errors or reauth crashes instead of a clean "requires newer HA" message.
- **Evidence:** Version floor vs. API usage mismatch; no runtime guard exists.
- **Suggested fix:** Raise `homeassistant` in hacs.json to the oldest core actually tested (≥ 2024.12 given `_get_reauth_entry`).
- **Verification:** `grep runtime_data\|ConfigFlowResult\|_get_reauth_entry` against the chosen minimum core's release notes; or install under that core in a test container and load the integration.

### [SEV-3] async_unload_entry tears down shared state before checking unload success
> **FIXED:** Gated all coordinator/service/domain-data teardown on `if unload_ok:`. Added a failed-unload test.
- **File:** custom_components/nordic_parcel/__init__.py:116-133
- **Issue:** The coordinator is removed from the shared registry and (if last entry) services and `hass.data[DOMAIN]` are removed regardless of `unload_ok`. If `async_unload_platforms` fails, the entry stays LOADED but its coordinator is gone from the aggregation registry and the services may be unregistered — leaving a loaded entry whose summary aggregation and services are broken.
- **Evidence:** `unload_ok` is computed at line 118 but only consulted in the return; all teardown at lines 121-131 runs unconditionally.
- **Suggested fix:** Gate the registry/service teardown on `if unload_ok:`.
- **Verification:** Test with `async_unload_platforms` mocked to return False; assert the coordinator remains in `hass.data[DOMAIN]["coordinators"]` and services remain registered.

### [SEV-3] add_tracking with no carrier silently adds to an arbitrary entry and fails invisibly
- **File:** custom_components/nordic_parcel/__init__.py:139-161, custom_components/nordic_parcel/coordinator.py:166-167
- **Issue:** Without a `carrier` field, the service adds the ID to `coordinators[0]` — whichever entry happens to be first. If that's the wrong carrier, every refresh raises `CarrierNotFoundError`, which is swallowed at debug level (coordinator.py:166-167). The service call reports success, no sensor ever appears, no issue is raised, and the dead ID stays in config data forever. The README's dashboard-card flow (no carrier field) makes this the *default* path for multi-carrier users.
- **Evidence:** `handle_add_tracking` picks `coordinators[0]`; nothing validates that the carrier actually knows the tracking number.
- **Suggested fix:** On add, immediately call `client.track_shipment(tracking_id)`; on `CarrierNotFoundError`, either try the other configured carriers before giving up or raise `ServiceValidationError` so the user gets feedback. At minimum, log at warning and create a repair issue for never-found manual IDs.
- **Verification:** Test: two entries configured, call `add_tracking` without carrier for an ID only the second carrier resolves; assert it ends up tracked (or the service raises) rather than silently dead.

### [SEV-3] Diagnostics masks tracking IDs in one section but leaks them all in another
- **File:** custom_components/nordic_parcel/diagnostics.py:54-55
- **Issue:** `coordinator_data` carefully masks tracking IDs and redacts sender/recipient/location, but `entry.as_dict()` is included with only credential keys redacted — and `entry.data` contains `manual_tracking` and `delivered_timestamps`, both keyed by **full** tracking IDs. Anyone the user shares a diagnostics dump with (GitHub issues, forums) gets every tracking number, defeating the masking one section below.
- **Evidence:** `TO_REDACT` covers only the four credential keys; `CONF_MANUAL_TRACKING`/`CONF_DELIVERED_TIMESTAMPS` are dict-keyed by tracking ID, which `async_redact_data` cannot mask by key name anyway.
- **Suggested fix:** Post-process the redacted entry dict: replace the `manual_tracking` and `delivered_timestamps` dicts with `_mask_tracking_id`-keyed copies (or just counts).
- **Verification:** Extend tests/test_diagnostics.py to call `async_get_config_entry_diagnostics` on an entry with manual tracking and assert no full tracking ID appears anywhere in the serialized output.

### [SEV-3] Helthjem: bad credentials likely surface as "cannot connect" instead of "invalid auth"
> **FIXED:** `_ensure_token` now maps a 400 response whose OAuth `error` is `invalid_client`/`unauthorized_client`/`invalid_grant` to `CarrierAuthError`. Added a test. (Depends on Helthjem's actual endpoint behavior — conservative, only known OAuth error codes are treated as auth failures.)
- **File:** custom_components/nordic_parcel/api/helthjem.py:165-168, custom_components/nordic_parcel/config_flow.py:149-164
- **Issue:** OAuth2 token endpoints conventionally return **HTTP 400** (`invalid_client`/`invalid_grant`) for bad client credentials, not 401/403. `_ensure_token` maps only 401/403 to `CarrierAuthError`; a 400 becomes `CarrierApiError`, so the config flow shows "Failed to connect" for wrong credentials and — worse — during a refresh the coordinator treats it as a transient warning instead of triggering reauth. Uncertainty: this depends on Helthjem's actual token endpoint behavior, which I cannot verify from the code; flagging rather than omitting.
- **Evidence:** helthjem.py:165-168 checks `resp.status in (401, 403)` then treats every other non-200 as generic API error.
- **Suggested fix:** Treat 400 responses from the token endpoint whose JSON `error` is `invalid_client`/`unauthorized_client`/`invalid_grant` as `CarrierAuthError`.
- **Verification:** Test `_ensure_token` with a mocked 400 + `{"error": "invalid_client"}` response; assert `CarrierAuthError`. Confirm against Helthjem's API docs or a live bad-credential request.

### [SEV-4] Summary sensor accumulates listeners across entry reloads
- **File:** custom_components/nordic_parcel/sensor.py:216-219
- **Issue:** `add_coordinator` appends an unsubscribe callback but nothing ever removes listeners for coordinators that are discarded on entry reload. Each reload of a non-first entry adds a fresh listener while the old one (holding a reference to the dead coordinator) stays until the summary entity itself is removed — unbounded growth for long-running installs that reload often, plus the dead coordinators are kept alive.
- **Evidence:** `_unsub_listeners` is only drained in `async_will_remove_from_hass`; entry unload does not notify the summary.
- **Suggested fix:** Key listeners by `entry_id` and unsubscribe in `async_unload_entry` (or have the summary re-derive subscriptions from `domain_data["coordinators"]` on each change instead of holding per-coordinator subscriptions).
- **Verification:** Test: reload an entry 3 times, assert `len(summary._unsub_listeners)` stays bounded (1 per live coordinator).

### [SEV-4] Entity-registry entries orphaned for shipments removed while HA was offline
- **File:** custom_components/nordic_parcel/sensor.py:33-63
- **Issue:** Registry cleanup only fires for IDs in `known_ids`, which is populated per-session. A parcel auto-cleaned (or manually removed) while HA is stopped — or whose entry's first refresh no longer returns it — leaves its registry entry behind forever, showing as a permanently unavailable "restored" sensor.
- **Evidence:** `removed = known_ids - current_ids` can never contain an ID from a previous HA run.
- **Suggested fix:** On setup, enumerate `er.async_entries_for_config_entry`, and remove registry entries whose unique_id's tracking ID is not in `coordinator.data`.
- **Verification:** Test: pre-seed the entity registry with a `nordic_parcel_OLD123` entry for the config entry, set up the integration with data lacking OLD123, assert the registry entry is removed.

### [SEV-4] Per-parcel sensor unique_id can collide across config entries
- **File:** custom_components/nordic_parcel/sensor.py:93
- **Issue:** `unique_id = f"{DOMAIN}_{tracking_id}"` omits the entry ID. Two entries tracking the same ID (two accounts, or the same parcel number appearing at two carriers) produce a unique_id collision: the second entity is rejected with an error log and never appears.
- **Evidence:** unique_id is derived from tracking ID alone; the registry-removal helper at sensor.py:54 assumes the same global scheme.
- **Suggested fix:** Include `coordinator.config_entry.entry_id` (or carrier) in the unique_id. Note this changes existing unique_ids — needs a registry migration to avoid duplicating users' entities.
- **Verification:** Test: two loaded entries whose coordinators both report tracking ID X; assert both sensors exist with distinct unique_ids.

### [SEV-4] Manual shipments are fetched sequentially
- **File:** custom_components/nordic_parcel/coordinator.py:133-169
- **Issue:** Each manual tracking ID is fetched one at a time with a 10 s timeout each; a user tracking 15 parcels on a flaky connection can take minutes per cycle, blocking the coordinator. Not a correctness bug, but an easy scalability ceiling.
- **Evidence:** Plain `for` loop awaiting `track_shipment` per ID.
- **Suggested fix:** `asyncio.gather` with a small semaphore (2–4 concurrent), keeping per-ID exception handling. Mind carrier rate limits.
- **Verification:** Test with N mocked slow responses and assert wall-clock scales sub-linearly (or just assert gather is used with bounded concurrency).

### [SEV-4] `close()` is dead API surface
- **File:** custom_components/nordic_parcel/api/__init__.py:79-81 (and the three client implementations)
- **Issue:** `CarrierClient.close()` is defined and implemented as a no-op by all three clients but never called anywhere in the integration or tests. Verified by tracing usage across the repo — no call sites.
- **Evidence:** `grep -rn "\.close()"` finds no callers of the client method.
- **Suggested fix:** Remove it from the protocol and clients, or start calling it from `async_unload_entry` if clients ever own sessions.
- **Verification:** `ruff`/`grep` confirm no references remain; tests pass.

### [SEV-4] Diagnostics endpoint has no end-to-end test
- **File:** tests/test_diagnostics.py:1-19
- **Issue:** Only the `_mask_tracking_id` helper is tested. `async_get_config_entry_diagnostics` — the code that decides what gets redacted and what leaks (see the SEV-3 above) — is untested, so redaction regressions ship silently.
- **Evidence:** 19-line test file, no use of the diagnostics entry point or a config entry fixture.
- **Suggested fix:** Add a test building a coordinator with shipments + manual tracking and snapshotting the diagnostics output, asserting credentials and tracking IDs never appear in full.
- **Verification:** New test fails on the current SEV-3 leak, passes after the fix.

## Not Reviewed
- `icons.json`, `translations/en.json`, `translations/nb.json` beyond structural parity — verified programmatically that `en.json` is identical to `strings.json` and `nb.json` has an identical key set; individual Norwegian phrasing not proofread.
- `.pytest_cache/`, `.claude/settings.local.json` — tooling artifacts, not product code.
- Test bodies were reviewed for coverage shape (names, fixtures, scenarios) rather than line-by-line assertion auditing.
- Live behavior of the three carrier APIs (actual timestamp formats, OAuth error codes, response shapes) could not be verified against real endpoints; findings that depend on API behavior (naive timestamps, Helthjem 400-on-bad-creds) are flagged with that uncertainty.
- README automation/dashboard YAML examples were spot-checked against service names and event names, not executed.
