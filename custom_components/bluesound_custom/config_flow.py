"""Config flow for the Bluesound Custom integration.

Two entry points:

* ``user``     – user manually types in ``host[:port]``.
* ``zeroconf`` – the player advertises itself on ``_musc._tcp.local.``.

Both paths probe the device with ``/SyncStatus`` to confirm we're talking to
a BluOS player and to extract the MAC, which we use as the unique-id.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .api import BluOSClient, BluOSError
from .const import DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)


class _CannotConnect(Exception):
    """Raised when the device cannot be reached."""


class _InvalidResponse(Exception):
    """Raised when the device responds but does not look like a BluOS player."""


class BluesoundCustomConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI configuration flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._port: int = DEFAULT_PORT
        self._mac: str | None = None
        self._name: str | None = None

    # ---- user step ------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host: str = user_input[CONF_HOST]
            port: int = user_input.get(CONF_PORT, DEFAULT_PORT)
            try:
                info = await _probe(self.hass, host, port)
            except _CannotConnect:
                errors["base"] = "cannot_connect"
            except _InvalidResponse:
                errors["base"] = "invalid_response"
            except Exception:  # noqa: BLE001 - last-resort safety net
                _LOGGER.exception("Unexpected error probing %s:%s", host, port)
                errors["base"] = "unknown"
            else:
                if not info["mac"]:
                    return self.async_abort(reason="no_mac")
                await self.async_set_unique_id(info["mac"])
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: host, CONF_PORT: port}
                )
                return self.async_create_entry(
                    title=info["name"] or host,
                    data={CONF_HOST: host, CONF_PORT: port},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
                }
            ),
            errors=errors,
        )

    # ---- zeroconf step --------------------------------------------------

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        host = str(discovery_info.host)
        port = discovery_info.port or DEFAULT_PORT
        try:
            info = await _probe(self.hass, host, port)
        except (_CannotConnect, _InvalidResponse):
            return self.async_abort(reason="cannot_connect")
        if not info["mac"]:
            return self.async_abort(reason="no_mac")

        await self.async_set_unique_id(info["mac"])
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: host, CONF_PORT: port}
        )

        self._host = host
        self._port = port
        self._mac = info["mac"]
        self._name = info["name"]
        self.context["title_placeholders"] = {
            "name": info["name"] or host,
            "host": host,
        }
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=self._name or self._host or "Bluesound",
                data={CONF_HOST: self._host, CONF_PORT: self._port},
            )
        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={
                "name": self._name or "",
                "host": self._host or "",
            },
        )


# ---------------------------------------------------------------------------


async def _probe(hass, host: str, port: int) -> dict[str, str]:
    """Make a single /SyncStatus call to confirm the device is BluOS."""
    session = async_get_clientsession(hass)
    client = BluOSClient(session, host, port, timeout=8)
    try:
        sync = await client.sync_status()
    except BluOSError as err:
        raise _CannotConnect(str(err)) from err
    if not sync.mac and not sync.name:
        raise _InvalidResponse("missing mac and name in SyncStatus response")
    return {"mac": sync.mac or "", "name": sync.name or ""}
