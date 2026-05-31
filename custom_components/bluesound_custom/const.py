"""Constants for the Bluesound Custom integration."""
from __future__ import annotations

DOMAIN = "bluesound_custom"
DEFAULT_NAME = "Bluesound Player"
DEFAULT_PORT = 11000

# Long-poll & retry timings ----------------------------------------------------
# /Status?timeout=N blocks on the device until something changes or N seconds pass.
STATUS_LONG_POLL_TIMEOUT = 100
# How long we let the HTTP client wait on top of the device-side timeout.
HTTP_LONG_POLL_HTTP_TIMEOUT = STATUS_LONG_POLL_TIMEOUT + 15
# Default timeout for short (control / browse) calls.
HTTP_REQUEST_TIMEOUT = 15
# DataUpdateCoordinator fallback interval (only triggered if no long-poll cycle is
# in flight, i.e. on errors). Short so we recover from transient device reboots.
OFFLINE_RETRY_INTERVAL = 10

# Cadence for "slow" data: presets & services rarely change.
PRESETS_REFRESH_INTERVAL = 60       # seconds
SERVICES_REFRESH_INTERVAL = 3600    # seconds

# Config entry keys ------------------------------------------------------------
CONF_MAC = "mac"
CONF_MODEL = "model"

# Service names ----------------------------------------------------------------
SERVICE_PLAY_PRESET = "play_preset"
ATTR_PRESET_ID = "preset_id"

# Browse / play_media identifier prefixes --------------------------------------
# media_content_id format is "<kind>|<urlquoted-arg>"; see media_browser.py.
ID_ROOT = "root"
ID_LIBRARY = "library"
ID_LIBRARY_NODE = "library_node"
ID_RADIO = "radio"
ID_RADIO_SERVICE = "radio_service"
ID_RADIO_NODE = "radio_node"
ID_FAVOURITES = "favourites"
ID_SERVICES = "services"
ID_SERVICE = "service"
ID_PLAYLISTS = "playlists"
ID_PRESET = "preset"
ID_PLAY_URL = "play_url"

# media_content_type marker for our internal nodes (HA passes this back on drill-down).
CONTENT_TYPE_BLUOS = "bluos"

# Defaults shown when /RadioBrowse returns no top-level services on older firmwares.
DEFAULT_RADIO_SERVICES: tuple[str, ...] = ("TuneIn", "iHeartRadio", "Calm Radio")
