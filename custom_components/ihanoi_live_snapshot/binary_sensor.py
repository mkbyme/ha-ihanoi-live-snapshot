"""Binary sensor: whether the last snapshot capture attempt for a camera succeeded.

`on` (CONNECTIVITY) means the last capture actually retrieved a keyframe from the camera's
WebSocket; `off` means it errored or returned no data (see device.py's
`async_update_camera`, which never clears the cached image on failure -- this entity is
the "is the camera actually reachable right now" signal that isn't visible from the image
entity alone, since that one just keeps showing the last good frame). `None`/unknown before
the first capture attempt after startup.
"""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    DOMAIN as ENTITY_DOMAIN,
    BinarySensorDeviceClass,
    BinarySensorEntity,
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
    """One camera-online binary sensor per selected camera."""
    account: IhanoiSnapshotAccount = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        IhanoiCameraOnlineBinarySensor(account, camera_id) for camera_id in account.camera_ids
    )


class IhanoiCameraOnlineBinarySensor(BinarySensorEntity):
    """`on` if the last capture attempt for this camera succeeded, `off` if it failed."""

    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, account: IhanoiSnapshotAccount, camera_id: str) -> None:
        self._account = account
        self._camera_id = camera_id
        self._attr_unique_id = f"{camera_id}_online".lower()
        self.entity_id = f"{ENTITY_DOMAIN}.{camera_id}_online".lower()

    @property
    def name(self) -> str:
        return f"{self._account.camera_display_name(self._camera_id)} Online"

    @property
    def device_info(self) -> DeviceInfo:
        return self._account.device_info(self._camera_id)

    @property
    def available(self) -> bool:
        return self._camera_id in self._account.cameras

    @property
    def is_on(self) -> bool | None:
        return self._account.snapshots[self._camera_id].online

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
