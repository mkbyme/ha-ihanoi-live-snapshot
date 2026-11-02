from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_CAMERA_QUALITY,
    CONF_CAMERAS,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
)
from .device import IhanoiSnapshotAccount, async_remove_persisted_snapshots

PLATFORMS = ["image", "button", "sensor", "binary_sensor", "number"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the iHanoi Live Snapshot entry and its selected cameras."""
    dataset = {**entry.data, **entry.options}

    account = IhanoiSnapshotAccount(
        hass,
        entry.entry_id,
        dataset[CONF_CAMERAS],
        dataset.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_MINUTES),
        dataset.get(CONF_CAMERA_QUALITY, {}),
    )
    await account.async_load_persisted_snapshots()
    await account.async_load_camera_list()
    await account.async_setup_periodic_refresh(entry)
    _async_remove_stale_devices(hass, entry, dataset[CONF_CAMERAS])

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = account
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Options changed -- reload via HA's own reload machinery so entry.state transitions
    correctly (see the toanthang_gps sibling integration for why calling
    async_setup_entry/async_unload_entry directly instead is wrong).

    Skipped for a quality-number-entity-triggered options write: device.py's
    IhanoiSnapshotAccount.async_set_camera_quality already applies that change in memory
    before persisting it, so tearing down and rebuilding every platform just to pick up a
    value that's already live would only add a visible flicker/delay for no benefit. A
    camera-selection/interval change from the config/options flow still reloads normally."""
    account = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if account is not None and account.consume_reload_suppression():
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Enable the "Delete" button on a camera's device page. Without this hook HA
    offers no way to remove a device from the UI at all -- and since a camera that drops
    off the live API is deliberately kept (see device.py's async_refresh_camera_list),
    there was otherwise no way to get rid of one short of deleting the whole entry."""
    camera_ids = [
        identifier for domain, identifier in device_entry.identifiers if domain == DOMAIN
    ]
    if not camera_ids:
        return False
    account = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if account is not None:
        for camera_id in camera_ids:
            await account.async_remove_camera(camera_id)
    return True


def _async_remove_stale_devices(
    hass: HomeAssistant, entry: ConfigEntry, camera_ids: list[str]
) -> None:
    """Remove devices of cameras no longer selected (deselected via the options flow) --
    otherwise they linger in the registry with every entity "no longer provided". This
    only looks at the user's selection, not the live API list, so a camera that merely
    went offline is still kept."""
    device_registry = dr.async_get(hass)
    selected = set(camera_ids)
    for device_entry in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if not any(
            domain == DOMAIN and identifier in selected
            for domain, identifier in device_entry.identifiers
        ):
            device_registry.async_update_device(
                device_entry.id, remove_config_entry_id=entry.entry_id
            )


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the persisted snapshot cache along with the entry -- otherwise it's an
    orphaned file under `.storage` forever, since only async_setup_entry knows its
    entry_id-derived key."""
    await async_remove_persisted_snapshots(hass, entry.entry_id)
