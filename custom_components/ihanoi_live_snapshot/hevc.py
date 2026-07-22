"""HEVC framing/keyframe-collection logic for the iHanoi live-camera WebSocket protocol.

Ported from the reverse-engineering prototype in the project's (gitignored, local-only)
`working/` directory rather than imported from it, since that directory doesn't ship with
the HACS package. See the project's CLAUDE.md and `working/CLAUDE.md` for the full
reverse-engineering writeup this is based on.

Each binary WebSocket message is one raw HEVC NAL unit prefixed with a fixed 12-byte
header (1 varying byte, 6-byte constant magic, 2 varying bytes, 2-byte constant, 1-byte
per-picture-group counter); byte 12 onward is the NAL unit itself (2-byte NAL header +
RBSP, no length prefix, no Annex-B start code). A GOP boundary/keyframe is announced by a
VPS(32)/SPS(33)/PPS(34) run followed by one or more IDR slice NAL(s) (19/20, occasionally
21); the first NAL after that run that isn't a parameter set or IDR slice marks the
keyframe picture as complete.
"""
from __future__ import annotations

import subprocess

START_CODE = b"\x00\x00\x00\x01"
PREFIX_LEN = 12

NAL_VPS = 32
NAL_SPS = 33
NAL_PPS = 34
NAL_IDR_W_RADL = 19
NAL_IDR_N_LP = 20
NAL_CRA = 21

PARAM_SET_TYPES = {NAL_VPS, NAL_SPS, NAL_PPS}
KEYFRAME_SLICE_TYPES = {NAL_IDR_W_RADL, NAL_IDR_N_LP, NAL_CRA}


def _parse_nal(ws_binary_message: bytes) -> tuple[int, bytes] | None:
    """Strip the 12-byte prefix off one binary WS frame and return (nal_type, raw_nal_bytes),
    or None if the frame is too short to hold a NAL."""
    nal = ws_binary_message[PREFIX_LEN:]
    if len(nal) < 2:
        return None
    nal_type = (nal[0] >> 1) & 0x3F
    return nal_type, nal


class KeyframeCollector:
    """Feed it raw binary WS messages one at a time via `feed()`. It waits for a VPS to
    start a picture, then gathers the parameter sets + IDR slice(s) that follow. `done`
    becomes True as soon as the picture is complete -- the caller should stop reading from
    the socket at that point."""

    def __init__(self) -> None:
        self.nals: list[bytes] = []
        self.in_keyframe = False
        self.done = False

    def feed(self, ws_binary_message: bytes) -> None:
        if self.done:
            return
        parsed = _parse_nal(ws_binary_message)
        if parsed is None:
            return
        nal_type, nal = parsed

        if not self.in_keyframe:
            if nal_type == NAL_VPS:
                self.in_keyframe = True
                self.nals.append(nal)
            return

        if nal_type in PARAM_SET_TYPES or nal_type in KEYFRAME_SLICE_TYPES:
            self.nals.append(nal)
        else:
            # First NAL that isn't part of the keyframe picture -> it's complete.
            self.done = True


def build_annexb(nals: list[bytes]) -> bytes:
    return b"".join(START_CODE + nal for nal in nals)


def decode_first_frame_to_png(annexb_bytes: bytes) -> bytes:
    """Decode the first frame of an Annex-B HEVC elementary stream to PNG bytes via ffmpeg.

    Blocking (spawns a subprocess) -- always call this through
    hass.async_add_executor_job, never directly from the event loop.
    """
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "hevc", "-i", "pipe:0",
            "-frames:v", "1", "-update", "1",
            "-f", "image2", "-c:v", "png", "pipe:1",
        ],
        input=annexb_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed to decode the extracted NAL units: "
            f"{proc.stderr.decode(errors='replace')}"
        )
    return proc.stdout
