"""Constants for the iHanoi Live Snapshot integration."""

DOMAIN = "ihanoi_live_snapshot"

CONF_CAMERAS = "cameras"

# Bundled, pre-shipped camera lookup table (camera_id -> name/address/lat-lng/wss_url).
# Refreshed in place by the "Update Camera List" button; see device.py.
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
