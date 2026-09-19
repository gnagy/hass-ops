"""Instance-parameterised Home Assistant REST client.

Every tool in this repo resolves its target the same way: read ``HA_INSTANCE``,
then look up ``HA_{INSTANCE}_URL`` and ``HA_{INSTANCE}_TOKEN``. No tool ever
hardcodes a URL. There is exactly one instance today and it is the live house,
so which instance a tool is about to touch has to be an explicit, logged fact
rather than a default buried in a script.

Stdlib only, deliberately: this is the module every other tool imports, and a
dependency here is a dependency everywhere.

Registry and Lovelace work needs the WebSocket API, not this. That belongs in a
sibling module when the pull scripts get written.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30


class HaApiError(RuntimeError):
    """Anything that stops a call reaching the instance or coming back intact."""


def resolve_instance() -> tuple[str, str, str]:
    """Return ``(instance, base_url, token)`` from the environment.

    Raises HaApiError with a message that says what to set, rather than letting
    a tool run on with a None URL and fail somewhere less obvious.
    """
    instance = os.environ.get("HA_INSTANCE")
    if not instance:
        raise HaApiError(
            "HA_INSTANCE is not set. Run through the `hass-ops` command, which selects "
            "the instance from hass-ops.toml."
        )

    prefix = f"HA_{instance.upper()}"
    url = os.environ.get(f"{prefix}_URL")
    token = os.environ.get(f"{prefix}_TOKEN")

    missing = [
        name
        for name, value in ((f"{prefix}_URL", url), (f"{prefix}_TOKEN", token))
        if not value
    ]
    if missing:
        raise HaApiError(
            f"HA_INSTANCE={instance!r} but {' and '.join(missing)} unset. "
            "URLs belong in hass-ops.toml; the token in the environment as "
            f"{prefix}_TOKEN. Never put a token in a tracked file."
        )

    assert url is not None and token is not None  # narrowed by the check above
    return instance, url.rstrip("/"), token


class HaApi:
    """Thin REST wrapper. One instance per process; resolves on construction."""

    def __init__(self) -> None:
        self.instance, self.base_url, self._token = resolve_instance()

    def __repr__(self) -> str:
        return f"<HaApi instance={self.instance} url={self.base_url}>"

    def _request(self, method: str, path: str, payload: object | None = None) -> object:
        url = f"{self.base_url}/api/{path.lstrip('/')}"
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT) as response:
                raw = response.read().decode()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            raise HaApiError(f"{method} /api/{path} -> HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise HaApiError(f"{method} /api/{path} -> {exc.reason}") from exc
        return json.loads(raw) if raw.strip() else None

    def get(self, path: str) -> object:
        return self._request("GET", path)

    def post(self, path: str, payload: object | None = None) -> object:
        # Every write says where it is going, before it goes there.
        log.info("WRITE instance=%s url=%s path=/api/%s", self.instance, self.base_url, path)
        return self._request("POST", path, {} if payload is None else payload)

    def states(self) -> list[dict]:
        """All entities that currently exist, with their states.

        Note this is the *state machine*, not the entity registry: disabled
        registry entries do not appear here. It is the right source for "does
        this entity_id resolve at runtime", which is the question that matters
        for a YAML reference.
        """
        result = self.get("states")
        if not isinstance(result, list):
            raise HaApiError(f"GET /api/states returned {type(result).__name__}, expected list")
        return result

    def service_names(self) -> set[str]:
        """Every callable service as ``domain.service``.

        Service names are shaped exactly like entity_ids — ``light.turn_on`` is
        indistinguishable from ``light.kitchen`` by pattern alone — so any tool
        scanning YAML for entity references needs this to tell them apart.
        """
        result = self.get("services")
        if not isinstance(result, list):
            raise HaApiError(f"GET /api/services returned {type(result).__name__}, expected list")
        return {
            f"{entry['domain']}.{service}"
            for entry in result
            if isinstance(entry, dict) and "domain" in entry
            for service in (entry.get("services") or {})
        }

    def reload(self, domain: str) -> None:
        """Reload one config domain. Never restart for a config change."""
        self.post(f"services/{domain}/reload")
