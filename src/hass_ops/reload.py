"""Reload one Home Assistant config domain.

A restart is a multi-minute outage of the house. For a change to one automation
that is the wrong tool, so the deploy path ends here rather than at `ha core
restart`.

  reload.py automation
  reload.py script scene
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from hass_ops.ha_api import HaApi, HaApiError

# Domains whose reload service exists on a default install. Not exhaustive —
# anything else is passed through, since integrations add their own.
COMMON = ("automation", "script", "scene", "template", "input_boolean", "group")


def main() -> int:
    domains = sys.argv[1:]
    if not domains:
        print(f"usage: hass-ops reload <domain> [...]\ncommon: {', '.join(COMMON)}", file=sys.stderr)
        return 64

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        api = HaApi()
        for domain in domains:
            api.reload(domain)
            print(f"reloaded: {domain}")
    except HaApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
