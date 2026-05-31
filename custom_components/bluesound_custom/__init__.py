"""The Bluesound Custom integration.

A HACS-distributable Home Assistant integration for Bluesound / BluOS
devices with rich ``async_browse_media`` support for the local library,
internet radio, favourite presets, streaming services, and playlists.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BluOSClient, BluOSError
from .const import DEFAULT_PORT
from .coordinator import BluesoundCustomCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER]

# Typed config-entry alias. We avoid the PEP 695 ``type`` statement so this
# module also syntax-checks on Python < 3.12; at runtime HA 2024.8+ runs on
# Python 3.12+ where the parameterised form is also valid.
BluesoundCustomConfigEntry = ConfigEntry


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Set up a Bluesound Custom config entry."""
    host: str = entry.data[CONF_HOST]
    port: int = entry.data.get(CONF_PORT, DEFAULT_PORT)
    session = async_get_clientsession(hass)
    client = BluOSClient(session, host, port)

    try:
        sync = await client.sync_status()
    except BluOSError as err:
        raise ConfigEntryNotReady(f"Cannot reach {host}:{port}: {err}") from err

    coordinator = BluesoundCustomCoordinator(hass, entry, client, sync)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Tear down a Bluesound Custom config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
