"""Client for the iHanoi public camera-list API and live-camera WebSocket capture.

Unlike the working/ prototype (which uses `websocket-client` + a blocking socket loop),
this uses aiohttp -- already a Home Assistant core dependency -- so no extra
`requirements` entry is needed in manifest.json.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import API_URL, CLIENT_HELLO, DEFAULT_CAPTURE_TIMEOUT, WS_USER_AGENT
from .hevc import KeyframeCollector, build_annexb, decode_first_frame_to_png

_LOGGER = logging.getLogger(__name__)


def load_camera_list(path: Path) -> dict[str, dict[str, Any]]:
    """Blocking file read -- call through hass.async_add_executor_job."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_camera_list(path: Path, table: dict[str, dict[str, Any]]) -> None:
    """Blocking file write -- call through hass.async_add_executor_job."""
    with path.open("w", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False, indent=2, sort_keys=True)


def _first_stream(profile: list[dict] | None, protocol: str) -> tuple[str | None, str | None]:
    for p in profile or []:
        for s in p.get("streams") or []:
            if s.get("protocol") == protocol:
                return s.get("source"), p.get("resolution")
    return None, None


def _build_camera_table(raw: dict) -> dict[str, dict[str, Any]]:
    table: dict[str, dict[str, Any]] = {}
    for cam in raw.get("data", []):
        camera_id = cam.get("camera_id")
        if not camera_id:
            continue
        wss_url, resolution = _first_stream(cam.get("profile"), "WSS")
        https_url, _ = _first_stream(cam.get("profile"), "HTTPS")
        if not wss_url:
            continue
        table[camera_id] = {
            "id": cam.get("id"),
            "name": cam.get("name"),
            "address": cam.get("address"),
            "ward_name": cam.get("ward_name"),
            "lat": cam.get("lat"),
            "lng": cam.get("lng"),
            "resolution": resolution,
            "wss_url": wss_url,
            "https_url": https_url,
        }
    return table


async def async_fetch_camera_list(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    """Fetch the live camera list from the iHanoi public API."""
    session = async_get_clientsession(hass)
    async with session.get(
        API_URL, headers={"User-Agent": "curl/8.0"}, timeout=aiohttp.ClientTimeout(total=20)
    ) as resp:
        raw = await resp.json(content_type=None)
    return _build_camera_table(raw)


async def async_capture_snapshot(
    hass: HomeAssistant, wss_url: str, timeout: float = DEFAULT_CAPTURE_TIMEOUT
) -> bytes:
    """Open the camera's live WebSocket, collect exactly one full keyframe (stopping the
    instant it's assembled), and decode it to PNG bytes."""
    session = async_get_clientsession(hass)
    collector = KeyframeCollector()

    async with asyncio.timeout(timeout):
        async with session.ws_connect(wss_url, headers={"User-Agent": WS_USER_AGENT}) as ws:
            await ws.send_str(CLIENT_HELLO)
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    collector.feed(msg.data)
                    if collector.done:
                        break
                elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                    break

    if not collector.nals:
        raise RuntimeError("Never saw a VPS NAL (type 32) before the connection ended.")

    annexb = build_annexb(collector.nals)
    return await hass.async_add_executor_job(decode_first_frame_to_png, annexb)
