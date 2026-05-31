"""BluOS HTTP API client.

Talks to a Bluesound / BluOS device over its HTTP control API on port 11000.
Responses are XML; we parse them with xmltodict and return dataclasses.

Reference:
  https://bluos.io/wp-content/uploads/2025/06/BluOS-Custom-Integration-API_v1.7.pdf

Only the endpoints required by the Home Assistant integration are exposed:
status, transport, volume, browse (local + radio), presets, services, playlists,
and basic grouping. Everything is async.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import aiohttp
import xmltodict

_LOGGER = logging.getLogger(__name__)


class BluOSError(Exception):
    """Base error for BluOS API failures."""


class BluOSConnectionError(BluOSError):
    """Raised when the device is unreachable / network error."""


class BluOSResponseError(BluOSError):
    """Raised when the device returns an unexpected response."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Status:
    """Snapshot returned by ``/Status``."""

    state: str = "stop"
    title1: str | None = None
    title2: str | None = None
    title3: str | None = None
    artist: str | None = None
    album: str | None = None
    name: str | None = None
    image: str | None = None
    service: str | None = None
    service_icon: str | None = None
    stream_url: str | None = None
    stream_format: str | None = None
    quality: str | None = None
    bitrate_kbps: int | None = None
    volume_db: float | None = None
    volume: int = 0
    mute: bool = False
    shuffle: bool = False
    repeat: int = 0  # 0 = off, 1 = one, 2 = all
    seek_secs: float | None = None
    total_secs: float | None = None
    can_seek: bool = False
    etag: str | None = None
    sync_stat: str | None = None
    group_name: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SyncStatus:
    """Device identity returned by ``/SyncStatus``."""

    name: str = ""
    model: str | None = None
    model_name: str | None = None
    brand: str | None = None
    mac: str = ""
    ip: str | None = None
    port: int = 11000
    icon: str | None = None
    master_ip: str | None = None
    slaves: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Preset:
    """A single ``/Presets`` entry."""

    id: int
    name: str
    url: str | None = None
    image: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Service:
    """A single ``/Services`` entry."""

    name: str
    display_name: str
    type: str
    image: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class BrowseItem:
    """A single ``/Browse`` or ``/RadioBrowse`` item."""

    key: str | None
    text: str
    text2: str | None = None
    type: str | None = None
    image: str | None = None
    play_url: str | None = None
    play_url_type: str | None = None
    is_playable: bool = False
    is_container: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class BluOSClient:
    """Async HTTP client for a single BluOS device."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int = 11000,
        timeout: int = 15,
    ) -> None:
        self._session = session
        self.host = host
        self.port = port
        self._default_timeout = aiohttp.ClientTimeout(total=timeout)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        client_timeout = (
            aiohttp.ClientTimeout(total=timeout) if timeout else self._default_timeout
        )
        # Filter Nones from params to avoid sending bare "?key=".
        clean_params = (
            {k: v for k, v in params.items() if v is not None} if params else None
        )
        try:
            async with self._session.get(
                url, params=clean_params, timeout=client_timeout
            ) as resp:
                resp.raise_for_status()
                text = await resp.text()
        except aiohttp.ClientError as err:
            raise BluOSConnectionError(f"{url}: {err}") from err
        except asyncio.TimeoutError as err:
            raise BluOSConnectionError(f"{url}: timeout") from err

        if not text.strip():
            return {}
        try:
            parsed = xmltodict.parse(text) or {}
        except Exception as err:  # noqa: BLE001 - xmltodict raises arbitrary errors
            raise BluOSResponseError(f"{url}: malformed XML: {err}") from err
        return parsed

    # ---- status ---------------------------------------------------------

    async def status(
        self, etag: str | None = None, timeout: int | None = None
    ) -> Status:
        """``/Status`` with optional long-poll (etag + timeout)."""
        params: dict[str, Any] = {}
        if etag:
            params["etag"] = etag
        http_timeout: int | None = None
        if timeout:
            params["timeout"] = str(timeout)
            http_timeout = timeout + 15
        raw = await self._get("/Status", params or None, timeout=http_timeout)
        return _parse_status(raw)

    async def sync_status(self) -> SyncStatus:
        raw = await self._get("/SyncStatus")
        return _parse_sync_status(raw)

    # ---- transport ------------------------------------------------------

    async def play(self, url: str | None = None, seek: int | None = None) -> None:
        params: dict[str, Any] = {}
        if url is not None:
            params["url"] = url
        if seek is not None:
            params["seek"] = str(seek)
        await self._get("/Play", params or None)

    async def pause(self, toggle: bool = False) -> None:
        await self._get("/Pause", {"toggle": "1"} if toggle else None)

    async def stop(self) -> None:
        await self._get("/Stop")

    async def skip(self) -> None:
        await self._get("/Skip")

    async def back(self) -> None:
        await self._get("/Back")

    async def seek(self, seconds: int) -> None:
        await self._get("/Play", {"seek": str(int(seconds))})

    async def set_volume(self, level: int) -> None:
        clamped = max(0, min(100, int(level)))
        await self._get("/Volume", {"level": str(clamped)})

    async def set_mute(self, mute: bool) -> None:
        await self._get("/Volume", {"mute": "1" if mute else "0"})

    async def set_shuffle(self, on: bool) -> None:
        await self._get("/Shuffle", {"state": "1" if on else "0"})

    async def set_repeat(self, mode: int) -> None:
        await self._get("/Repeat", {"state": str(int(mode))})

    # ---- browse / discovery --------------------------------------------

    async def browse(self, key: str | None = None) -> list[BrowseItem]:
        raw = await self._get("/Browse", {"key": key} if key else None)
        return _parse_browse(raw)

    async def radio_browse(
        self, service: str | None = None, key: str | None = None
    ) -> list[BrowseItem]:
        params: dict[str, Any] = {}
        if service:
            params["service"] = service
        if key:
            params["key"] = key
        raw = await self._get("/RadioBrowse", params or None)
        return _parse_radio_browse(raw)

    async def presets(self) -> list[Preset]:
        return _parse_presets(await self._get("/Presets"))

    async def load_preset(self, preset_id: int) -> None:
        await self._get("/Preset", {"id": str(int(preset_id))})

    async def services(self) -> list[Service]:
        return _parse_services(await self._get("/Services"))

    async def playlists(
        self, service: str | None = None, category: str | None = None
    ) -> list[BrowseItem]:
        params: dict[str, Any] = {}
        if service:
            params["service"] = service
        if category:
            params["category"] = category
        return _parse_browse(await self._get("/Playlists", params or None))

    # ---- grouping -------------------------------------------------------

    async def add_slave(self, slave_ip: str, slave_port: int = 11000) -> None:
        await self._get(
            "/AddSlave", {"slave": slave_ip, "port": str(slave_port)}
        )

    async def remove_slave(self, slave_ip: str, slave_port: int = 11000) -> None:
        await self._get(
            "/RemoveSlave", {"slave": slave_ip, "port": str(slave_port)}
        )


# ---------------------------------------------------------------------------
# Parsers (XML-to-dataclass)
# ---------------------------------------------------------------------------


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).lower() in ("1", "true", "on", "yes")


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _first_attr(node: dict[str, Any], *keys: str) -> Any:
    """Return the first non-None attribute from a node tolerating @-prefixes."""
    for key in keys:
        for cand in (key, f"@{key}"):
            value = node.get(cand)
            if value is not None:
                return value
    return None


def _parse_status(raw: dict[str, Any]) -> Status:
    status = raw.get("status") or {}
    if not isinstance(status, dict):
        status = {}
    return Status(
        state=str(status.get("state") or "stop"),
        title1=_text(status.get("title1")),
        title2=_text(status.get("title2")),
        title3=_text(status.get("title3")),
        artist=_text(status.get("artist")) or _text(status.get("title2")),
        album=_text(status.get("album")) or _text(status.get("title3")),
        name=_text(status.get("name")),
        image=_text(status.get("image")),
        service=_text(status.get("service")),
        service_icon=_text(status.get("serviceIcon")),
        stream_url=_text(status.get("streamUrl") or status.get("stream_url")),
        stream_format=_text(status.get("streamFormat")),
        quality=_text(status.get("quality")),
        bitrate_kbps=_int(status.get("bitrate"), 0) or None,
        volume_db=_float(status.get("db")),
        volume=_int(status.get("volume"), 0),
        mute=_bool(status.get("mute")),
        shuffle=_bool(status.get("shuffle")),
        repeat=_int(status.get("repeat"), 0),
        seek_secs=_float(status.get("secs")),
        total_secs=_float(status.get("totlen")),
        can_seek=_bool(status.get("canSeek")),
        etag=_text(status.get("@etag") or status.get("etag")),
        sync_stat=_text(status.get("syncStat") or status.get("@syncStat")),
        group_name=_text(status.get("groupName")),
        raw=status,
    )


def _parse_sync_status(raw: dict[str, Any]) -> SyncStatus:
    sync = raw.get("SyncStatus") or raw.get("syncStatus") or {}
    if not isinstance(sync, dict):
        sync = {}
    slaves_node = sync.get("slave") or sync.get("Slave")
    slaves = [
        {
            "ip": _first_attr(s, "id"),
            "port": _int(_first_attr(s, "port"), 11000),
        }
        for s in _ensure_list(slaves_node)
        if isinstance(s, dict)
    ]
    return SyncStatus(
        name=str(_first_attr(sync, "name") or ""),
        model=_first_attr(sync, "model"),
        model_name=_first_attr(sync, "modelName"),
        brand=_first_attr(sync, "brand"),
        mac=str(_first_attr(sync, "mac") or ""),
        ip=_first_attr(sync, "ip"),
        port=_int(_first_attr(sync, "port"), 11000),
        icon=_first_attr(sync, "icon"),
        master_ip=_first_attr(sync, "master"),
        slaves=slaves,
        raw=sync,
    )


def _parse_presets(raw: dict[str, Any]) -> list[Preset]:
    container = raw.get("presets") or {}
    if not isinstance(container, dict):
        return []
    items = _ensure_list(container.get("preset"))
    out: list[Preset] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out.append(
            Preset(
                id=_int(_first_attr(item, "id"), 0),
                name=str(_first_attr(item, "name") or ""),
                url=_first_attr(item, "url"),
                image=_first_attr(item, "image"),
                raw=item,
            )
        )
    return out


def _parse_services(raw: dict[str, Any]) -> list[Service]:
    container = raw.get("services") or {}
    if not isinstance(container, dict):
        return []
    items = _ensure_list(container.get("service"))
    out: list[Service] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(_first_attr(item, "name") or "")
        out.append(
            Service(
                name=name,
                display_name=str(_first_attr(item, "displayname") or name),
                type=str(_first_attr(item, "type") or ""),
                image=_first_attr(item, "image"),
                raw=item,
            )
        )
    return out


def _parse_browse(raw: dict[str, Any]) -> list[BrowseItem]:
    container = raw.get("browse") or raw.get("Browse") or {}
    if not isinstance(container, dict):
        return []
    items_node = container.get("item") or container.get("Item")
    out: list[BrowseItem] = []
    for item in _ensure_list(items_node):
        if not isinstance(item, dict):
            continue
        item_type = _first_attr(item, "type")
        play_url = _first_attr(item, "playURL")
        key = _first_attr(item, "browseKey", "key")
        is_container = key is not None or item_type in ("menu", "list", "folder")
        is_playable = play_url is not None or item_type in (
            "song",
            "station",
            "link",
            "audio",
        )
        out.append(
            BrowseItem(
                key=key,
                text=str(_first_attr(item, "text") or ""),
                text2=_first_attr(item, "text2"),
                type=item_type,
                image=_first_attr(item, "image"),
                play_url=play_url,
                play_url_type=_first_attr(item, "playURLType"),
                is_playable=bool(is_playable),
                is_container=bool(is_container) and not is_playable,
                raw=item,
            )
        )
    return out


def _parse_radio_browse(raw: dict[str, Any]) -> list[BrowseItem]:
    inner = raw.get("radiotime") or raw.get("RadioBrowse") or raw.get("browse") or {}
    return _parse_browse({"browse": inner})


def _text(value: Any) -> str | None:
    """xmltodict returns either a str or a dict ``{'#text': '...', '@x': '...'}``."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get("#text")
    return str(value)
