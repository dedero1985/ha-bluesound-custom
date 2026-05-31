"""Media player entity for the Bluesound Custom integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    RepeatMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import media_browser
from .api import BluOSError
from .const import ATTR_PRESET_ID, DOMAIN, SERVICE_PLAY_PRESET
from .coordinator import BluesoundCustomCoordinator

_LOGGER = logging.getLogger(__name__)


STATE_MAP: dict[str, MediaPlayerState] = {
    "play": MediaPlayerState.PLAYING,
    "stream": MediaPlayerState.PLAYING,
    "pause": MediaPlayerState.PAUSED,
    "stop": MediaPlayerState.IDLE,
    "connecting": MediaPlayerState.BUFFERING,
    "grouped": MediaPlayerState.PLAYING,
}

SUPPORT = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.SHUFFLE_SET
    | MediaPlayerEntityFeature.REPEAT_SET
    | MediaPlayerEntityFeature.SEEK
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.PLAY_MEDIA
)

REPEAT_TO_BLUOS = {
    RepeatMode.OFF: 0,
    RepeatMode.ONE: 1,
    RepeatMode.ALL: 2,
}
BLUOS_TO_REPEAT = {v: k for k, v in REPEAT_TO_BLUOS.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the BluOS media_player entity for a config entry."""
    coordinator: BluesoundCustomCoordinator = entry.runtime_data
    async_add_entities([BluesoundCustomPlayer(coordinator)])

    # Per-entity service: media_player.bluesound_custom_play_preset
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_PLAY_PRESET,
        {vol.Required(ATTR_PRESET_ID): vol.All(int, vol.Range(min=1, max=99))},
        "async_play_preset",
    )


class BluesoundCustomPlayer(
    CoordinatorEntity[BluesoundCustomCoordinator], MediaPlayerEntity
):
    """One BluOS player exposed as a Home Assistant media_player."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = SUPPORT

    def __init__(self, coordinator: BluesoundCustomCoordinator) -> None:
        super().__init__(coordinator)
        sync = coordinator.sync_status
        self._attr_unique_id = (
            sync.mac or f"{coordinator.client.host}:{coordinator.client.port}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=sync.name or "Bluesound Player",
            manufacturer=sync.brand or "Bluesound",
            model=sync.model_name or sync.model,
            connections={("mac", sync.mac)} if sync.mac else set(),
            configuration_url=f"http://{coordinator.client.host}",
        )

    # ---- helpers --------------------------------------------------------

    @property
    def _status(self):
        return self.coordinator.data.status if self.coordinator.data else None

    # ---- state ---------------------------------------------------------

    @property
    def state(self) -> MediaPlayerState | None:
        status = self._status
        if not status:
            return None
        return STATE_MAP.get(status.state, MediaPlayerState.IDLE)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def media_title(self) -> str | None:
        s = self._status
        return s.title1 if s else None

    @property
    def media_artist(self) -> str | None:
        s = self._status
        if not s:
            return None
        return s.artist or s.title2

    @property
    def media_album_name(self) -> str | None:
        s = self._status
        if not s:
            return None
        return s.album or s.title3

    @property
    def media_image_url(self) -> str | None:
        s = self._status
        if not s or not s.image:
            return None
        if s.image.startswith(("http://", "https://")):
            return s.image
        path = s.image if s.image.startswith("/") else f"/{s.image}"
        return f"http://{self.coordinator.client.host}:{self.coordinator.client.port}{path}"

    @property
    def media_duration(self) -> int | None:
        s = self._status
        return int(s.total_secs) if s and s.total_secs else None

    @property
    def media_position(self) -> int | None:
        s = self._status
        return int(s.seek_secs) if s and s.seek_secs is not None else None

    @property
    def volume_level(self) -> float | None:
        s = self._status
        return (s.volume / 100.0) if s else None

    @property
    def is_volume_muted(self) -> bool | None:
        s = self._status
        return s.mute if s else None

    @property
    def shuffle(self) -> bool | None:
        s = self._status
        return s.shuffle if s else None

    @property
    def repeat(self) -> RepeatMode | None:
        s = self._status
        if not s:
            return None
        return BLUOS_TO_REPEAT.get(s.repeat, RepeatMode.OFF)

    @property
    def source(self) -> str | None:
        s = self._status
        return s.service if s else None

    @property
    def source_list(self) -> list[str]:
        if not self.coordinator.data:
            return []
        return [svc.display_name or svc.name for svc in self.coordinator.data.services]

    @property
    def media_position_updated_at(self):
        return self.coordinator.data.fetched_at if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._status
        if not s:
            return {}
        attrs: dict[str, Any] = {}
        if s.quality:
            attrs["audio_quality"] = s.quality
        if s.stream_format:
            attrs["audio_format"] = s.stream_format
        if s.bitrate_kbps:
            attrs["bitrate_kbps"] = s.bitrate_kbps
        if s.volume_db is not None:
            attrs["volume_db"] = s.volume_db
        if s.service:
            attrs["streaming_service"] = s.service
        if s.service_icon:
            attrs["service_icon"] = s.service_icon
        if s.stream_url:
            attrs["stream_url"] = s.stream_url
        if s.group_name:
            attrs["group_name"] = s.group_name
        return attrs

    # ---- transport -----------------------------------------------------

    async def async_media_play(self) -> None:
        await self._run(self.coordinator.client.play())

    async def async_media_pause(self) -> None:
        await self._run(self.coordinator.client.pause())

    async def async_media_stop(self) -> None:
        await self._run(self.coordinator.client.stop())

    async def async_media_next_track(self) -> None:
        await self._run(self.coordinator.client.skip())

    async def async_media_previous_track(self) -> None:
        await self._run(self.coordinator.client.back())

    async def async_media_seek(self, position: float) -> None:
        await self._run(self.coordinator.client.seek(int(position)))

    async def async_set_volume_level(self, volume: float) -> None:
        await self._run(self.coordinator.client.set_volume(int(volume * 100)))

    async def async_mute_volume(self, mute: bool) -> None:
        await self._run(self.coordinator.client.set_mute(mute))

    async def async_set_shuffle(self, shuffle: bool) -> None:
        await self._run(self.coordinator.client.set_shuffle(shuffle))

    async def async_set_repeat(self, repeat: RepeatMode) -> None:
        await self._run(self.coordinator.client.set_repeat(REPEAT_TO_BLUOS.get(repeat, 0)))

    async def async_select_source(self, source: str) -> None:
        services = self.coordinator.data.services if self.coordinator.data else []
        match = next(
            (
                svc
                for svc in services
                if svc.display_name == source or svc.name == source
            ),
            None,
        )
        if match is None:
            _LOGGER.warning("Unknown Bluesound source: %s", source)
            return
        # BluOS lets us "start" a service by feeding its internal name as a play URL.
        try:
            await self.coordinator.client.play(url=match.name)
        except BluOSError as err:
            _LOGGER.warning("Failed to select source %s: %s", source, err)
        finally:
            await self.coordinator.force_refresh()

    # ---- browse + play -------------------------------------------------

    async def async_browse_media(
        self,
        media_content_type: str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        return await media_browser.async_browse(
            self.coordinator, media_content_type, media_content_id
        )

    async def async_play_media(
        self, media_type: str, media_id: str, **kwargs: Any
    ) -> None:
        await media_browser.async_play(self.coordinator, media_type, media_id)
        await self.coordinator.force_refresh()

    # ---- custom services ----------------------------------------------

    async def async_play_preset(self, preset_id: int) -> None:
        """Service handler: media_player.<entity>_play_preset(preset_id=N)."""
        try:
            await self.coordinator.client.load_preset(int(preset_id))
        except BluOSError as err:
            _LOGGER.warning("play_preset failed: %s", err)
        finally:
            await self.coordinator.force_refresh()

    # ---- internal ------------------------------------------------------

    async def _run(self, coro: Any) -> None:
        """Run a control call and request a refresh, swallowing transient errors."""
        try:
            await coro
        except BluOSError as err:
            _LOGGER.warning("BluOS call failed: %s", err)
        finally:
            await self.coordinator.force_refresh()
