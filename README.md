# Bluesound Custom — Home Assistant Integration

A HACS-installable Home Assistant integration for **Bluesound / BluOS** devices
(NAD, Bluesound, DALI, Roksan, …) with **rich media browsing**:

- 📚 Local **Library** — artists, albums, tracks, folders, genres
- 📻 **Radio** — TuneIn, iHeartRadio, Calm Radio, …
- ⭐ **Favourite Radios** — the numbered presets stored on the device
- 🎧 **Streaming Services** — Spotify, Tidal, Qobuz, Deezer, Amazon Music, …
- 🎶 **Playlists** — saved playlists (local + service)

…plus the usual transport (play / pause / stop / next / previous / seek),
volume, mute, shuffle, repeat, source selection, and **Zeroconf auto-discovery**.

> This integration uses the domain `bluesound_custom` so it **coexists** with
> the official `bluesound` integration on the same Home Assistant instance.

---

## Table of Contents

1. [Why another Bluesound integration?](#why-another-bluesound-integration)
2. [Features](#features)
3. [Requirements](#requirements)
4. [Installation](#installation)
   - [Option A — HACS (custom repository)](#option-a--hacs-custom-repository)
   - [Option B — manual install](#option-b--manual-install)
5. [Configuration](#configuration)
   - [Automatic discovery (Zeroconf)](#automatic-discovery-zeroconf)
   - [Manual setup](#manual-setup)
6. [Using the media browser](#using-the-media-browser)
7. [Services](#services)
8. [Architecture](#architecture)
9. [Development](#development)
10. [Troubleshooting](#troubleshooting)
11. [Credits](#credits)
12. [License](#license)

---

## Why another Bluesound integration?

The [official Home Assistant Bluesound integration](https://www.home-assistant.io/integrations/bluesound/)
is solid for **playback control**, but its `async_browse_media` is a thin
wrapper around Home Assistant's `media_source` — it doesn't expose what
BluOS itself can browse: your local NAS library, the TuneIn/iHeartRadio tree,
your saved presets, or your linked streaming services.

The community alternative
[`aunefyren/bluesound_alt`](https://github.com/aunefyren/bluesound_alt)
nails group-volume handling but doesn't expose any browse tree at all.

`bluesound_custom` fills that gap. It uses BluOS's own `/Browse`,
`/RadioBrowse`, `/Presets`, `/Services`, and `/Playlists` endpoints and
turns each one into a directory in Home Assistant's media browser. Pick
anything in the tree → press play.

## Features

| Capability                       | Supported |
| -------------------------------- | :-------: |
| Play / Pause / Stop              | ✅         |
| Next / Previous track            | ✅         |
| Seek                             | ✅         |
| Volume set / step / mute         | ✅         |
| Shuffle / Repeat                 | ✅         |
| Source selection (services)      | ✅         |
| **Browse local library**         | ✅         |
| **Browse internet radio**        | ✅         |
| **Browse favourite presets**     | ✅         |
| **Browse streaming services**    | ✅         |
| **Browse saved playlists**       | ✅         |
| Zeroconf auto-discovery          | ✅         |
| Long-poll status (ETag)          | ✅         |
| `play_preset` service            | ✅         |
| Multi-room grouping              | 🚧 planned |
| Per-speaker volume in groups     | 🚧 planned |

## Requirements

- Home Assistant **2024.8** or newer.
- A Bluesound / BluOS device reachable on your network (port **11000**).
- (Optional) [HACS](https://hacs.xyz/) for one-click installation.

## Installation

### Option A — HACS (custom repository)

1. In Home Assistant, open **HACS → Integrations**.
2. Click the **︙** menu (top-right) → **Custom repositories**.
3. Paste the GitHub URL of this repository, e.g.:
   ```
   https://github.com/dedero1985/ha-bluesound-custom
   ```
   Category: **Integration**. Click **Add**.
4. Find **Bluesound Custom (Library, Radios & Streaming)** in the HACS store
   and click **Download**.
5. **Restart Home Assistant.**
6. Go to **Settings → Devices & Services → Add Integration** and search for
   *"Bluesound Custom"*. Continue with [Configuration](#configuration).

### Option B — manual install

1. Download/clone this repository.
2. Copy the `custom_components/bluesound_custom/` folder into your Home
   Assistant config directory so it lives at:
   ```
   <ha-config>/custom_components/bluesound_custom/
   ```
3. **Restart Home Assistant.**
4. **Settings → Devices & Services → Add Integration → "Bluesound Custom"**.

## Configuration

### Automatic discovery (Zeroconf)

BluOS players advertise themselves on the `_musc._tcp.local.` mDNS service
type. If your Home Assistant host can see mDNS on the same network as the
player, you'll get a notification at **Settings → Devices & Services**
saying *"Bluesound device discovered"*. Click **Configure** and confirm.

### Manual setup

If discovery doesn't fire (segmented network, mDNS blocked, etc.):

1. **Settings → Devices & Services → Add Integration → "Bluesound Custom"**
2. Enter:
   - **Host** — IP or hostname of the player, e.g. `192.168.1.42`
   - **Port** — leave at the default `11000` unless you've changed it
3. Click **Submit**. The integration probes `/SyncStatus`, extracts the
   MAC address as a stable unique-id, and creates a `media_player` entity.

Each player creates its own config entry and one `media_player` entity.
Add the integration once per device.

## Using the media browser

Open any media card or call `media_player.play_media` against the entity.
Pressing the **browse** button gives you this tree:

```
🔊 <Player name>
├── 📚 Library
│   ├── Artists
│   ├── Albums
│   ├── Folders
│   └── Genres …
├── 📻 Radio
│   ├── TuneIn
│   │   ├── Local Radio …
│   │   └── Genres …
│   └── iHeartRadio …
├── ⭐ Favourite Radios (Presets)
│   ├── #1 BBC Radio 6
│   ├── #2 FIP …
│   └── …
├── 🎧 Streaming Services
│   ├── Spotify
│   ├── Tidal
│   └── Qobuz …
└── 🎶 Playlists
```

Tap anything with a **▶ play** affordance to start playback.

### From an automation

```yaml
service: media_player.play_media
target:
  entity_id: media_player.living_room_bluesound
data:
  media_content_type: bluos          # any non-empty string works
  media_content_id: "preset|3"        # ⇒ /Preset?id=3
```

`media_content_id` values you can pass directly without browsing first:

| ID                              | Effect                                  |
| ------------------------------- | --------------------------------------- |
| `preset\|<id>`                  | Play preset N (`/Preset?id=<id>`)       |
| `play_url\|<url-encoded URL>`   | Play a BluOS `playURL` (`/Play?url=…`)  |

Browse tree nodes share the same `<kind>\|<urlquoted-arg>` scheme — drill in
once via the UI and inspect the resulting `media_content_id` to script it.

## Services

### `bluesound_custom.play_preset`

Play one of the device's stored presets.

```yaml
service: bluesound_custom.play_preset
target:
  entity_id: media_player.kitchen_bluesound
data:
  preset_id: 5
```

| Field      | Type      | Required | Description                            |
| ---------- | --------- | -------- | -------------------------------------- |
| `preset_id`| int 1-99  | yes      | Preset slot as configured on the device|

The standard Home Assistant `media_player.*` services (`play_media`,
`select_source`, `volume_set`, `media_seek`, …) all work too.

## Now playing attributes

In addition to the standard `media_title` / `media_artist` / `media_album_name`
/ `media_image_url` properties (which the default HA media-control card
already renders), the entity exposes these `extra_state_attributes`. They are
only present when the device actually reports the field for the current
stream — Spotify Connect doesn't expose the same fields as a FLAC from your
NAS, etc.

| Attribute            | Type    | Example                              | BluOS source   |
| -------------------- | ------- | ------------------------------------ | -------------- |
| `audio_quality`      | string  | `cd`, `hd`, `mq`, `mp3`, `aac`       | `quality`      |
| `audio_format`       | string  | `FLAC 44.1 kHz, 16-bit`, `320 kbps MP3` | `streamFormat` |
| `bitrate_kbps`       | int     | `1411`                               | `bitrate`      |
| `volume_db`          | float   | `-60.1`                              | `db` (current playback level in dB, not ReplayGain) |
| `streaming_service`  | string  | `Spotify`, `Tidal`, `TuneIn`         | `service`      |
| `service_icon`       | URL     | `https://.../spotify.png`            | `serviceIcon`  |
| `stream_url`         | URL     | `http://stream.example.com/...`      | `streamUrl`    |
| `group_name`         | string  | `Living room + Kitchen`              | `groupName`    |

The entity also returns `media_position_updated_at` so the default card's
progress bar advances smoothly between long-poll updates instead of looking
frozen.

### Surfacing the extras in your dashboard

The **default `media-control` card** only renders title / artist / album /
image — that's a Home Assistant choice, not something the integration can
override. For the rest, use any of:

**`mini-media-player`** (HACS) — pass attribute names via `attribute`:

```yaml
type: custom:mini-media-player
entity: media_player.living_room_bluesound
info: scroll
artwork: cover
attribute:
  - audio_quality
  - audio_format
  - bitrate_kbps
```

**`mushroom-media-player-card`** — templated secondary line:

```yaml
type: custom:mushroom-media-player-card
entity: media_player.living_room_bluesound
secondary_info: |
  {{ state_attr('media_player.living_room_bluesound', 'audio_format') }}
  ({{ state_attr('media_player.living_room_bluesound', 'bitrate_kbps') }} kbps)
```

**Plain `entities` card** — show attributes inline:

```yaml
type: entities
entities:
  - entity: media_player.living_room_bluesound
    type: custom:multiple-entity-row
    show_state: false
    entities:
      - attribute: audio_format
        name: Format
      - attribute: bitrate_kbps
        name: kbps
      - attribute: streaming_service
        name: Source
```

**Template sensor** — promote a single attribute to a first-class entity so
you can graph / alert / show it anywhere:

```yaml
template:
  - sensor:
      - name: Bluesound now-playing format
        state: "{{ state_attr('media_player.living_room_bluesound', 'audio_format') }}"
      - name: Bluesound now-playing bitrate
        state: "{{ state_attr('media_player.living_room_bluesound', 'bitrate_kbps') }}"
        unit_of_measurement: kbps
        device_class: data_rate
```

## Architecture

```text
┌───────────────────────────────────────────────────────────────────────────┐
│                       Home Assistant entity layer                         │
│                                                                           │
│   media_player.py   ── BluesoundCustomPlayer (MediaPlayerEntity)          │
│        │              ─ properties from coordinator.data.status           │
│        │              ─ async_browse_media → media_browser.async_browse   │
│        │              ─ async_play_media   → media_browser.async_play     │
│        ▼                                                                  │
│   media_browser.py  ── tree builder                                       │
│        │              ─ encode_id / decode_id  ("kind|arg" codec)         │
│        ▼                                                                  │
│   coordinator.py    ── BluesoundCustomCoordinator                         │
│        │              ─ long-poll /Status?timeout=100&etag=…              │
│        │              ─ slow refresh of /Presets and /Services            │
│        │              ─ /SyncStatus on syncStat change                    │
│        ▼                                                                  │
│   api.py            ── BluOSClient (aiohttp + xmltodict)                  │
│        │              ─ /Status, /Volume, /Play, /Pause, /Stop, …          │
│        │              ─ /Browse, /RadioBrowse, /Presets, /Services        │
│        │              ─ /Playlists, /AddSlave, /RemoveSlave               │
│        ▼                                                                  │
└─────────────────── HTTP :11000 (XML) ──────────────────────────────────────┘
                                  │
                              BluOS device
```

Reference: [BluOS Custom Integration API v1.7](https://bluos.io/wp-content/uploads/2025/06/BluOS-Custom-Integration-API_v1.7.pdf).

## Development

```text
ha-bluesound-custom/
├── README.md
├── hacs.json
├── info.md
├── LICENSE
└── custom_components/
    └── bluesound_custom/
        ├── __init__.py          # async_setup_entry, runtime_data
        ├── api.py               # BluOS HTTP client + XML parsers
        ├── config_flow.py       # user + zeroconf setup
        ├── const.py             # DOMAIN, content_id kinds, intervals
        ├── coordinator.py       # long-polling DataUpdateCoordinator
        ├── manifest.json
        ├── media_browser.py     # async_browse / async_play tree
        ├── media_player.py      # MediaPlayerEntity
        ├── services.yaml        # play_preset
        ├── strings.json         # config flow + service strings
        └── translations/
            └── en.json
```

### Forking & republishing

If you fork this repo to publish under your own GitHub user, rewrite the
upstream owner (`dedero1985`) so HACS validation, the documentation link
and the issue tracker point at your fork:

```bash
sed -i '' 's/dedero1985/<YOUR_GH_USER>/g' \
  custom_components/bluesound_custom/manifest.json info.md README.md
```

The files touched are:

- `custom_components/bluesound_custom/manifest.json` (`codeowners`, `documentation`, `issue_tracker`)
- `info.md` (last-line link)
- this `README.md` (HACS install snippet)

### Local syntax check

```bash
python -m py_compile custom_components/bluesound_custom/*.py
```

For a deeper lint, install Home Assistant in a venv and run `hassfest` /
`pytest-homeassistant-custom-component`.

## Troubleshooting

| Symptom                                            | Fix                                                                                                                                                |
| -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Integration not discovered                         | Confirm UDP mDNS reaches your HA host. On VLANs you may need to enable mDNS reflection. Use the manual setup as a fallback.                        |
| `Cannot reach <host>:<port>` on setup              | Open `http://<host>:11000/Status` in a browser — you should see an XML document. If not, check firewall / VLAN.                                    |
| Browse tree is empty for *Streaming Services*      | The device may not have any streaming service linked yet. Add an account in the BluOS app first.                                                   |
| Preset plays but skips to silence                  | The preset URL has expired (some BluOS firmwares cache old TuneIn URLs). Re-save the preset from the BluOS app.                                    |
| Both `bluesound` and `bluesound_custom` are loaded | That's fine — they have different domains. Choose the entity from whichever one you prefer; remove the other integration to free the entity name. |

Enable debug logging:

```yaml
# configuration.yaml
logger:
  default: warning
  logs:
    custom_components.bluesound_custom: debug
```

## Credits

- BluOS / Bluesound for publishing the [Custom Integration API spec](https://bluos.io).
- The official [`homeassistant/components/bluesound`](https://github.com/home-assistant/core/tree/dev/homeassistant/components/bluesound) integration — the playback semantics here closely follow it.
- [`aunefyren/bluesound_alt`](https://github.com/aunefyren/bluesound_alt) — for the proven HACS layout and long-polling-with-ETag pattern.

## License

[MIT](./LICENSE)
