"""Config flow for iHanoi Live Snapshot.

Single-step: pick which cameras to add from a dropdown built off the bundled
ihanoi_camera.json (no login/API call needed for this step -- the file "đã mang đi sẵn").
`manifest.json`'s `single_config_entry` means only one entry ever exists; the options
flow below is how the selected-camera list changes after setup.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from . import api
from .const import CAMERA_LIST_FILENAME, CONF_CAMERAS, DOMAIN

_LOGGER = logging.getLogger(__name__)

_CAMERA_LIST_PATH = Path(__file__).parent / CAMERA_LIST_FILENAME


def _camera_selector(cameras: dict[str, dict[str, Any]]) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(value=camera_id, label=_display_label(camera_id, cam))
                for camera_id, cam in sorted(
                    cameras.items(), key=lambda kv: kv[1].get("name") or kv[0]
                )
            ],
            multiple=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _display_label(camera_id: str, camera: dict[str, Any]) -> str:
    name = camera.get("name") or camera_id
    return f"{name} ({camera_id})"


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for iHanoi Live Snapshot."""

    VERSION = 1

    def __init__(self) -> None:
        self._errors: dict[str, str] = {}
        self._cameras: dict[str, dict[str, Any]] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return OptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        self._errors = {}

        if not self._cameras:
            self._cameras = await self.hass.async_add_executor_job(
                api.load_camera_list, _CAMERA_LIST_PATH
            )

        if user_input is not None:
            cameras = user_input[CONF_CAMERAS]
            if not cameras:
                self._errors["base"] = "no_cameras_selected"
            else:
                return self.async_create_entry(
                    title="iHanoi Live Snapshot", data={CONF_CAMERAS: cameras}
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_CAMERAS, default=[]): _camera_selector(self._cameras)}
            ),
            errors=self._errors,
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Change which cameras are synced after setup."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._errors: dict[str, str] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        self._errors = {}
        cameras = await self.hass.async_add_executor_job(
            api.load_camera_list, _CAMERA_LIST_PATH
        )
        current = self._config_entry.options.get(
            CONF_CAMERAS, self._config_entry.data.get(CONF_CAMERAS, [])
        )

        if user_input is not None:
            selected = user_input[CONF_CAMERAS]
            if not selected:
                self._errors["base"] = "no_cameras_selected"
            else:
                return self.async_create_entry(title="", data={CONF_CAMERAS: selected})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_CAMERAS, default=current): _camera_selector(cameras)}
            ),
            errors=self._errors,
        )
