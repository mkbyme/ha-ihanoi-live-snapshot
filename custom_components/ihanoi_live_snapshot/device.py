"""Runtime store for one iHanoi Live Snapshot config entry.

Snapshot capture itself has no coordinator: a capture happens on demand (a button press,
meant to be called from automations) and pushes its result via a per-camera dispatcher
signal, not a poll. The one thing that IS on a `DataUpdateCoordinator` timer is the camera
list/wss_url table (see `async_setup_periodic_refresh`) -- and refreshing that list, either
via that timer or via the "Update Camera List" button, also re-captures every selected
camera's snapshot (see `async_refresh_camera_list`), since a stale wss_url is exactly what
that refresh just fixed.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import api
from .const import (
    CAMERA_LIST_FILENAME,
    CONF_DEVICE_MANUFACTURER,
    CONF_DEVICE_MODEL,
    DOMAIN,
    MAX_NAME_LENGTH,
    SIGNAL_CAMERA_UPDATED,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1


def _snapshot_to_json(snapshot: "CameraSnapshot") -> dict[str, Any]:
    return {
        "image": base64.b64encode(snapshot.image).decode("ascii") if snapshot.image else None,
        "last_updated": snapshot.last_updated.isoformat() if snapshot.last_updated else None,
        "last_error": snapshot.last_error,
        "online": snapshot.online,
    }


def _snapshot_from_json(data: dict[str, Any]) -> "CameraSnapshot":
    image_b64 = data.get("image")
    last_updated = data.get("last_updated")
    return CameraSnapshot(
        image=base64.b64decode(image_b64) if image_b64 else None,
        last_updated=dt_util.parse_datetime(last_updated) if last_updated else None,
        last_error=data.get("last_error"),
        online=data.get("online"),
    )


async def async_remove_persisted_snapshots(hass: HomeAssistant, entry_id: str) -> None:
    """Delete the on-disk snapshot cache for a removed config entry, so uninstalling
    the integration doesn't leave an orphaned file under `.storage`."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}_{entry_id}_snapshots").async_remove()


@dataclass
class CameraSnapshot:
    image: bytes | None = None
    last_updated: datetime | None = None
    last_error: str | None = None
    online: bool | None = None
    """Whether the last capture attempt succeeded -- None means no attempt has been made
    yet (entry just started up), so the binary_sensor can report "unknown" rather than a
    misleading on/off before the first capture."""


class IhanoiSnapshotAccount:
    """Owns the camera lookup table and the captured-image state for one entry's
    selected cameras."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        camera_ids: list[str],
        update_interval_minutes: int = 0,
    ) -> None:
        self.hass = hass
        self.camera_ids = camera_ids
        self._update_interval_minutes = update_interval_minutes
        self._camera_list_path = Path(__file__).parent / CAMERA_LIST_FILENAME
        self.cameras: dict[str, dict[str, Any]] = {}
        self.snapshots: dict[str, CameraSnapshot] = {
            camera_id: CameraSnapshot() for camera_id in camera_ids
        }
        self.coordinator: DataUpdateCoordinator[None] | None = None
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_{entry_id}_snapshots")

    async def async_load_camera_list(self) -> None:
        self.cameras = await self.hass.async_add_executor_job(
            api.load_camera_list, self._camera_list_path
        )

    async def async_load_persisted_snapshots(self) -> None:
        """Restore each selected camera's last known image/status from disk. Unlike a
        config-entry reload (which keeps this object, and therefore `self.snapshots`,
        alive in memory), a real HA restart creates a fresh IhanoiSnapshotAccount --
        without this, every camera's image/last_updated/online would reset to blank on
        every restart, not just cameras that happen to be offline at the time. Call this
        before entities are set up so they read the restored state on first render."""
        data = await self._store.async_load()
        if not data:
            return
        for camera_id, raw in data.get("snapshots", {}).items():
            if camera_id in self.snapshots:
                self.snapshots[camera_id] = _snapshot_from_json(raw)

    async def _async_save_snapshots(self) -> None:
        await self._store.async_save(
            {
                "snapshots": {
                    camera_id: _snapshot_to_json(snapshot)
                    for camera_id, snapshot in self.snapshots.items()
                }
            }
        )

    async def async_setup_periodic_refresh(self, entry: ConfigEntry) -> None:
        """Start a background re-fetch of the camera list (its wss_url session tokens
        expire), on top of the manual "Update Camera List" button. No-op if the configured
        interval is 0 -- see CONF_UPDATE_INTERVAL in const.py."""
        if not self._update_interval_minutes:
            return

        coordinator = DataUpdateCoordinator[None](
            self.hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_camera_list",
            update_method=self.async_refresh_camera_list,
            update_interval=timedelta(minutes=self._update_interval_minutes),
        )
        # Don't use async_config_entry_first_refresh: the bundled ihanoi_camera.json is
        # already loaded as a fallback, so a network hiccup here shouldn't block entry setup.
        await coordinator.async_refresh()
        # DataUpdateCoordinator only (re)arms its update_interval timer while it has at
        # least one listener (see async_add_listener/_schedule_refresh in HA core's
        # update_coordinator.py) -- no entity observes this coordinator directly, so
        # without a listener the timer never gets armed past the manual async_refresh()
        # above, and the configured interval is silently never honored again. This
        # permanent no-op listener is what keeps it firing; config_entry=entry above
        # means HA already cancels it via coordinator.async_shutdown() on unload/reload.
        coordinator.async_add_listener(lambda: None)
        self.coordinator = coordinator

    async def async_refresh_camera_list(self) -> None:
        """Re-fetch the camera list from the live API, overwrite the bundled file, and
        capture a fresh snapshot for every selected camera right after -- their wss_url
        may have just changed, so there's no longer a need to also press each camera's
        own Update button by hand. A capture failure for one camera is logged, not
        raised, so it doesn't mask a otherwise-successful list refresh.

        A camera that's down disappears from the live API response entirely (this is
        the iHanoi API's own signal for "offline", not a bug on our end) -- for any
        selected camera_id missing from the freshly fetched table, carry over its
        previous entry (name/wss_url/etc.) instead of dropping it, so its name/image
        stay put and it's marked offline below rather than raising a spurious
        "not found" error or going `unavailable`."""
        table = await api.async_fetch_camera_list(self.hass)
        missing_ids = {camera_id for camera_id in self.camera_ids if camera_id not in table}
        for camera_id in missing_ids:
            cached = self.cameras.get(camera_id)
            if cached is not None:
                table[camera_id] = cached

        await self.hass.async_add_executor_job(
            api.save_camera_list, self._camera_list_path, table
        )
        self.cameras = table

        async def _refresh_one(camera_id: str) -> None:
            if camera_id in missing_ids and camera_id in self.cameras:
                # Known camera, just absent from this fetch -- don't waste a full
                # capture timeout on a wss_url we already know is stale.
                await self._mark_camera_offline(
                    camera_id, "Camera is missing from the live camera list (offline)."
                )
                return
            await self.async_update_camera(camera_id)

        results = await asyncio.gather(
            *(_refresh_one(camera_id) for camera_id in self.camera_ids),
            return_exceptions=True,
        )
        for camera_id, result in zip(self.camera_ids, results):
            if isinstance(result, Exception):
                _LOGGER.warning(
                    "Failed to refresh the snapshot for %s after a camera list update: %s",
                    camera_id,
                    result,
                )

    async def _mark_camera_offline(self, camera_id: str, reason: str) -> None:
        """Mark a selected camera offline without attempting a capture. The cached
        name (via `self.cameras`) and the last captured image are left untouched --
        only `online`/`last_error` change, and `last_updated` (the successful-capture
        timestamp) deliberately doesn't move."""
        snapshot = self.snapshots.setdefault(camera_id, CameraSnapshot())
        snapshot.online = False
        snapshot.last_error = reason
        async_dispatcher_send(self.hass, f"{SIGNAL_CAMERA_UPDATED}_{camera_id}")
        await self._async_save_snapshots()

    async def async_update_camera(self, camera_id: str) -> bool:
        """Capture and store a fresh snapshot for one camera, then notify its entities.

        Returns True if a new image was captured, False if the camera was down / returned
        no data. In the latter case the previously captured image is deliberately kept
        (never overwritten with None) so the image entity doesn't go blank or error -- the
        failure is only recorded on `snapshot.last_error` and surfaced by the "Last Update"
        sensor. Only a genuine misconfiguration (camera_id not in the list) still raises."""
        camera = self.cameras.get(camera_id)
        if camera is None or not camera.get("wss_url"):
            raise RuntimeError(
                f"camera_id {camera_id!r} not found in {CAMERA_LIST_FILENAME} -- "
                "press 'Update Camera List' first."
            )

        snapshot = self.snapshots.setdefault(camera_id, CameraSnapshot())
        # Timestamp burned into the image (local time) and stored on the snapshot.
        now = dt_util.now()
        label = now.strftime("%Y-%m-%d %H:%M:%S")
        try:
            image = await api.async_capture_snapshot(
                self.hass, camera["wss_url"], label=label
            )
        except Exception as err:  # noqa: BLE001 -- camera down / bad wss_url / decode fail
            snapshot.last_error = str(err)
            snapshot.online = False
            _LOGGER.warning(
                "Snapshot capture failed for %s; keeping the previous image: %s",
                camera_id,
                err,
            )
            async_dispatcher_send(self.hass, f"{SIGNAL_CAMERA_UPDATED}_{camera_id}")
            await self._async_save_snapshots()
            return False

        if not image:
            snapshot.last_error = "Camera returned no snapshot data."
            snapshot.online = False
            _LOGGER.warning(
                "Snapshot capture returned no data for %s; keeping the previous image.",
                camera_id,
            )
            async_dispatcher_send(self.hass, f"{SIGNAL_CAMERA_UPDATED}_{camera_id}")
            await self._async_save_snapshots()
            return False

        snapshot.image = image
        snapshot.last_updated = now
        snapshot.last_error = None
        snapshot.online = True
        async_dispatcher_send(self.hass, f"{SIGNAL_CAMERA_UPDATED}_{camera_id}")
        await self._async_save_snapshots()
        return True

    def camera_display_name(self, camera_id: str) -> str:
        camera = self.cameras.get(camera_id)
        name = camera.get("name") if camera else None
        return (name or camera_id)[:MAX_NAME_LENGTH]

    def device_info(self, camera_id: str) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, camera_id)},
            name=self.camera_display_name(camera_id),
            manufacturer=CONF_DEVICE_MANUFACTURER,
            model=CONF_DEVICE_MODEL,
        )
