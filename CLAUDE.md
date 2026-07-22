# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status and goal

The task (`README.md`, in Vietnamese) was to build a HACS integration for Home Assistant,
based on the algorithm reverse-engineered in `working/`, modeled structurally on the
sibling repo `ha-toanthanggps-com`. That integration is now scaffolded at
`custom_components/ihanoi_live_snapshot/` (domain `ihanoi_live_snapshot`). Two things to
have loaded before touching it further:

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

No `DataUpdateCoordinator`/polling anywhere in this integration — snapshots are captured
only on demand (a button press), so there's nothing to poll on a schedule. State instead
flows: button press → `IhanoiSnapshotAccount.async_update_camera()` → dispatcher signal →
the paired image entity re-renders. Keep this in mind before reaching for a coordinator
pattern here; it doesn't fit.

- `const.py` — domain, `CONF_CAMERAS`, the bundled camera-list filename, the iHanoi API
  URL, WS handshake constants (`CLIENT_HELLO = "mobile:"`, user-agent), `MAX_NAME_LENGTH`
  (100 — entity/device names are the camera's `name` from `ihanoi_camera.json`, truncated
  to this per the task brief), and the dispatcher signal name template.
- `hevc.py` — ported from `working/ihanoi_hevc.py` almost verbatim: the 12-byte per-message
  framing header, NAL type constants, and `KeyframeCollector` (state machine: waits for a
  VPS(32)/SPS(33)/PPS(34) run, collects the IDR slice(s) that follow, flags itself `done`
  the instant the first non-parameter-set/non-IDR NAL arrives). `decode_first_frame_to_png`
  differs from the prototype's `decode_first_frame`: it pipes ffmpeg's PNG output back
  through stdout as bytes (`-f image2 -c:v png pipe:1`) instead of writing to a file path,
  since `ImageEntity` needs in-memory bytes, not a file. Still a blocking subprocess call —
  only ever invoked through `hass.async_add_executor_job`.
- `api.py` — camera-list fetch/table-building (ported from
  `working/update_ihanoi_camera_list.py`) plus live snapshot capture (ported from
  `working/snapshot_ihanoi_livecamera.py`'s connect/send-hello/read-until-done loop). One
  deliberate deviation from the prototype: this uses **aiohttp** (`ClientSession.ws_connect`)
  instead of the `websocket-client` package the prototype used, since aiohttp is already a
  Home Assistant core dependency — avoids adding a `requirements` entry to `manifest.json`.
  `async_capture_snapshot` bounds the whole connect-send-collect loop in one
  `asyncio.timeout()` rather than relying on a per-call socket timeout.
- `device.py` — `IhanoiSnapshotAccount`: not a coordinator, just the runtime store for one
  config entry. Holds the camera lookup table (loaded from the bundled
  `ihanoi_camera.json`), a `CameraSnapshot(image, last_updated)` per selected camera_id,
  `async_update_camera()` (capture + store + `async_dispatcher_send`), and
  `async_refresh_camera_list()` (re-fetch from the live API, overwrite the bundled file in
  place). Also centralizes `camera_display_name()`/`device_info()` (name truncation +
  `DeviceInfo` construction) so `image.py`/`button.py` don't duplicate that logic.
- `config_flow.py` — single step (`user`): a `SelectSelector` (DROPDOWN, `multiple=True`)
  built from the bundled camera list — no login/API call needed for setup, unlike the
  ToanThang sibling. `manifest.json` sets `"single_config_entry": true` (HA's built-in
  singleton mechanism), so there's no manual `_abort_if_unique_id_configured` dance here.
  `OptionsFlowHandler` re-shows the same selector (live-reloaded from the bundled file, in
  case the list-refresh button changed it) to add/remove cameras later.
- `image.py` — `IhanoiSnapshotImage(ImageEntity)`, one per selected camera_id.
  `_attr_should_poll = False`; `async_image()` just returns the account's cached bytes for
  that camera_id. Listens for `f"{SIGNAL_CAMERA_UPDATED}_{camera_id}"` via
  `async_dispatcher_connect` in `async_added_to_hass` to know when to
  `async_write_ha_state()` — there's no other trigger for this entity to update itself.
- `button.py` — two entity classes: `IhanoiSnapshotUpdateButton` (one per camera — the
  "update trigger... callable via automation" from the task brief; `async_press()` just
  calls `account.async_update_camera(camera_id)`) and `IhanoiCameraListRefreshButton` (one
  per config entry, `EntityCategory.CONFIG`, calls `account.async_refresh_camera_list()`).
  Both wrap failures in `HomeAssistantError` so they surface cleanly in the UI/automation
  traces instead of as a bare stack trace.
- `ihanoi_camera.json` — the bundled/"mang đi sẵn" (pre-shipped) camera table, a copy of
  `working/ihanoi_camera.json`. Read by `config_flow.py` (for the dropdown) and
  `device.py` (at entry setup); overwritten in place by
  `IhanoiCameraListRefreshButton`/`async_refresh_camera_list()`. Since it embeds `wss_url`
  session tokens that expire, don't assume the bundled copy's URLs are live — that's
  exactly what the refresh button is for.
- `strings.json` / `translations/{vi,en}.json` — config/options flow UI text, Vietnamese
  primary (per the sibling convention), keep both in sync.

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
