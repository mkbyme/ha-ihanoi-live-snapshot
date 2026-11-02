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
from .const import (
    CAMERA_LIST_FILENAME,
    CONF_CAMERA_QUALITY,
    CONF_CAMERAS,
    CONF_UPDATE_INTERVAL,
    DEFAULT_JPEG_QUALITY,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
    MAX_JPEG_QUALITY,
    MIN_JPEG_QUALITY,
    UPDATE_INTERVAL_OPTIONS,
)

_LOGGER = logging.getLogger(__name__)

_CAMERA_LIST_PATH = Path(__file__).parent / CAMERA_LIST_FILENAME

_QUALITY_FIELD_PREFIX = "quality_"

_UPDATE_INTERVAL_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=[str(minutes) for minutes in UPDATE_INTERVAL_OPTIONS],
        mode=selector.SelectSelectorMode.DROPDOWN,
        custom_value=True,
    )
)

_QUALITY_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=MIN_JPEG_QUALITY,
        max=MAX_JPEG_QUALITY,
        step=5,
        mode=selector.NumberSelectorMode.SLIDER,
        unit_of_measurement="%",
    )
)


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


def _quality_field_key(camera_id: str) -> str:
    return f"{_QUALITY_FIELD_PREFIX}{camera_id}"


def _camera_quality_schema(
    camera_ids: list[str],
    current: dict[str, int],
) -> vol.Schema:
    """One quality slider per selected camera_id. Field keys are dynamic
    (quality_<camera_id>), so the frontend can't show a translated per-camera label --
    the step's description lists camera_id -> name instead (see _camera_list_placeholder)."""
    return vol.Schema(
        {
            vol.Required(
                _quality_field_key(camera_id),
                default=current.get(camera_id, DEFAULT_JPEG_QUALITY),
            ): _QUALITY_SELECTOR
            for camera_id in camera_ids
        }
    )


def _camera_list_placeholder(camera_ids: list[str], cameras: dict[str, dict[str, Any]]) -> str:
    return "\n".join(
        f"- {camera_id}: {cameras.get(camera_id, {}).get('name') or camera_id}"
        for camera_id in camera_ids
    )


def _parse_camera_quality(
    camera_ids: list[str], user_input: dict[str, Any], errors: dict[str, str]
) -> dict[str, int]:
    quality: dict[str, int] = {}
    for camera_id in camera_ids:
        raw = user_input.get(_quality_field_key(camera_id), DEFAULT_JPEG_QUALITY)
        try:
            value = int(raw)
            if not MIN_JPEG_QUALITY <= value <= MAX_JPEG_QUALITY:
                raise ValueError
        except (TypeError, ValueError):
            errors["base"] = "invalid_jpeg_quality"
            value = DEFAULT_JPEG_QUALITY
        quality[camera_id] = value
    return quality


def _parse_update_interval(raw: str, errors: dict[str, str]) -> int:
    """Parse the (possibly custom-typed) update-interval selector value. On failure,
    records an error under "base" and returns a harmless placeholder -- callers must check
    `errors` before using the return value."""
    try:
        minutes = int(raw)
        if minutes < 0:
            raise ValueError
    except ValueError:
        errors["base"] = "invalid_update_interval"
        return 0
    return minutes


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for iHanoi Live Snapshot."""

    VERSION = 1

    def __init__(self) -> None:
        self._errors: dict[str, str] = {}
        self._cameras: dict[str, dict[str, Any]] = {}
        self._selected_cameras: list[str] = []
        self._update_interval: int = DEFAULT_UPDATE_INTERVAL_MINUTES

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
            update_interval = _parse_update_interval(user_input[CONF_UPDATE_INTERVAL], self._errors)
            if not cameras:
                self._errors["base"] = "no_cameras_selected"
            elif not self._errors:
                self._selected_cameras = cameras
                self._update_interval = update_interval
                return await self.async_step_quality()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CAMERAS, default=[]): _camera_selector(self._cameras),
                    vol.Required(
                        CONF_UPDATE_INTERVAL, default=str(DEFAULT_UPDATE_INTERVAL_MINUTES)
                    ): _UPDATE_INTERVAL_SELECTOR,
                }
            ),
            errors=self._errors,
        )

    async def async_step_quality(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Second step: per-camera JPEG compression quality, only reachable once the
        camera selection from async_step_user is known (the fields are dynamic, one per
        selected camera_id)."""
        self._errors = {}

        if user_input is not None:
            quality = _parse_camera_quality(self._selected_cameras, user_input, self._errors)
            if not self._errors:
                return self.async_create_entry(
                    title="iHanoi Live Snapshot",
                    data={
                        CONF_CAMERAS: self._selected_cameras,
                        CONF_UPDATE_INTERVAL: self._update_interval,
                        CONF_CAMERA_QUALITY: quality,
                    },
                )

        return self.async_show_form(
            step_id="quality",
            data_schema=_camera_quality_schema(self._selected_cameras, {}),
            errors=self._errors,
            description_placeholders={
                "camera_list": _camera_list_placeholder(self._selected_cameras, self._cameras)
            },
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Change which cameras are synced, the refresh interval, and per-camera JPEG
    quality after setup."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._errors: dict[str, str] = {}
        self._cameras: dict[str, dict[str, Any]] = {}
        self._selected_cameras: list[str] = []
        self._update_interval: int = DEFAULT_UPDATE_INTERVAL_MINUTES

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        self._errors = {}
        if not self._cameras:
            self._cameras = await self.hass.async_add_executor_job(
                api.load_camera_list, _CAMERA_LIST_PATH
            )
        current = self._config_entry.options.get(
            CONF_CAMERAS, self._config_entry.data.get(CONF_CAMERAS, [])
        )
        # A selected camera can be absent from the bundled list (e.g. it dropped off the
        # live API before the carry-over in device.py existed) -- still offer it as an
        # option, otherwise it can't be seen, let alone unticked, in this dropdown.
        for camera_id in current:
            self._cameras.setdefault(camera_id, {})
        current_interval = self._config_entry.options.get(
            CONF_UPDATE_INTERVAL,
            self._config_entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_MINUTES),
        )

        if user_input is not None:
            selected = user_input[CONF_CAMERAS]
            update_interval = _parse_update_interval(user_input[CONF_UPDATE_INTERVAL], self._errors)
            if not selected:
                self._errors["base"] = "no_cameras_selected"
            elif not self._errors:
                self._selected_cameras = selected
                self._update_interval = update_interval
                return await self.async_step_quality()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CAMERAS, default=current): _camera_selector(self._cameras),
                    vol.Required(
                        CONF_UPDATE_INTERVAL, default=str(current_interval)
                    ): _UPDATE_INTERVAL_SELECTOR,
                }
            ),
            errors=self._errors,
        )

    async def async_step_quality(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Second step: per-camera JPEG compression quality, defaulting to whatever's
        already configured for a given camera_id (or DEFAULT_JPEG_QUALITY if it's newly
        selected)."""
        self._errors = {}
        current_quality = self._config_entry.options.get(
            CONF_CAMERA_QUALITY, self._config_entry.data.get(CONF_CAMERA_QUALITY, {})
        )

        if user_input is not None:
            quality = _parse_camera_quality(self._selected_cameras, user_input, self._errors)
            if not self._errors:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_CAMERAS: self._selected_cameras,
                        CONF_UPDATE_INTERVAL: self._update_interval,
                        CONF_CAMERA_QUALITY: quality,
                    },
                )

        return self.async_show_form(
            step_id="quality",
            data_schema=_camera_quality_schema(self._selected_cameras, current_quality),
            errors=self._errors,
            description_placeholders={
                "camera_list": _camera_list_placeholder(self._selected_cameras, self._cameras)
            },
        )
