"""DataUpdateCoordinator for the Bluesound Custom integration.

Strategy:

* ``/Status`` is read with long-polling (``?timeout=N&etag=X``) so that the
  device wakes us up only when something changes. The HTTP timeout is set to
  ``N + 15`` seconds so the device's own timeout fires first on a quiet line.
* ``/Presets`` and ``/Services`` are refreshed on slow cadences inside the
  same coordinator tick because they rarely change.
* ``/SyncStatus`` is refreshed when the ``syncStat`` token in /Status changes
  (which happens on rename, group join/leave, ...).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    BluOSClient,
    BluOSConnectionError,
    BluOSError,
    Preset,
    Service,
    Status,
    SyncStatus,
)
from .const import (
    DOMAIN,
    OFFLINE_RETRY_INTERVAL,
    PRESETS_REFRESH_INTERVAL,
    SERVICES_REFRESH_INTERVAL,
    STATUS_LONG_POLL_TIMEOUT,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


@dataclass
class BluesoundData:
    """One coherent snapshot of player state."""

    status: Status
    sync_status: SyncStatus
    presets: list[Preset] = field(default_factory=list)
    services: list[Service] = field(default_factory=list)
    fetched_at: datetime | None = None


class BluesoundCustomCoordinator(DataUpdateCoordinator[BluesoundData]):
    """Long-polling coordinator for a single BluOS device."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: "ConfigEntry",
        client: BluOSClient,
        sync_status: SyncStatus,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({sync_status.name or client.host})",
            # Only used as a *recovery* interval — _async_update_data already
            # blocks for ~STATUS_LONG_POLL_TIMEOUT seconds in the success path.
            update_interval=timedelta(seconds=OFFLINE_RETRY_INTERVAL),
            always_update=False,
        )
        self.entry = entry
        self.client = client
        self.sync_status = sync_status
        self._etag: str | None = None
        self._presets: list[Preset] = []
        self._services: list[Service] = []
        self._presets_age: float = 0.0
        self._services_age: float = 0.0
        self._last_sync_stat: str | None = sync_status.raw.get("@syncStat") if sync_status.raw else None
        self.folder_key: str | None = None

    async def _async_setup(self) -> None:
        """One-time setup before the first data refresh.

        Probe a list of candidate BluOS browse keys (in parallel) to find
        the one that drills into the file-system folder view of the local
        music library. The exact key isn't documented in BluOS API v1.7
        and varies by firmware; the first candidate that returns items is
        cached on ``self.folder_key`` for the lifetime of the coordinator.
        If no candidate works, ``folder_key`` stays None and the media
        browser hides the Folders entry rather than surfacing a dead link.
        """
        from .const import FOLDER_KEY_CANDIDATES

        async def _probe(candidate: str) -> str | None:
            try:
                items = await self.client.browse(key=candidate)
            except BluOSError:
                return None
            return candidate if items else None

        results = await asyncio.gather(
            *(_probe(c) for c in FOLDER_KEY_CANDIDATES),
            return_exceptions=False,
        )
        for candidate, result in zip(FOLDER_KEY_CANDIDATES, results):
            if result:
                self.folder_key = result
                _LOGGER.debug("BluOS folder view discovered at key=%r", result)
                return
        _LOGGER.debug("BluOS folder view not exposed on this device")

    async def _async_update_data(self) -> BluesoundData:
        # /Status long-poll. On reconnect (etag=None) we get an immediate snapshot.
        try:
            status = await self.client.status(
                etag=self._etag,
                timeout=STATUS_LONG_POLL_TIMEOUT,
            )
        except BluOSConnectionError as err:
            self._etag = None
            raise UpdateFailed(f"BluOS device unreachable: {err}") from err
        except BluOSError as err:
            self._etag = None
            raise UpdateFailed(f"BluOS error: {err}") from err

        self._etag = status.etag

        now = time.monotonic()

        # Presets — needed for the Favourite Radios browser node.
        if not self._presets or (now - self._presets_age) > PRESETS_REFRESH_INTERVAL:
            try:
                self._presets = await self.client.presets()
                self._presets_age = now
            except BluOSError as err:
                _LOGGER.debug("Preset refresh failed: %s", err)

        # Services — needed for the Streaming Services browser node and source_list.
        if not self._services or (now - self._services_age) > SERVICES_REFRESH_INTERVAL:
            try:
                self._services = await self.client.services()
                self._services_age = now
            except BluOSError as err:
                _LOGGER.debug("Service refresh failed: %s", err)

        # SyncStatus is small but rarely changes; refresh only on syncStat change.
        if status.sync_stat and status.sync_stat != self._last_sync_stat:
            try:
                self.sync_status = await self.client.sync_status()
                self._last_sync_stat = status.sync_stat
            except BluOSError as err:
                _LOGGER.debug("SyncStatus refresh failed: %s", err)

        return BluesoundData(
            status=status,
            sync_status=self.sync_status,
            presets=list(self._presets),
            services=list(self._services),
            fetched_at=dt_util.utcnow(),
        )

    async def force_refresh(self) -> None:
        """Reset the etag and request an immediate refresh after a control action."""
        self._etag = None
        await self.async_request_refresh()
