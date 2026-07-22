from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_CAMERAS, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_MINUTES, DOMAIN
from .device import IhanoiSnapshotAccount

PLATFORMS = ["image", "button", "sensor", "binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the iHanoi Live Snapshot entry and its selected cameras."""
    dataset = {**entry.data, **entry.options}

    account = IhanoiSnapshotAccount(
        hass,
        dataset[CONF_CAMERAS],
        dataset.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_MINUTES),
    )
    await account.async_load_camera_list()
    await account.async_setup_periodic_refresh(entry)

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
    """Selected-camera list changed -- reload via HA's own reload machinery so
    entry.state transitions correctly (see the toanthang_gps sibling integration for
    why calling async_setup_entry/async_unload_entry directly instead is wrong)."""
    await hass.config_entries.async_reload(entry.entry_id)
