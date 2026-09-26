"""Run ha-mcp, the Home Assistant MCP server, against the targeted instance.

  hass-ops -i test ha-mcp            # an MCP client starts this; it speaks MCP on stdin/stdout
  hass-ops -i prod ha-mcp --print    # show the command and environment it would run, token hidden

ha-mcp (https://github.com/homeassistant-ai/ha-mcp) takes all of its settings from the environment. This
command builds that environment from hass-ops.toml, so an MCP client entry needs no URL, token or settings
of its own:

- HOMEASSISTANT_URL and HOMEASSISTANT_TOKEN from the instance, the token from its token_command as usual;
- READ_ONLY_MODE from the instance's `read_only`, which is true unless the file sets it false;
- HA_MCP_DISABLE_SETTINGS_UI=1, so no settings web page runs next to a stdio server;
- HA_MCP_CONFIG_DIR=~/.ha-mcp/<instance>, so instances do not share ha-mcp's saved state;
- then `[ha_mcp.env]`, then `[instances.<name>.ha_mcp.env]`, each overriding what came before.

The process then becomes `uvx <package>`, so stdin and stdout belong to the server.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import sys
from pathlib import Path

from hass_ops import project as project_mod

HIDDEN = ("HOMEASSISTANT_TOKEN",)


def build(proj: project_mod.Project, target: project_mod.Instance) -> tuple[list[str], dict[str, str]]:
    """The command to run and the variables to add to the environment for it."""
    if proj.ha_mcp is None:
        raise project_mod.ProjectError(
            f"{project_mod.FILENAME} has no [ha_mcp] table; add one with package = \"ha-mcp==<version>\""
        )
    token = os.environ.get(f"HA_{target.name.upper()}_TOKEN")
    if not token:
        raise project_mod.ProjectError(
            f"no token for {target.name!r}: set HA_{target.name.upper()}_TOKEN or a token_command"
        )
    env = {
        "HA_MCP_DISABLE_SETTINGS_UI": "1",
        "HA_MCP_CONFIG_DIR": str(Path.home() / ".ha-mcp" / target.name),
        **proj.ha_mcp.env,
        **target.ha_mcp.env,
        "HOMEASSISTANT_URL": target.url,
        "HOMEASSISTANT_TOKEN": token,
        "READ_ONLY_MODE": "true" if target.ha_mcp.read_only else "false",
    }
    env["HA_MCP_CONFIG_DIR"] = str(Path(env["HA_MCP_CONFIG_DIR"]).expanduser())
    return ["uvx", proj.ha_mcp.package], env


def main() -> int:
    parser = argparse.ArgumentParser(prog="hass-ops ha-mcp", description=__doc__.splitlines()[0])
    parser.add_argument("--print", action="store_true", help="show the command and environment; run nothing")
    args = parser.parse_args(sys.argv[1:])

    proj = project_mod.current()
    target = proj.instance()
    try:
        command, extra = build(proj, target)
    except project_mod.ProjectError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.print:
        for key in sorted(extra):
            print(f"{key}={'<hidden>' if key in HIDDEN else extra[key]}")
        print(shlex.join(command))
        return 0

    mode = "read-only" if target.ha_mcp.read_only else "WRITES ALLOWED"
    # stdout is the MCP channel from here on, so everything said goes to stderr
    print(f"ha-mcp: instance={target.name} {mode} package={command[1]}", file=sys.stderr)
    if shutil.which(command[0]) is None:
        print(f"error: {command[0]} not found on PATH; install uv", file=sys.stderr)
        return 127
    Path(extra["HA_MCP_CONFIG_DIR"]).mkdir(parents=True, exist_ok=True)
    sys.stdout.flush()
    os.execvpe(command[0], command, {**os.environ, **extra})
    return 0  # not reached


if __name__ == "__main__":
    sys.exit(main())
