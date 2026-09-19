"""Two read-only HACS checks: can HACS download, and did what it downloaded arrive.

  resources   every Lovelace resource URL answers 200             -> exit 1 if not
  preflight   the GitHub token HACS holds is accepted by GitHub   -> exit 1 if not

Both exist because of one failure. HACS updates a plugin by deleting its folder
under www/community/ and then downloading the release asset. On 2026-09-11 the
download was refused - the token had been revoked - and mini-climate-card was
left with no files while HACS went on recording it as installed. Nothing said
so until two dashboards showed "Custom element doesn't exist".

HACS never noticed the token was dead either. It only starts reauth when a call
through its API wrapper raises an authentication error; plugin downloads take a
different path and just log `<Plugin ...> 401`. So `preflight` before any HACS
update, `resources` after it.

`preflight` runs on the instance over SSH, because that is where the token is.
The token is read and used there and never printed or sent back - only GitHub's
status code and the rate limit come out.

Exit codes: 0 ok, 1 findings, 2 could not reach the instance.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from hass_ops.ha_api import HaApiError, resolve_instance
from hass_ops.ha_ws import HaWs

TIMEOUT = 15

# Runs on the instance. Prints one line: the HTTP status, then the core limit.
REMOTE_PREFLIGHT = r"""
import json, urllib.request, urllib.error
entries = json.load(open("/config/.storage/core.config_entries"))["data"]["entries"]
hacs = [e for e in entries if e["domain"] == "hacs"]
if not hacs:
    print("NO_ENTRY 0"); raise SystemExit
token = hacs[0]["data"].get("token", "")
req = urllib.request.Request(
    "https://api.github.com/rate_limit",
    headers={"Authorization": "token " + token, "User-Agent": "ha-workspace-preflight"},
)
try:
    with urllib.request.urlopen(req, timeout=15) as r:
        core = json.load(r)["resources"]["core"]
        print(r.status, core["remaining"], core["limit"])
except urllib.error.HTTPError as exc:
    print(exc.code, 0, 0)
"""


def check_resources() -> int:
    instance, base_url, _ = resolve_instance()
    with HaWs() as ws:
        resources = ws.try_command("lovelace/resources") or []
    print(f"instance={instance}  resources={len(resources)}")

    failures = 0
    for resource in resources:
        url = resource["url"]
        full = url if url.startswith(("http://", "https://")) else f"{base_url}/{url.lstrip('/')}"
        try:
            with urllib.request.urlopen(full, timeout=TIMEOUT) as response:
                status = response.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        except urllib.error.URLError as exc:
            status = f"unreachable ({exc.reason})"
        if status == 200:
            print(f"ok       {url}")
        else:
            failures += 1
            print(f"BROKEN   {url}  -> {status}")

    if failures:
        print(f"\n{failures} resource(s) do not load; every card they define renders as an error.")
        print("A HACS plugin here was probably half-updated - run `hass-ops hacs preflight`, then redownload it.")
        return 1
    return 0


def check_preflight() -> int:
    instance, _, _ = resolve_instance()
    ssh = os.environ.get(f"HA_{instance.upper()}_SSH")
    if not ssh:
        print(f"error: HA_{instance.upper()}_SSH is not set: give the instance an `ssh` in hass-ops.toml.", file=sys.stderr)
        return 2

    result = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=10", ssh, "python3", "-"],
        input=REMOTE_PREFLIGHT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        print(f"error: ssh {ssh} failed: {result.stderr.strip()}", file=sys.stderr)
        return 2

    status, remaining, limit = result.stdout.split()
    print(f"instance={instance}  github_status={status}  rate_limit={remaining}/{limit}")
    if status == "200":
        return 0
    if status == "NO_ENTRY":
        print("HACS has no config entry on this instance.")
    else:
        print("GitHub rejects the HACS token. Any HACS update will fail, and a plugin update")
        print("will delete the installed files first. Re-add the HACS integration before updating.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("check", choices=["resources", "preflight"])
    args = parser.parse_args()
    try:
        return check_resources() if args.check == "resources" else check_preflight()
    except HaApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
