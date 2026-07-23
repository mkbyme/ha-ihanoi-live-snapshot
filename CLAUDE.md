# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status and goal

The original task brief (Vietnamese; see `git show 2f4444b:README.md` -- the initial
commit, before `README.md` became the user-facing HACS readme it is now) was to build a
HACS integration for Home Assistant, based on the algorithm reverse-engineered in
`working/`, modeled structurally on the sibling repo `ha-toanthanggps-com`. That
integration is now scaffolded at `custom_components/ihanoi_live_snapshot/` (domain
`ihanoi_live_snapshot`). Two things to have loaded before touching it further:

1. **The wire protocol and working prototype** — `working/` (see below). This directory is
   listed in `.gitignore` (`/working`), so it is intentionally untracked/local-only —
   reference material the integration's `hevc.py`/`api.py` were ported from, not something
   the package imports at runtime.
2. **The HACS structural template** — the sibling repo `ha-toanthanggps-com`, one directory
   up (`/home/nxcuong/Desktop/mine/homeassistant/ha-toanthanggps-com`), which has its own
   `CLAUDE.md` worth reading for the conventions this integration borrows (module layout,
   `DataUpdateCoordinator`-less "account" object pattern, translations,
   `hacs.json`/`manifest.json` layout, `EntityCategory`/dynamic-icon idioms). It doesn't use
   the HA `image`/`button` platforms anywhere (its entities are `sensor`/`device_tracker`),
   so those pieces here are new territory, not copied wholesale.

## `custom_components/ihanoi_live_snapshot/` — the integration

No `DataUpdateCoordinator`/polling for the snapshot images themselves — a capture only
happens on demand (a button press), so there's nothing to poll on a schedule there. State
flows: button press → `IhanoiSnapshotAccount.async_update_camera()` → dispatcher signal →
the paired image entity re-renders. Keep this in mind before reaching for a coordinator
pattern for the image/button entities; it doesn't fit.

The one thing that *does* poll is the camera list/`wss_url` table: those session tokens
expire, and a stale one is what makes `button.press` fail with "Never saw a VPS NAL" or a
bare connection timeout (see `device.py`'s `async_setup_periodic_refresh`/`CONF_UPDATE_INTERVAL`
below) — that's a `DataUpdateCoordinator` on a `config_entry`-scoped timer, deliberately
mirroring the `ha-toanthanggps-com` sibling's `ToanThangGpsAccount.async_create_coordinator`
pattern, just for a different purpose (refreshing a lookup table, not entity state).

- `const.py` — domain, `CONF_CAMERAS`, `CONF_UPDATE_INTERVAL`/`DEFAULT_UPDATE_INTERVAL_MINUTES`/
  `UPDATE_INTERVAL_OPTIONS` (camera-list auto-refresh cadence; 0 disables it, manual button
  only), the bundled camera-list filename, the iHanoi API URL, WS handshake constants
  (`CLIENT_HELLO = "mobile:"`, user-agent), `MAX_NAME_LENGTH` (100 — entity/device names are
  the camera's `name` from `ihanoi_camera.json`, truncated to this per the task brief), and
  the dispatcher signal name template.
- `hevc.py` — ported from `working/ihanoi_hevc.py` almost verbatim: the 12-byte per-message
  framing header, NAL type constants, and `KeyframeCollector` (state machine: waits for a
  VPS(32)/SPS(33)/PPS(34) run, collects the IDR slice(s) that follow, flags itself `done`
  the instant the first non-parameter-set/non-IDR NAL arrives). `decode_first_frame_to_png`
  differs from the prototype's `decode_first_frame`: it pipes ffmpeg's PNG output back
  through stdout as bytes (`-f image2 -c:v png pipe:1`) instead of writing to a file path,
  since `ImageEntity` needs in-memory bytes, not a file. Still a blocking subprocess call —
  only ever invoked through `hass.async_add_executor_job`. Takes an optional `label`
  (the capture timestamp): when set, it's burned into the bottom-right corner via ffmpeg's
  `drawtext` filter — `_escape_drawtext` escapes the colons/backslashes so a `HH:MM:SS`
  string survives the filtergraph parser. `drawtext` points at the bundled
  `fonts/DejaVuSans.ttf` via `fontfile=` rather than a bare family name, so it only needs
  libfreetype — not libfontconfig or any host-installed font. (Originally it relied on
  fontconfig resolving a family name, which silently failed on font-less Alpine-based HA
  Docker/HAOS containers — drawtext would fail and the no-overlay retry below would kick
  in on *every* capture, so the timestamp label just never appeared; fontfile= sidesteps
  that class of environment entirely.) If ffmpeg still can't use it for some reason, a
  `drawtext`-failed decode is retried once *without* the overlay rather than losing the
  snapshot entirely.
- `api.py` — camera-list fetch/table-building (ported from
  `working/update_ihanoi_camera_list.py`) plus live snapshot capture (ported from
  `working/snapshot_ihanoi_livecamera.py`'s connect/send-hello/read-until-done loop). One
  deliberate deviation from the prototype: this uses **aiohttp** (`ClientSession.ws_connect`)
  instead of the `websocket-client` package the prototype used, since aiohttp is already a
  Home Assistant core dependency — avoids adding a `requirements` entry to `manifest.json`.
  `async_capture_snapshot` bounds the whole connect-send-collect loop in one
  `asyncio.timeout()` rather than relying on a per-call socket timeout.
- `device.py` — `IhanoiSnapshotAccount`: not a coordinator for the image/button entities,
  just the runtime store for one config entry. Holds the camera lookup table (loaded from
  the bundled `ihanoi_camera.json`), a `CameraSnapshot(image, last_updated, last_error, online)`
  per selected camera_id, `async_update_camera()` (capture + store + `async_dispatcher_send`),
  and `async_refresh_camera_list()` (re-fetch from the live API, overwrite the bundled file in
  place, *then* `asyncio.gather()` an `async_update_camera()` for every selected camera_id
  so a stale/expired `wss_url` gets fixed and re-captured in the same call -- per-camera
  capture failures are logged, not raised, so one flaky camera doesn't fail the whole
  list refresh). Also centralizes `camera_display_name()`/`device_info()` (name truncation
  + `DeviceInfo` construction) so `image.py`/`button.py` don't duplicate that logic.

  A camera that's down disappears from the live API response entirely -- that's the
  iHanoi API's own "it's offline" signal, not a fetch bug. `async_refresh_camera_list()`
  accounts for this: for any selected `camera_id` missing from the freshly fetched table,
  it carries over that camera_id's *previous* entry (name/`wss_url`/etc.) into the table
  that gets saved and applied, instead of dropping it -- otherwise `self.cameras` loses the
  entry, `camera_display_name()` falls back to the raw id, `available` (in
  `image.py`/`sensor.py`/`binary_sensor.py`/`button.py`, all `camera_id in account.cameras`)
  goes `False`, and `async_update_camera()` raises a spurious "not found" instead of a
  normal offline result. For camera_ids missing from *this* fetch specifically, it also
  skips the real capture attempt (which would otherwise hang for the full capture timeout
  on a `wss_url` already known to be stale) and calls `_mark_camera_offline()` instead --
  sets `online=False`/`last_error`, dispatches, but leaves the cached name and the last
  captured image bytes untouched, and does not move `last_updated` (that timestamp is
  strictly "last *successful* capture").

  Snapshot state also survives a real HA restart now, not just a config-entry
  reload/options change (which keeps this Python object, and therefore `self.snapshots`,
  alive in memory the whole time) -- `async_load_persisted_snapshots()` (called from
  `__init__.py`'s `async_setup_entry`, before platforms are forwarded, so entities read
  restored state on their first render) restores each selected camera's
  image/last_updated/last_error/online from a per-entry `homeassistant.helpers.storage.Store`
  (key `f"{DOMAIN}_{entry_id}_snapshots"`, image bytes base64-encoded since `Store` writes
  JSON). `_async_save_snapshots()` writes the whole thing back after every state change
  (`async_update_camera()`'s three exits, `_mark_camera_offline()`) -- no debouncing, since
  captures only happen on demand/every-N-minutes, not in a hot loop. Module-level
  `async_remove_persisted_snapshots(hass, entry_id)` deletes that store file; wired into
  `__init__.py`'s `async_remove_entry` so uninstalling the integration doesn't leave an
  orphaned file under `.storage`.

  `async_setup_periodic_refresh(entry)` is the one actual coordinator in this integration:
  it builds a `DataUpdateCoordinator[None]` (`config_entry=entry`, `update_method=`
  `self.async_refresh_camera_list`) on a `timedelta(minutes=self._update_interval_minutes)`
  interval, called from `__init__.py`'s `async_setup_entry` right after the initial
  `async_load_camera_list()`. It's a no-op (`self.coordinator` stays `None`) when the
  configured interval is 0. Uses `coordinator.async_refresh()`, not
  `async_config_entry_first_refresh()`, on purpose — the bundled JSON is already a working
  fallback, so a network hiccup on this initial background refresh shouldn't block entry
  setup with `ConfigEntryNotReady`. Immediately after that initial refresh it also calls
  `coordinator.async_add_listener(lambda: None)` — a permanent no-op listener. This isn't
  decorative: `DataUpdateCoordinator` only (re)arms its `update_interval` timer while
  `self._listeners` is non-empty (see HA core's `update_coordinator.py`), and since no
  entity observes this coordinator directly, without that listener the timer would arm
  once (implicitly, via the manual `async_refresh()` above) and then never get rearmed —
  the configured interval would silently only ever fire once, at startup. `config_entry=
  entry` above means HA already wires `coordinator.async_shutdown()` into the entry's
  unload, so this listener doesn't need manual cleanup.
- `config_flow.py` — single step (`user`): a `SelectSelector` (DROPDOWN, `multiple=True`)
  built from the bundled camera list — no login/API call needed for setup, unlike the
  ToanThang sibling — plus a second `SelectSelector` (DROPDOWN, `custom_value=True`,
  options from `UPDATE_INTERVAL_OPTIONS`) for `CONF_UPDATE_INTERVAL`, mirroring the
  ToanThang sibling's `_SCAN_INTERVAL_SELECTOR`/`SCAN_INTERVAL_OPTIONS`. `manifest.json`
  sets `"single_config_entry": true` (HA's built-in singleton mechanism), so there's no
  manual `_abort_if_unique_id_configured` dance here. `OptionsFlowHandler` re-shows both
  selectors (camera list live-reloaded from the bundled file, in case the list-refresh
  button changed it) to change the camera selection or the refresh interval later — a
  change reloads the entry (`async_update_listener`), which re-creates the coordinator
  with the new interval.
- `image.py` — `IhanoiSnapshotImage(ImageEntity)`, one per selected camera_id.
  `_attr_should_poll = False`; `async_image()` just returns the account's cached bytes for
  that camera_id. Listens for `f"{SIGNAL_CAMERA_UPDATED}_{camera_id}"` via
  `async_dispatcher_connect` in `async_added_to_hass` to know when to
  `async_write_ha_state()` — there's no other trigger for this entity to update itself.
  Failure handling lives in `device.py`'s `async_update_camera()`: a camera that's down /
  returns no data does **not** overwrite the cached bytes (that would blank the entity and
  trigger HA image errors) — it records `CameraSnapshot.last_error`, fires the dispatcher
  signal anyway (so the sensor's `last_error` attribute updates), and returns `False`. Only
  a genuine misconfig (camera_id absent from the list) still raises. So `image.py` keeps
  its last good frame across an outage; `last_updated` (hence the sensor below) only
  advances on a *successful* capture. `__init__` seeds `_attr_image_last_updated` from
  `account.snapshots[camera_id].last_updated` directly (rather than waiting for the first
  dispatcher signal) so a snapshot restored by `device.py`'s
  `async_load_persisted_snapshots()` after a real HA restart renders immediately.
- `sensor.py` — `IhanoiLastUpdateSensor(SensorEntity)`, one per camera,
  `SensorDeviceClass.TIMESTAMP` + `EntityCategory.DIAGNOSTIC`. `native_value` is the
  snapshot's `last_updated` (tz-aware `dt_util.now()`), with `last_error` exposed as an
  extra state attribute so automations can detect a down camera even though the button no
  longer raises for that case. Same dispatcher-signal-driven update pattern as `image.py`.
- `button.py` — two entity classes: `IhanoiSnapshotUpdateButton` (one per camera — the
  "update trigger... callable via automation" from the task brief; `async_press()` just
  calls `account.async_update_camera(camera_id)`) and `IhanoiCameraListRefreshButton` (one
  per config entry, `EntityCategory.CONFIG`, calls `account.async_refresh_camera_list()` --
  which, per above, also re-captures every selected camera's snapshot, so pressing this one
  button is enough after a list refresh instead of also pressing each camera's own button).
  Both wrap failures in `HomeAssistantError` so they surface cleanly in the UI/automation
  traces instead of as a bare stack trace — but note the per-camera button only *raises*
  for a real misconfig now; a merely-down camera makes `async_update_camera()` return
  `False`, which the button just logs (the previous image is kept — see `image.py` above).
- `ihanoi_camera.json` — the bundled/"mang đi sẵn" (pre-shipped) camera table, a copy of
  `working/ihanoi_camera.json`. Read by `config_flow.py` (for the dropdown) and
  `device.py` (at entry setup); overwritten in place by
  `IhanoiCameraListRefreshButton`/`async_refresh_camera_list()`. Since it embeds `wss_url`
  session tokens that expire, don't assume the bundled copy's URLs are live — that's
  exactly what the refresh button is for.
- `strings.json` / `translations/{vi,en}.json` — config/options flow UI text, Vietnamese
  primary (per the sibling convention), keep both in sync.
- `fonts/DejaVuSans.ttf` (+ `fonts/LICENSE`) — bundled so `hevc.py`'s `drawtext` timestamp
  overlay works regardless of the host's fonts (see `hevc.py` above). DejaVu Sans is
  public-domain/Bitstream-Vera-licensed and freely redistributable; `fonts/LICENSE` is that
  license text, copied verbatim (attribution requirement, not a functional dependency).

## Commands

No build/lint/test tooling, and no `homeassistant`/`aiohttp`/`voluptuous` pip packages
installed in this environment by default — Pylance's "import could not be resolved"
warnings on `homeassistant.*` are expected here, matching the `ha-toanthanggps-com`
sibling. `requirements.txt` at the repo root (`pip install -r requirements.txt`) is a
**dev-only** convenience to get those packages locally for import-testing this code or
running the `working/` prototype scripts — it's not how Home Assistant installs a custom
integration's own dependencies (that's `manifest.json`'s `requirements` array, which stays
`[]` here on purpose: aiohttp/voluptuous ship with HA core, and `ffmpeg` isn't pip-
installable at all).

- Syntax-check: `python3 -m py_compile custom_components/ihanoi_live_snapshot/*.py`.
- `hevc.py` has zero `homeassistant`/third-party imports, so its `KeyframeCollector`/
  `build_annexb` logic can be exercised directly with `python3 -c "import hevc; ..."` from
  inside `custom_components/ihanoi_live_snapshot/`.
- For everything else (`api.py`'s `_build_camera_table`, `device.py`'s
  `IhanoiSnapshotAccount`, the config flow), there's no real HA instance to run here —
  validate by stubbing `homeassistant.*`/`aiohttp`/`voluptuous` in `sys.modules` and
  importing the module standalone (same approach the `ha-toanthanggps-com` sibling's
  `CLAUDE.md` describes for its `ha-wadaco-water` sibling). This was done ad hoc when
  scaffolding the integration; there's no committed stub/test harness for it yet — worth
  building one (e.g. under a `tests/` dir with `pytest-homeassistant-custom-component`) if
  this integration keeps growing.

## The reverse-engineered snapshot logic (`working/`)

`working/CLAUDE.md` and `working/README.md` have the full writeup; the short version, for
context on what `hevc.py`/`api.py` above were ported from:

- `working/ihanoi_hevc.py` — the framing/`KeyframeCollector` logic, ported into
  `custom_components/ihanoi_live_snapshot/hevc.py` (see above for the one behavioral
  difference in the ffmpeg-decode step).
- `working/snapshot_ihanoi_livecamera.py` — reference implementation of the
  connect/send-`"mobile:"`/collect-until-done/decode loop, ported (and switched from
  `websocket-client` to aiohttp) into `api.py`'s `async_capture_snapshot`.
- `working/update_ihanoi_camera_list.py` — fetches
  `https://cds.hanoi.gov.vn/api/1.0/public/video-wall-cameras-v2` and writes
  `ihanoi_camera.json`; ported into `api.py`'s `async_fetch_camera_list`/
  `_build_camera_table`, invoked by `device.py`'s `async_refresh_camera_list`.

Dependencies used by the prototype: `websocket-client` (`import websocket`) and the
`ffmpeg` CLI on `PATH`. The integration only still needs the latter (a system binary, not
pip-installable — not declarable in `manifest.json`; `hevc.decode_first_frame_to_png`
raises a clear `RuntimeError` if the `ffmpeg` call fails, but there's no `shutil.which`
pre-flight check yet).

### Working with the prototype scripts directly

```bash
python3 working/snapshot_ihanoi_livecamera.py --camera-id gm9SoV9AOg -o out.png
python3 working/update_ihanoi_camera_list.py
```

Since `working/` is gitignored, `git status`/`git diff` won't show edits made there — don't
rely on git to track or review changes to those files.
