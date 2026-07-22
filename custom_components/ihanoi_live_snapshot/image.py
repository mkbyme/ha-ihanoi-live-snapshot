"""Image entity: one per selected camera, showing its most recently captured snapshot.

There's no polling -- the cached bytes only change when the paired button entity
(button.py) captures a new one, which then pushes a dispatcher signal here.
"""
from __future__ import annotations

import logging

from homeassistant.components.image import DOMAIN as ENTITY_DOMAIN, ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_CAMERA_UPDATED
from .device import IhanoiSnapshotAccount

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """One image entity per selected camera."""
    account: IhanoiSnapshotAccount = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        IhanoiSnapshotImage(hass, account, camera_id) for camera_id in account.camera_ids
    )


class IhanoiSnapshotImage(ImageEntity):
    """The last snapshot captured for one camera."""

    _attr_should_poll = False
    _attr_content_type = "image/png"

    def __init__(self, hass: HomeAssistant, account: IhanoiSnapshotAccount, camera_id: str) -> None:
        super().__init__(hass)
        self._account = account
        self._camera_id = camera_id
        self._attr_unique_id = f"{camera_id}_image".lower()
        self.entity_id = f"{ENTITY_DOMAIN}.{camera_id}_image".lower()

    @property
    def name(self) -> str:
        return self._account.camera_display_name(self._camera_id)

    @property
    def device_info(self) -> DeviceInfo:
        return self._account.device_info(self._camera_id)

    @property
    def available(self) -> bool:
        return self._camera_id in self._account.cameras

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
        self._attr_image_last_updated = self._account.snapshots[self._camera_id].last_updated
        self.async_write_ha_state()

    async def async_image(self) -> bytes | None:
        return self._account.snapshots[self._camera_id].image
