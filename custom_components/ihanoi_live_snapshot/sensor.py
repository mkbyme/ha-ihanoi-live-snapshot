"""Sensor entity: the timestamp of the last successful snapshot per camera.

Like the image entity there's no polling -- it re-renders only when the paired button
(button.py) triggers a capture, which pushes a per-camera dispatcher signal here. On a
failed capture the timestamp stays put (the image entity keeps its last good frame); the
failure reason is exposed on the `last_error` attribute so automations can still detect a
camera that's down.
"""
from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components.sensor import (
    DOMAIN as ENTITY_DOMAIN,
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_CAMERA_UPDATED
from .device import IhanoiSnapshotAccount

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """One 'Last Update' sensor per selected camera."""
    account: IhanoiSnapshotAccount = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        IhanoiLastUpdateSensor(account, camera_id) for camera_id in account.camera_ids
    )


class IhanoiLastUpdateSensor(SensorEntity):
    """Timestamp of the last successful snapshot capture for one camera."""

    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, account: IhanoiSnapshotAccount, camera_id: str) -> None:
        self._account = account
        self._camera_id = camera_id
        self._attr_unique_id = f"{camera_id}_last_update".lower()
        self.entity_id = f"{ENTITY_DOMAIN}.{camera_id}_last_update".lower()

    @property
    def name(self) -> str:
        return f"{self._account.camera_display_name(self._camera_id)} Last Update"

    @property
    def device_info(self) -> DeviceInfo:
        return self._account.device_info(self._camera_id)

    @property
    def available(self) -> bool:
        return self._camera_id in self._account.cameras

    @property
    def native_value(self) -> datetime | None:
        return self._account.snapshots[self._camera_id].last_updated

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        return {"last_error": self._account.snapshots[self._camera_id].last_error}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_CAMERA_UPDATED}_{self._camera_id}",
                self._handle_camera_updated,
            )
        )

    @callback
    def _handle_camera_updated(self) -> None:
        self.async_write_ha_state()
