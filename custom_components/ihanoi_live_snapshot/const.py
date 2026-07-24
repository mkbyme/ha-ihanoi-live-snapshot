"""Constants for the iHanoi Live Snapshot integration."""

DOMAIN = "ihanoi_live_snapshot"

CONF_CAMERAS = "cameras"

# Per-camera JPEG compression quality, keyed by camera_id (dict of camera_id -> int).
# Used both for the full-size snapshot and the preview thumbnail below, so there's one
# knob per camera instead of two -- see device.py's IhanoiSnapshotAccount.camera_quality
# and hevc.py's quality->ffmpeg qscale mapping.
CONF_CAMERA_QUALITY = "camera_quality"
DEFAULT_JPEG_QUALITY = 85
MIN_JPEG_QUALITY = 30
MAX_JPEG_QUALITY = 100

# Small thumbnail rendered alongside the full-size snapshot (image_preview entity in
# image.py), meant for dashboards/notifications where the full-resolution image is
# unnecessary bandwidth.
PREVIEW_IMAGE_WIDTH = 640
PREVIEW_IMAGE_HEIGHT = 360

# How often (minutes) to auto re-fetch the camera list/wss_url table in the background,
# on top of the manual "Update Camera List" button -- the wss_url session tokens embedded
# in it expire, and a stale entry is what makes button.press/image capture start failing
# with "Never saw a VPS NAL" or a bare connection timeout. 0 disables the background
# refresh (manual button only, the original behavior).
CONF_UPDATE_INTERVAL = "update_interval_minutes"
DEFAULT_UPDATE_INTERVAL_MINUTES = 60
UPDATE_INTERVAL_OPTIONS = [0, 15, 30, 60, 120, 240]

# Bundled, pre-shipped camera lookup table (camera_id -> name/address/lat-lng/wss_url).
# Refreshed in place by the "Update Camera List" button or the periodic refresh above;
# see device.py.
CAMERA_LIST_FILENAME = "ihanoi_camera.json"

API_URL = (
    "https://cds.hanoi.gov.vn/api/1.0/public/video-wall-cameras-v2"
    "?refresh=false&page=1&per_page=1000&id=&address=&name=&userId=3594114"
)

# Sent as a text frame right after the WS handshake; the server won't push video
# until it sees this (see hevc.py / project CLAUDE.md for the reverse-engineering notes).
CLIENT_HELLO = "mobile:"
WS_USER_AGENT = "okhttp/4.12.0"
DEFAULT_CAPTURE_TIMEOUT = 10  # seconds

# Entity/device display names are the camera's name from ihanoi_camera.json, shortened
# to this length (see README.md's task brief).
MAX_NAME_LENGTH = 100

CONF_DEVICE_MANUFACTURER = "iHanoi (cds.hanoi.gov.vn)"
CONF_DEVICE_MODEL = "Live Camera"

SIGNAL_CAMERA_UPDATED = f"{DOMAIN}_camera_updated"
