"""Runtime store for one iHanoi Live Snapshot config entry.

There is no DataUpdateCoordinator here: snapshots are captured on demand (a button
press, meant to be called from automations), never polled on a schedule. Entities push
updates to each other via a dispatcher signal per camera instead of pulling from a
coordinator.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
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

    def __init__(self, hass: HomeAssistant, camera_ids: list[str]) -> None:
        self.hass = hass
        self.camera_ids = camera_ids
        self._camera_list_path = Path(__file__).parent / CAMERA_LIST_FILENAME
        self.cameras: dict[str, dict[str, Any]] = {}
        self.snapshots: dict[str, CameraSnapshot] = {
            camera_id: CameraSnapshot() for camera_id in camera_ids
        }

    async def async_load_camera_list(self) -> None:
        self.cameras = await self.hass.async_add_executor_job(
            api.load_camera_list, self._camera_list_path
        )

    async def async_refresh_camera_list(self) -> None:
        """Re-fetch the camera list from the live API and overwrite the bundled file."""
        table = await api.async_fetch_camera_list(self.hass)
        await self.hass.async_add_executor_job(
            api.save_camera_list, self._camera_list_path, table
        )
        self.cameras = table

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
