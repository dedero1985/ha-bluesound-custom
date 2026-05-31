"""Browse-media tree for the Bluesound Custom integration.

Top-level layout shown to the user in the Home Assistant media browser::

    Bluesound  (root)
    ├── Library             (BluOS /Browse)
    ├── Radio               (BluOS /RadioBrowse)
    │   ├── TuneIn
    │   └── iHeartRadio
    ├── Favourite Radios    (BluOS /Presets)
    ├── Streaming Services  (BluOS /Services + /Browse?key=<svc>)
    └── Playlists           (BluOS /Playlists)

``media_content_id`` is encoded as ``"<kind>|<urlquoted-arg>"`` so that any
text (browse keys, play URLs, service names) survives a round-trip through
HA's media browser.  Playback uses two terminal kinds:

* ``preset|<id>``      → ``/Preset?id=<id>``
* ``play_url|<url>``   → ``/Play?url=<url>``
"""
from __future__ import annotations

import logging
from urllib.parse import quote, unquote

from homeassistant.components.media_player import (
    BrowseError,
    BrowseMedia,
    MediaClass,
    MediaType,
)

from .api import BluOSError, BrowseItem
from .const import (
    CONTENT_TYPE_BLUOS,
    DEFAULT_RADIO_SERVICES,
    ID_FAVOURITES,
    ID_LIBRARY,
    ID_LIBRARY_NODE,
    ID_PLAY_ADD,
    ID_PLAY_URL,
    ID_PLAYLISTS,
    ID_PRESET,
    ID_RADIO,
    ID_RADIO_NODE,
    ID_RADIO_SERVICE,
    ID_ROOT,
    ID_SERVICE,
    ID_SERVICES,
)
from .coordinator import BluesoundCustomCoordinator

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# media_content_id codec
# ---------------------------------------------------------------------------


def encode_id(kind: str, arg: str = "") -> str:
    """Encode a node identity into a URL-safe media_content_id."""
    return f"{kind}|{quote(arg or '', safe='')}"


def decode_id(content_id: str) -> tuple[str, str]:
    """Decode a media_content_id into ``(kind, arg)``."""
    if "|" not in content_id:
        return content_id, ""
    kind, arg = content_id.split("|", 1)
    return kind, unquote(arg)


# ---------------------------------------------------------------------------
# Entry points (called from media_player.py)
# ---------------------------------------------------------------------------


async def async_browse(
    coordinator: BluesoundCustomCoordinator,
    media_content_type: str | None,
    media_content_id: str | None,
) -> BrowseMedia:
    """Resolve a media browser request to a BrowseMedia node."""
    if not media_content_id:
        return await _root(coordinator)

    kind, arg = decode_id(media_content_id)

    routes = {
        ID_ROOT: lambda: _root(coordinator),
        ID_LIBRARY: lambda: _library_root(coordinator),
        ID_LIBRARY_NODE: lambda: _library_node(coordinator, arg),
        ID_RADIO: lambda: _radio_root(coordinator),
        ID_RADIO_SERVICE: lambda: _radio_service(coordinator, arg),
        ID_RADIO_NODE: lambda: _radio_node(coordinator, arg),
        ID_FAVOURITES: lambda: _favourites(coordinator),
        ID_SERVICES: lambda: _services_root(coordinator),
        ID_SERVICE: lambda: _service(coordinator, arg),
        ID_PLAYLISTS: lambda: _playlists(coordinator),
    }
    handler = routes.get(kind)
    if handler is None:
        raise BrowseError(f"Unknown Bluesound browse node: {media_content_id}")
    return await handler()


async def async_play(
    coordinator: BluesoundCustomCoordinator,
    media_content_type: str,
    media_content_id: str,
) -> None:
    """Play a node selected from the browse tree.

    Terminal kinds:
      * ``preset|<id>``     -> ``/Preset?id=<id>``
      * ``play_url|<url>``  -> ``/Play?url=<url>``

    Folder kinds (``library_node`` / ``radio_node`` / ``radio_service`` /
    ``service``) get "play folder" semantics: first try BluOS's own
    ``/Play?url=<key>`` (works for service-style keys like
    ``spotify:playlist:...``), then fall back to drilling in and playing
    the first child that has a ``playURL``. This matches what the BluOS
    phone app does on a "Play All" gesture and stops play_media from
    erroring when the HA media-browser UI invokes it on a folder.
    """
    kind, arg = decode_id(media_content_id)
    if kind == ID_PRESET:
        try:
            await coordinator.client.load_preset(int(arg))
        except (ValueError, BluOSError) as err:
            raise BrowseError(f"Failed to play preset {arg}: {err}") from err
        return
    if kind == ID_PLAY_URL:
        if not arg:
            raise BrowseError("Empty BluOS play URL")
        try:
            await coordinator.client.play(url=arg)
        except BluOSError as err:
            raise BrowseError(f"Failed to play URL: {err}") from err
        return
    if kind == ID_PLAY_ADD:
        if not arg:
            raise BrowseError("Empty BluOS add URL")
        try:
            await coordinator.client.add(arg, playnow=True)
        except BluOSError as err:
            raise BrowseError(f"Failed to queue and play: {err}") from err
        return
    if kind in (ID_LIBRARY_NODE, ID_SERVICE, ID_RADIO_NODE, ID_RADIO_SERVICE):
        await _play_folder(coordinator, kind, arg)
        return
    raise BrowseError(f"Cannot play Bluesound node: {media_content_id}")


async def _play_folder(
    coordinator: BluesoundCustomCoordinator,
    kind: str,
    arg: str,
) -> None:
    """Fallback 'play folder' for items that lack their own addURL/playURL.

    Reached when the user pressed play on a pure-container node (e.g. a
    top-level menu like ``LocalMusic:`` whose /Browse item carries only
    ``browseKey``). BluOS will NOT accept a browseKey as a play URL
    (confirmed against BluOS API v1.7) so we don't try /Play?url=<key>
    here -- it would always fail. Instead:

    1. Drill into the folder via the right /Browse endpoint for the kind.
    2. Play the first child that exposes a ``playURL`` (single track).
    3. Or the first child that exposes an ``addURL`` (sub-album/playlist
       queued via /Add?...&playnow=1).
    4. If neither exists at the top level, raise a clear BrowseError so
       the user knows to drill deeper.

    Items that have their own addURL are handled directly by ID_PLAY_ADD
    in async_play and never reach this function.
    """
    if not arg:
        raise BrowseError("Cannot play empty Bluesound node")

    try:
        items = await _list_folder(coordinator, kind, arg)
    except BluOSError as err:
        raise BrowseError(
            f"Cannot open Bluesound folder: {err}. "
            "Use the browse menu to drill in and pick a track."
        ) from err

    for item in items:
        if item.play_url:
            try:
                await coordinator.client.play(url=item.play_url)
                return
            except BluOSError:
                continue
        if item.add_url:
            try:
                await coordinator.client.add(item.add_url, playnow=True)
                return
            except BluOSError:
                continue

    raise BrowseError(
        "This folder has no directly playable items at the top level. "
        "Open it via the browse menu and pick a track, album, or playlist."
    )


async def _list_folder(
    coordinator: BluesoundCustomCoordinator,
    kind: str,
    arg: str,
) -> list[BrowseItem]:
    if kind == ID_RADIO_NODE:
        if "::" in arg:
            service, key = arg.split("::", 1)
        else:
            service, key = "", arg
        return await coordinator.client.radio_browse(
            service=service or None, key=key
        )
    if kind == ID_RADIO_SERVICE:
        return await coordinator.client.radio_browse(service=arg)
    if kind == ID_SERVICE:
        try:
            return await coordinator.client.browse(key=arg)
        except BluOSError:
            return await coordinator.client.playlists(service=arg)
    return await coordinator.client.browse(key=arg)


# ---------------------------------------------------------------------------
# Tree builders
# ---------------------------------------------------------------------------


async def _root(coordinator: BluesoundCustomCoordinator) -> BrowseMedia:
    children = [
        _directory("Library", encode_id(ID_LIBRARY), MediaClass.DIRECTORY),
        _directory("Radio", encode_id(ID_RADIO), MediaClass.DIRECTORY),
        _directory(
            "Favourite Radios (Presets)",
            encode_id(ID_FAVOURITES),
            MediaClass.CHANNEL,
        ),
        _directory(
            "Streaming Services", encode_id(ID_SERVICES), MediaClass.DIRECTORY
        ),
        _directory("Playlists", encode_id(ID_PLAYLISTS), MediaClass.PLAYLIST),
    ]
    return BrowseMedia(
        title=coordinator.sync_status.name or "Bluesound",
        media_class=MediaClass.DIRECTORY,
        media_content_type=CONTENT_TYPE_BLUOS,
        media_content_id=encode_id(ID_ROOT),
        can_play=False,
        can_expand=True,
        children=children,
        children_media_class=MediaClass.DIRECTORY,
    )


async def _library_root(coordinator: BluesoundCustomCoordinator) -> BrowseMedia:
    items = await _safe_browse(coordinator, key=None)
    return BrowseMedia(
        title="Library",
        media_class=MediaClass.DIRECTORY,
        media_content_type=CONTENT_TYPE_BLUOS,
        media_content_id=encode_id(ID_LIBRARY),
        can_play=False,
        can_expand=True,
        children=[_item_to_browse(item, ID_LIBRARY_NODE) for item in items],
        children_media_class=MediaClass.DIRECTORY,
    )


async def _library_node(
    coordinator: BluesoundCustomCoordinator, key: str
) -> BrowseMedia:
    items = await _safe_browse(coordinator, key=key)
    return BrowseMedia(
        title="Library",
        media_class=MediaClass.DIRECTORY,
        media_content_type=CONTENT_TYPE_BLUOS,
        media_content_id=encode_id(ID_LIBRARY_NODE, key),
        can_play=False,
        can_expand=True,
        children=[_item_to_browse(item, ID_LIBRARY_NODE) for item in items],
        children_media_class=MediaClass.MUSIC,
    )


async def _radio_root(coordinator: BluesoundCustomCoordinator) -> BrowseMedia:
    items: list[BrowseItem] = []
    try:
        items = await coordinator.client.radio_browse()
    except BluOSError as err:
        _LOGGER.debug("RadioBrowse root failed, falling back to defaults: %s", err)

    children: list[BrowseMedia] = []
    seen: set[str] = set()
    for item in items:
        name = item.text or item.text2 or ""
        if not name or name in seen:
            continue
        seen.add(name)
        children.append(
            BrowseMedia(
                title=name,
                media_class=MediaClass.DIRECTORY,
                media_content_type=CONTENT_TYPE_BLUOS,
                media_content_id=encode_id(ID_RADIO_SERVICE, name),
                can_play=False,
                can_expand=True,
                thumbnail=item.image,
                children_media_class=MediaClass.DIRECTORY,
            )
        )

    if not children:
        for name in DEFAULT_RADIO_SERVICES:
            children.append(
                BrowseMedia(
                    title=name,
                    media_class=MediaClass.DIRECTORY,
                    media_content_type=CONTENT_TYPE_BLUOS,
                    media_content_id=encode_id(ID_RADIO_SERVICE, name),
                    can_play=False,
                    can_expand=True,
                    children_media_class=MediaClass.DIRECTORY,
                )
            )

    return BrowseMedia(
        title="Radio",
        media_class=MediaClass.DIRECTORY,
        media_content_type=CONTENT_TYPE_BLUOS,
        media_content_id=encode_id(ID_RADIO),
        can_play=False,
        can_expand=True,
        children=children,
        children_media_class=MediaClass.DIRECTORY,
    )


async def _radio_service(
    coordinator: BluesoundCustomCoordinator, service_name: str
) -> BrowseMedia:
    try:
        items = await coordinator.client.radio_browse(service=service_name)
    except BluOSError as err:
        raise BrowseError(
            f"Failed to load radio service {service_name}: {err}"
        ) from err
    return BrowseMedia(
        title=service_name,
        media_class=MediaClass.DIRECTORY,
        media_content_type=CONTENT_TYPE_BLUOS,
        media_content_id=encode_id(ID_RADIO_SERVICE, service_name),
        can_play=False,
        can_expand=True,
        children=[
            _item_to_browse(item, ID_RADIO_NODE, service=service_name)
            for item in items
        ],
        children_media_class=MediaClass.CHANNEL,
    )


async def _radio_node(
    coordinator: BluesoundCustomCoordinator, packed: str
) -> BrowseMedia:
    """Drill-down inside a radio service. ``packed`` is ``"<service>::<key>"``."""
    if "::" in packed:
        service, key = packed.split("::", 1)
    else:
        service, key = "", packed
    try:
        items = await coordinator.client.radio_browse(
            service=service or None, key=key
        )
    except BluOSError as err:
        raise BrowseError(f"Failed to load radio node: {err}") from err
    return BrowseMedia(
        title=service or "Radio",
        media_class=MediaClass.DIRECTORY,
        media_content_type=CONTENT_TYPE_BLUOS,
        media_content_id=encode_id(ID_RADIO_NODE, packed),
        can_play=False,
        can_expand=True,
        children=[
            _item_to_browse(item, ID_RADIO_NODE, service=service) for item in items
        ],
        children_media_class=MediaClass.CHANNEL,
    )


async def _favourites(coordinator: BluesoundCustomCoordinator) -> BrowseMedia:
    presets = coordinator.data.presets if coordinator.data else []
    children: list[BrowseMedia] = []
    for preset in presets:
        title = f"#{preset.id} {preset.name}".strip()
        children.append(
            BrowseMedia(
                title=title,
                media_class=MediaClass.CHANNEL,
                media_content_type=MediaType.CHANNEL,
                media_content_id=encode_id(ID_PRESET, str(preset.id)),
                can_play=True,
                can_expand=False,
                thumbnail=preset.image,
            )
        )
    return BrowseMedia(
        title="Favourite Radios (Presets)",
        media_class=MediaClass.DIRECTORY,
        media_content_type=CONTENT_TYPE_BLUOS,
        media_content_id=encode_id(ID_FAVOURITES),
        can_play=False,
        can_expand=True,
        children=children,
        children_media_class=MediaClass.CHANNEL,
    )


async def _services_root(coordinator: BluesoundCustomCoordinator) -> BrowseMedia:
    services = coordinator.data.services if coordinator.data else []
    children: list[BrowseMedia] = []
    for svc in services:
        # Hide entries that aren't really "streaming services" in the user sense.
        if svc.type in ("LocalMusic",):
            continue
        children.append(
            BrowseMedia(
                title=svc.display_name or svc.name,
                media_class=MediaClass.DIRECTORY,
                media_content_type=CONTENT_TYPE_BLUOS,
                media_content_id=encode_id(ID_SERVICE, svc.name),
                can_play=False,
                can_expand=True,
                thumbnail=svc.image,
                children_media_class=MediaClass.DIRECTORY,
            )
        )
    return BrowseMedia(
        title="Streaming Services",
        media_class=MediaClass.DIRECTORY,
        media_content_type=CONTENT_TYPE_BLUOS,
        media_content_id=encode_id(ID_SERVICES),
        can_play=False,
        can_expand=True,
        children=children,
        children_media_class=MediaClass.DIRECTORY,
    )


async def _service(
    coordinator: BluesoundCustomCoordinator, service_name: str
) -> BrowseMedia:
    """Browse inside a streaming service.

    Most BluOS firmwares expose service browsing via ``/Browse?key=<service>``.
    Some return playlists only through ``/Playlists?service=<service>``. We
    try the more general endpoint first and fall back.
    """
    items: list[BrowseItem] = []
    try:
        items = await coordinator.client.browse(key=service_name)
    except BluOSError:
        try:
            items = await coordinator.client.playlists(service=service_name)
        except BluOSError as err:
            raise BrowseError(
                f"Failed to browse service {service_name}: {err}"
            ) from err
    return BrowseMedia(
        title=service_name,
        media_class=MediaClass.DIRECTORY,
        media_content_type=CONTENT_TYPE_BLUOS,
        media_content_id=encode_id(ID_SERVICE, service_name),
        can_play=False,
        can_expand=True,
        children=[_item_to_browse(item, ID_LIBRARY_NODE) for item in items],
        children_media_class=MediaClass.MUSIC,
    )


async def _playlists(coordinator: BluesoundCustomCoordinator) -> BrowseMedia:
    try:
        items = await coordinator.client.playlists()
    except BluOSError as err:
        raise BrowseError(f"Failed to load playlists: {err}") from err
    return BrowseMedia(
        title="Playlists",
        media_class=MediaClass.DIRECTORY,
        media_content_type=CONTENT_TYPE_BLUOS,
        media_content_id=encode_id(ID_PLAYLISTS),
        can_play=False,
        can_expand=True,
        children=[_item_to_browse(item, ID_LIBRARY_NODE) for item in items],
        children_media_class=MediaClass.PLAYLIST,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _directory(title: str, content_id: str, children_class: MediaClass) -> BrowseMedia:
    return BrowseMedia(
        title=title,
        media_class=MediaClass.DIRECTORY,
        media_content_type=CONTENT_TYPE_BLUOS,
        media_content_id=content_id,
        can_play=False,
        can_expand=True,
        children_media_class=children_class,
    )


async def _safe_browse(
    coordinator: BluesoundCustomCoordinator, key: str | None
) -> list[BrowseItem]:
    try:
        return await coordinator.client.browse(key=key)
    except BluOSError as err:
        raise BrowseError(f"BluOS browse failed: {err}") from err


def _item_to_browse(
    item: BrowseItem,
    expand_kind: str,
    service: str | None = None,
) -> BrowseMedia:
    """Convert a BluOS /Browse item into a BrowseMedia node.

    Each /Browse item carries at most three identifiers, prioritised in
    this order to produce a single ``media_content_id``:

    * ``playURL``   -> ``play_url|<url>``     (direct stream, /Play?url=)
    * ``addURL``    -> ``play_add|<addURL>``  (folder/album/playlist,
                                               /Add?...&playnow=1 -- this
                                               is what the BluOS phone app
                                               uses for "Play All")
    * ``browseKey`` -> ``library_node|<key>`` / ``radio_node|<svc>::<key>``
                      (expandable directory; not playable)
    """
    title = item.text or ""
    if item.text2:
        title = f"{title} — {item.text2}" if title else item.text2

    if item.play_url:
        return BrowseMedia(
            title=title or "(unnamed)",
            media_class=_guess_media_class(item),
            media_content_type=MediaType.MUSIC,
            media_content_id=encode_id(ID_PLAY_URL, item.play_url),
            can_play=True,
            can_expand=False,
            thumbnail=item.image,
        )

    if item.add_url:
        return BrowseMedia(
            title=title or "(unnamed)",
            media_class=_guess_media_class(item),
            media_content_type=MediaType.MUSIC,
            media_content_id=encode_id(ID_PLAY_ADD, item.add_url),
            can_play=True,
            can_expand=False,
            thumbnail=item.image,
        )

    if expand_kind == ID_RADIO_NODE:
        return BrowseMedia(
            title=title or "(unnamed)",
            media_class=MediaClass.DIRECTORY,
            media_content_type=CONTENT_TYPE_BLUOS,
            media_content_id=encode_id(
                ID_RADIO_NODE, f"{service or ''}::{item.key or ''}"
            ),
            can_play=False,
            can_expand=item.key is not None,
            thumbnail=item.image,
        )

    return BrowseMedia(
        title=title or "(unnamed)",
        media_class=MediaClass.DIRECTORY,
        media_content_type=CONTENT_TYPE_BLUOS,
        media_content_id=encode_id(expand_kind, item.key or ""),
        can_play=False,
        can_expand=item.key is not None,
        thumbnail=item.image,
    )


def _guess_media_class(item: BrowseItem) -> MediaClass:
    """Map BluOS item types onto the closest MediaClass."""
    type_map = {
        "song": MediaClass.TRACK,
        "audio": MediaClass.TRACK,
        "link": MediaClass.MUSIC,
        "station": MediaClass.CHANNEL,
        "album": MediaClass.ALBUM,
        "artist": MediaClass.ARTIST,
        "playlist": MediaClass.PLAYLIST,
        "genre": MediaClass.GENRE,
        "folder": MediaClass.DIRECTORY,
    }
    return type_map.get(item.type or "", MediaClass.MUSIC)
