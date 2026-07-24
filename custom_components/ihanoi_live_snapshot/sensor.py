"""Sensor entities: the timestamp of the last successful snapshot per camera, and a
camera-location sensor meant for Lovelace map cards.

Like the image entity there's no polling -- both entities re-render only when the paired
button (button.py) triggers a capture, which pushes a per-camera dispatcher signal here. On
a failed capture the "Last Update" timestamp stays put (the image entity keeps its last
good frame); the failure reason is exposed on the `last_error` attribute so automations can
still detect a camera that's down.
"""
from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components.image import DOMAIN as IMAGE_DOMAIN
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
    """One 'Last Update' sensor and one location sensor per selected camera."""
    account: IhanoiSnapshotAccount = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []
    for camera_id in account.camera_ids:
        entities.append(IhanoiLastUpdateSensor(account, camera_id))
        entities.append(IhanoiCameraLocationSensor(account, camera_id))
    async_add_entities(entities)


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


class IhanoiCameraLocationSensor(SensorEntity):
    """Camera location for Lovelace map cards -- `latitude`/`longitude` extra state
    attributes taken straight from the camera's `lat`/`lng` fields in
    ihanoi_camera.json (a fixed street camera, not something that needs a
    device_tracker's home/not_home semantics). The map card also renders an
    `entity_picture`, if the entity has one, as the marker itself instead of a plain
    dot -- so `entity_picture` here is read straight off the paired preview-image
    entity's own current state attribute rather than duplicating ImageEntity's
    token/URL logic, keeping the marker showing the last captured snapshot."""

    _attr_should_poll = False

    def __init__(self, account: IhanoiSnapshotAccount, camera_id: str) -> None:
        self._account = account
        self._camera_id = camera_id
        self._attr_unique_id = f"{camera_id}_location".lower()
        self.entity_id = f"{ENTITY_DOMAIN}.{camera_id}_location".lower()
        self._preview_entity_id = f"{IMAGE_DOMAIN}.{camera_id}_image_preview".lower()

    @property
    def name(self) -> str:
        return f"{self._account.camera_display_name(self._camera_id)} Location"

    @property
    def device_info(self) -> DeviceInfo:
        return self._account.device_info(self._camera_id)

    @property
    def available(self) -> bool:
        return self._camera_id in self._account.cameras

    @property
    def native_value(self) -> str | None:
        camera = self._account.cameras.get(self._camera_id)
        return camera.get("address") if camera else None

    @property
    def extra_state_attributes(self) -> dict[str, float]:
        camera = self._account.cameras.get(self._camera_id)
        lat = camera.get("lat") if camera else None
        lng = camera.get("lng") if camera else None
        if lat is None or lng is None:
            return {}
        return {"latitude": lat, "longitude": lng}

    @property
    def entity_picture(self) -> str | None:
        preview_state = self.hass.states.get(self._preview_entity_id)
        return preview_state.attributes.get("entity_picture") if preview_state else None

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
