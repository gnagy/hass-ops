"""WebSocket client for the parts of Home Assistant that REST cannot reach.

The entity/device/area/floor/label registries and the Lovelace configs have no
REST equivalent — they are WebSocket-only. That is the whole reason this module
exists alongside the stdlib-only ``ha_api``.

Unlike ``ha_api`` this has a dependency (``websockets``), so importers must
declare it in their PEP 723 block. Keep that dependency here and nowhere else.

Read-only by construction: there is no send-command-and-ignore-result path, and
nothing here writes. Registry *writes* would belong in an apply script, which
should be built against the fixtures a pull produces.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from hass_ops.ha_api import HaApiError, resolve_instance

from websockets.sync.client import connect

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30

# websockets defaults to a 1 MiB frame cap, which HACS blows through instantly:
# hacs/repositories/list returns its entire catalogue, not just what is
# installed, and the client gets a 1009 close mid-pull rather than an error it
# can handle. The registries on a large instance are not far behind. This is a
# read-only tool talking to a machine on the LAN, so the cap buys nothing.
MAX_FRAME_BYTES = 64 * 1024 * 1024


class HaWsError(HaApiError):
    """A WebSocket call that did not come back with a usable result."""


class HaWs:
    """One authenticated WebSocket session. Use as a context manager."""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.instance, base_url, self._token = resolve_instance()
        self._url = self._websocket_url(base_url)
        self._timeout = timeout
        self._connection: Any = None
        self._next_id = 1

    @staticmethod
    def _websocket_url(base_url: str) -> str:
        if base_url.startswith("https://"):
            return "wss://" + base_url[len("https://") :] + "/api/websocket"
        if base_url.startswith("http://"):
            return "ws://" + base_url[len("http://") :] + "/api/websocket"
        raise HaWsError(f"cannot derive a WebSocket URL from {base_url!r}")

    def __enter__(self) -> HaWs:
        self._connection = connect(
            self._url, open_timeout=self._timeout, max_size=MAX_FRAME_BYTES
        )
        self._authenticate()
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _receive(self) -> dict:
        raw = self._connection.recv(timeout=self._timeout)
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HaWsError(f"non-JSON frame from {self._url}: {raw[:200]!r}") from exc
        if not isinstance(message, dict):
            raise HaWsError(f"unexpected frame shape: {type(message).__name__}")
        return message

    def _send(self, payload: dict) -> None:
        self._connection.send(json.dumps(payload))

    def _authenticate(self) -> None:
        hello = self._receive()
        if hello.get("type") != "auth_required":
            raise HaWsError(f"expected auth_required, got {hello.get('type')!r}")

        self._send({"type": "auth", "access_token": self._token})
        result = self._receive()
        if result.get("type") == "auth_invalid":
            raise HaWsError(
                f"authentication rejected by {self.instance}: {result.get('message')}. "
                "The token (HA_<INSTANCE>_TOKEN) may have been revoked."
            )
        if result.get("type") != "auth_ok":
            raise HaWsError(f"expected auth_ok, got {result.get('type')!r}")

    def command(self, command_type: str, **fields: object) -> Any:
        """Send one command and return its ``result``.

        Events and results for other ids are skipped rather than treated as
        errors — subscriptions from elsewhere in the session would otherwise
        derail an unrelated call.
        """
        message_id = self._next_id
        self._next_id += 1
        self._send({"id": message_id, "type": command_type, **fields})

        while True:
            message = self._receive()
            if message.get("id") != message_id or message.get("type") != "result":
                continue
            if not message.get("success", False):
                error = message.get("error") or {}
                raise HaWsError(
                    f"{command_type} failed: {error.get('code', '?')} "
                    f"{error.get('message', '(no message)')}"
                )
            return message.get("result")

    def try_command(self, command_type: str, **fields: object) -> Any | None:
        """Like ``command`` but returns None when the command is unavailable.

        For optional surfaces — HACS is not installed everywhere, and the
        default dashboard raises when it is strategy-generated rather than
        stored.
        """
        try:
            return self.command(command_type, **fields)
        except HaWsError as exc:
            log.debug("optional command %s unavailable: %s", command_type, exc)
            return None
