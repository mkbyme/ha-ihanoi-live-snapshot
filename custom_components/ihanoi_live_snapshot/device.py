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
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
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


@dataclass
class CameraSnapshot:
    image: bytes | None = None
    last_updated: datetime | None = None


class IhanoiSnapshotAccount:
    """Owns the camera lookup table and the captured-image state for one entry's
    selected cameras."""

    def __init__(
        self, hass: HomeAssistant, camera_ids: list[str], update_interval_minutes: int = 0
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

    async def async_load_camera_list(self) -> None:
        self.cameras = await self.hass.async_add_executor_job(
            api.load_camera_list, self._camera_list_path
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
        self.coordinator = coordinator

    async def async_refresh_camera_list(self) -> None:
        """Re-fetch the camera list from the live API, overwrite the bundled file, and
        capture a fresh snapshot for every selected camera right after -- their wss_url
        may have just changed, so there's no longer a need to also press each camera's
        own Update button by hand. A capture failure for one camera is logged, not
        raised, so it doesn't mask a otherwise-successful list refresh."""
        table = await api.async_fetch_camera_list(self.hass)
        await self.hass.async_add_executor_job(
            api.save_camera_list, self._camera_list_path, table
        )
        self.cameras = table

        results = await asyncio.gather(
            *(self.async_update_camera(camera_id) for camera_id in self.camera_ids),
            return_exceptions=True,
        )
        for camera_id, result in zip(self.camera_ids, results):
            if isinstance(result, Exception):
                _LOGGER.warning(
                    "Failed to refresh the snapshot for %s after a camera list update: %s",
                    camera_id,
                    result,
                )

    async def async_update_camera(self, camera_id: str) -> None:
        """Capture and store a fresh snapshot for one camera, then notify its entities."""
        camera = self.cameras.get(camera_id)
        if camera is None or not camera.get("wss_url"):
            raise RuntimeError(
                f"camera_id {camera_id!r} not found in {CAMERA_LIST_FILENAME} -- "
                "press 'Update Camera List' first."
            )

        image = await api.async_capture_snapshot(self.hass, camera["wss_url"])
        snapshot = self.snapshots.setdefault(camera_id, CameraSnapshot())
        snapshot.image = image
        snapshot.last_updated = dt_util.utcnow()
        async_dispatcher_send(self.hass, f"{SIGNAL_CAMERA_UPDATED}_{camera_id}")

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
