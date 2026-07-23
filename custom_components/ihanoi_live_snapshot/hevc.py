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

import logging
import subprocess
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

START_CODE = b"\x00\x00\x00\x01"
PREFIX_LEN = 12

# Bundled so the timestamp overlay doesn't depend on the host having any fonts/fontconfig
# installed at all -- `fontfile=` only needs libfreetype, unlike a bare family name (e.g.
# "sans"), which needs libfontconfig *and* at least one font it can resolve to. Many HA
# Docker/HAOS containers are Alpine-based and ship neither by default, which is what made
# the timestamp label silently disappear (drawtext failed -> the no-overlay retry below
# kicked in every time). DejaVu Sans is public-domain/Bitstream-Vera-licensed and freely
# redistributable -- see fonts/LICENSE.
_FONT_PATH = Path(__file__).parent / "fonts" / "DejaVuSans.ttf"

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


def _escape_drawtext(text: str) -> str:
    """Escape the characters ffmpeg's drawtext filter treats specially, so a timestamp
    like ``2026-07-22 15:30:45`` survives the filtergraph parser intact (the colons in
    particular would otherwise be read as option separators)."""
    return (
        text.replace("\\", r"\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace("%", r"\%")
    )


def _run_ffmpeg(args: list[str], annexb_bytes: bytes) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, input=annexb_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )


def decode_first_frame_to_png(annexb_bytes: bytes, label: str | None = None) -> bytes:
    """Decode the first frame of an Annex-B HEVC elementary stream to PNG bytes via ffmpeg.

    If ``label`` is given (e.g. the capture timestamp), it's burned into the bottom-right
    corner of the image via ffmpeg's ``drawtext`` filter, pointed at the bundled
    ``fonts/DejaVuSans.ttf`` via ``fontfile=`` so it only needs libfreetype -- not
    libfontconfig or any host-installed font. If ffmpeg still can't use it for some reason,
    we don't want to lose the snapshot over it, so we retry once without the overlay and
    just log a warning.

    Blocking (spawns a subprocess) -- always call this through
    hass.async_add_executor_job, never directly from the event loop.
    """
    head = ["ffmpeg", "-y", "-v", "error", "-f", "hevc", "-i", "pipe:0",
            "-frames:v", "1", "-update", "1"]
    tail = ["-f", "image2", "-c:v", "png", "pipe:1"]

    args = list(head)
    if label:
        args += [
            "-vf",
            f"drawtext=fontfile='{_escape_drawtext(str(_FONT_PATH))}'"
            f":text='{_escape_drawtext(label)}'"
            ":fontcolor=white:fontsize=20:box=1:boxcolor=black@0.5"
            ":boxborderw=6:x=w-tw-10:y=h-th-10",
        ]
    args += tail

    proc = _run_ffmpeg(args, annexb_bytes)
    if proc.returncode != 0 and label:
        _LOGGER.warning(
            "ffmpeg drawtext overlay failed (%s); decoding without the timestamp label.",
            proc.stderr.decode(errors="replace").strip(),
        )
        proc = _run_ffmpeg(head + tail, annexb_bytes)

    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed to decode the extracted NAL units: "
            f"{proc.stderr.decode(errors='replace')}"
        )
    return proc.stdout
