"""hass-ops: operate a Home Assistant instance as code.

    hass-ops [-i INSTANCE] [-C DIR] <command> [args...]

Every command resolves the project (hass-ops.toml, walked up from the working directory) and the target
instance first, and prints both. Writes are opt-in per command: `apply --write`, `promote --write`,
`deploy` (asks before transferring, unless --yes). `<command> --help` shows each command's options.
"""

from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
from importlib import resources
from pathlib import Path

from hass_ops import project as project_mod

# command -> (module, one-line description). The module's main() parses the remaining arguments itself.
COMMANDS: dict[str, tuple[str, str]] = {
    "check": ("hass_ops.validate.entity_refs", "parse all config YAML and check entity_id references live"),
    "hacs": ("hass_ops.validate.hacs", "HACS checks: `resources` (every Lovelace resource loads), `preflight`"),
    "pull": ("hass_ops.pull", "read tier-2 state (registries, dashboards, HACS, config entries) into exports/"),
    "drift": ("", "pull, then fail if exports/ changed: something was edited outside the repo"),
    "promote": ("hass_ops.promote", "adopt exports/ into desired/ (dry run unless --write)"),
    "apply": ("hass_ops.apply", "reconcile the instance toward desired/ (dry run unless --write)"),
    "deploy": ("", "rsync the config to the instance, after check and a dry run; --dry-run stops there"),
    "reload": ("hass_ops.reload", "reload config domains, e.g. `reload automation template`; never a restart"),
    "exec": ("", "run a command with the instance in its environment: `exec -- docker compose up -d`"),
    "ha-mcp": ("hass_ops.ha_mcp", "run the ha-mcp MCP server against the instance, settings from [ha_mcp]"),
}


def _run_module(module: str, prog: str, argv: list[str]) -> int:
    """Hand the remaining arguments to a command module's own argparse."""
    mod = importlib.import_module(module)
    sys.argv = [prog, *argv]
    try:
        return int(mod.main() or 0)
    except SystemExit as exc:  # argparse --help and usage errors
        return int(exc.code or 0) if isinstance(exc.code, int) else 1


def _drift(proj: project_mod.Project, prog: str, argv: list[str]) -> int:
    code = _run_module("hass_ops.pull", f"{prog} pull", argv)
    if code:
        return code
    return subprocess.call(
        ["git", "diff", "--exit-code", "--stat", "--", str(proj.exports)], cwd=proj.root
    )


def _deploy(proj: project_mod.Project, prog: str, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=f"{prog} deploy", description=COMMANDS["deploy"][1])
    parser.add_argument("--dry-run", action="store_true", help="show what rsync would change; transfer nothing")
    parser.add_argument("--yes", action="store_true", help="do not ask before transferring")
    parser.add_argument("--skip-check", action="store_true", help="skip `check` before a real deploy")
    args = parser.parse_args(argv)
    if not args.dry_run and not args.skip_check:
        code = _run_module("hass_ops.validate.entity_refs", f"{prog} check", [])
        if code:
            print("check failed: not deploying (--skip-check to override)", file=sys.stderr)
            return code
    env = dict(
        os.environ,
        HASS_OPS_ROOT=str(proj.root),
        HASS_OPS_CONFIG_DIR=str(proj.config),
        HASS_OPS_RSYNCIGNORE=str(proj.rsyncignore),
    )
    if args.yes:
        env["HA_DEPLOY_YES"] = "1"
    script = resources.files("hass_ops").joinpath("deploy.sh")
    with resources.as_file(script) as path:
        return subprocess.call(["bash", str(path), "dry" if args.dry_run else "apply"], env=env)


def _exec(prog: str, argv: list[str]) -> int:
    """Run any command with the selected instance published: HA_INSTANCE, HA_<NAME>_URL, _SSH and _TOKEN.

    For scripts that use the hass_ops client library and for tools that take an HA URL and token from the
    environment, so neither needs its own copy of either.
    """
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        print(f"usage: {prog} exec -- <command> [args...]", file=sys.stderr)
        return 64
    try:
        return subprocess.call(argv)
    except FileNotFoundError:
        print(f"error: command not found: {argv[0]}", file=sys.stderr)
        return 127


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="hass-ops",
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="commands:\n" + "\n".join(f"  {name:<9} {desc}" for name, (_, desc) in COMMANDS.items()),
    )
    parser.add_argument("-i", "--instance", help="target instance from hass-ops.toml (default: HA_INSTANCE, then the file's default)")
    parser.add_argument("-C", "--project", type=Path, help="project directory, instead of searching from the working directory")
    parser.add_argument("command", choices=COMMANDS, metavar="command")
    parser.add_argument("args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    ns = parser.parse_args(argv)

    try:
        proj, _ = project_mod.activate(ns.project, ns.instance)
    except project_mod.ProjectError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    prog = "hass-ops"
    if ns.command == "drift":
        return _drift(proj, prog, ns.args)
    if ns.command == "deploy":
        return _deploy(proj, prog, ns.args)
    if ns.command == "exec":
        return _exec(prog, ns.args)
    return _run_module(COMMANDS[ns.command][0], f"{prog} {ns.command}", ns.args)


if __name__ == "__main__":
    sys.exit(main())
