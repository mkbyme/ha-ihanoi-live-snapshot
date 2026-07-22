"""Button entities.

- `IhanoiSnapshotUpdateButton`: one per camera -- the "update trigger" from README.md,
  meant to be called from automations. Pressing it captures a fresh snapshot and pushes
  it to that camera's image entity.
- `IhanoiCameraListRefreshButton`: one per config entry -- re-fetches
  ihanoi_camera.json from the live API (the wss_url session tokens it contains expire).
"""
from __future__ import annotations

import logging

from homeassistant.components.button import DOMAIN as ENTITY_DOMAIN, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .device import IhanoiSnapshotAccount

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    account: IhanoiSnapshotAccount = hass.data[DOMAIN][entry.entry_id]

    entities: list[ButtonEntity] = [
        IhanoiSnapshotUpdateButton(account, camera_id) for camera_id in account.camera_ids
    ]
    entities.append(IhanoiCameraListRefreshButton(account, entry))
    async_add_entities(entities)


class IhanoiSnapshotUpdateButton(ButtonEntity):
    """Per-camera 'capture a new snapshot now' trigger."""

    _attr_should_poll = False

    def __init__(self, account: IhanoiSnapshotAccount, camera_id: str) -> None:
        self._account = account
        self._camera_id = camera_id
        self._attr_unique_id = f"{camera_id}_update".lower()
        self.entity_id = f"{ENTITY_DOMAIN}.{camera_id}_update".lower()

    @property
    def name(self) -> str:
        return f"{self._account.camera_display_name(self._camera_id)} Update"

    @property
    def device_info(self) -> DeviceInfo:
        return self._account.device_info(self._camera_id)

    @property
    def available(self) -> bool:
        return self._camera_id in self._account.cameras

    async def async_press(self) -> None:
        try:
            await self._account.async_update_camera(self._camera_id)
        except Exception as err:
            raise HomeAssistantError(
                f"Failed to capture a snapshot for {self._camera_id}: {err}"
            ) from err


class IhanoiCameraListRefreshButton(ButtonEntity):
    """Re-fetch ihanoi_camera.json from the live API."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_name = "Update Camera List"

    def __init__(self, account: IhanoiSnapshotAccount, entry: ConfigEntry) -> None:
        self._account = account
        self._attr_unique_id = f"{entry.entry_id}_refresh_camera_list"
        self.entity_id = f"{ENTITY_DOMAIN}.ihanoi_update_camera_list"

    async def async_press(self) -> None:
        try:
            await self._account.async_refresh_camera_list()
        except Exception as err:
            raise HomeAssistantError(f"Failed to refresh the camera list: {err}") from err
