"""Number entity: per-camera JPEG compression quality (30-100%).

Same setting as the config/options flow's "quality" step (see config_flow.py), just
exposed as an entity so it can be adjusted from a dashboard/automation without going
through Settings > Configure each time. Changing it calls
IhanoiSnapshotAccount.async_set_camera_quality, which persists into the config entry's
options -- so the two stay in sync and the entity's value survives a reload/restart.
"""
from __future__ import annotations

from homeassistant.components.number import (
    DOMAIN as ENTITY_DOMAIN,
    NumberEntity,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MAX_JPEG_QUALITY, MIN_JPEG_QUALITY
from .device import IhanoiSnapshotAccount


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    account: IhanoiSnapshotAccount = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        IhanoiCameraQualityNumber(account, camera_id) for camera_id in account.camera_ids
    )


class IhanoiCameraQualityNumber(NumberEntity):
    """Per-camera JPEG compression quality slider (30-100%)."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = MIN_JPEG_QUALITY
    _attr_native_max_value = MAX_JPEG_QUALITY
    _attr_native_step = 5
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER

    def __init__(self, account: IhanoiSnapshotAccount, camera_id: str) -> None:
        self._account = account
        self._camera_id = camera_id
        self._attr_unique_id = f"{camera_id}_quality".lower()
        self.entity_id = f"{ENTITY_DOMAIN}.{camera_id}_quality".lower()

    @property
    def name(self) -> str:
        return f"{self._account.camera_display_name(self._camera_id)} JPEG Quality"

    @property
    def device_info(self) -> DeviceInfo:
        return self._account.device_info(self._camera_id)

    @property
    def available(self) -> bool:
        return self._camera_id in self._account.cameras

    @property
    def native_value(self) -> int:
        return self._account.camera_quality(self._camera_id)

    async def async_set_native_value(self, value: float) -> None:
        await self._account.async_set_camera_quality(self._camera_id, int(value))
        # native_value reads straight from the account, which is already updated at this
        # point -- write it now instead of waiting for the config-entry reload below (that
        # reload is suppressed for this call anyway; see async_set_camera_quality) so the
        # slider/history reflect the new value immediately.
        self.async_write_ha_state()
