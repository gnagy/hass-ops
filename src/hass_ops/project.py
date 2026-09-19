"""The project a command runs against: `hass-ops.toml`, found by walking up from the working directory.

A project is one Home Assistant configuration kept as code. The file says where its parts are and which
instances it deploys to:

    [paths]                     # relative to hass-ops.toml; these are the defaults
    config = "ha-config"        # tier 1, rsynced to /config
    desired = "desired"         # tier 2, what apply reconciles toward
    exports = "exports"         # tier 2, what pull records
    rsyncignore = ".rsyncignore"

    [check]
    skip_dirs = ["www"]         # directories under config/ that hold no HA YAML

    [instances.prod]
    url = "https://homeassistant.example"
    ssh = "homeassistant"       # ssh host for deploys and `ha core check`
    token_command = "security find-generic-password -s hass-ops -a prod -w"
    default = true

    [instances.test]
    url = "https://ha-test.example"
    ssh = "ha-test"

Tokens are never in the file. An instance's token is `HA_<NAME>_TOKEN` from the environment when that is set,
otherwise the output of its `token_command`, run through the shell: a keychain or password-manager lookup
such as `security find-generic-password ... -w` (macOS), `op read op://...`, `pass show ...` or
`secret-tool lookup ...`. The command is only run for the instance a command targets.

Which instance a command targets is decided once, here, in this order: `--instance`, then `HA_INSTANCE`,
then the instance marked `default`. The choice is printed before anything connects.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

FILENAME = "hass-ops.toml"


class ProjectError(RuntimeError):
    """The project or the instance could not be resolved."""


@dataclass(frozen=True)
class Instance:
    name: str
    url: str
    ssh: str | None = None
    default: bool = False
    token_command: str | None = None


@dataclass(frozen=True)
class Project:
    root: Path
    config: Path
    desired: Path
    exports: Path
    rsyncignore: Path
    skip_dirs: frozenset[str] = frozenset()
    instances: dict[str, Instance] = field(default_factory=dict)

    def relative(self, path: Path) -> str:
        """A path as shown to the user: relative to the project root when it is inside it."""
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)

    def instance(self, name: str | None = None) -> Instance:
        """Resolve the target instance: explicit name, then HA_INSTANCE, then the default."""
        chosen = name or os.environ.get("HA_INSTANCE")
        if not chosen:
            defaults = [i for i in self.instances.values() if i.default]
            if len(defaults) != 1:
                raise ProjectError(
                    f"no instance given and {FILENAME} marks {len(defaults)} as default; pass --instance"
                )
            return defaults[0]
        if chosen not in self.instances:
            known = ", ".join(sorted(self.instances)) or "none"
            raise ProjectError(f"unknown instance {chosen!r}; {FILENAME} defines: {known}")
        return self.instances[chosen]


def find(start: Path | None = None) -> Path:
    """The nearest hass-ops.toml at or above `start` (default: the working directory)."""
    override = os.environ.get("HASS_OPS_PROJECT")
    if override:
        path = Path(override).expanduser()
        candidate = path / FILENAME if path.is_dir() else path
        if not candidate.is_file():
            raise ProjectError(f"HASS_OPS_PROJECT={override} has no {FILENAME}")
        return candidate.resolve()
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / FILENAME
        if candidate.is_file():
            return candidate
    raise ProjectError(f"no {FILENAME} in {here} or above it; run inside a project or pass --project")


def load(path: Path) -> Project:
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ProjectError(f"{path}: {exc}") from exc
    root = path.parent
    paths = data.get("paths", {})

    def at(key: str, default: str) -> Path:
        return (root / paths.get(key, default)).resolve()

    instances = {
        name: Instance(
            name=name,
            url=spec["url"].rstrip("/"),
            ssh=spec.get("ssh"),
            default=bool(spec.get("default")),
            token_command=spec.get("token_command"),
        )
        for name, spec in data.get("instances", {}).items()
    }
    return Project(
        root=root,
        config=at("config", "ha-config"),
        desired=at("desired", "desired"),
        exports=at("exports", "exports"),
        rsyncignore=at("rsyncignore", ".rsyncignore"),
        skip_dirs=frozenset(data.get("check", {}).get("skip_dirs", ["www"])),
        instances=instances,
    )


_current: Project | None = None


def activate(project_dir: Path | None = None, instance: str | None = None) -> tuple[Project, Instance]:
    """Load the project and select the instance for this process.

    The chosen instance is published to the environment (HA_INSTANCE, HA_<NAME>_URL, HA_<NAME>_SSH and, when
    it was not already set, HA_<NAME>_TOKEN from token_command) so the clients and deploy.sh read one answer.
    The file wins over anything already set for URL and ssh host; the environment wins for the token.
    """
    global _current
    _current = load(find(project_dir))
    target = _current.instance(instance)
    prefix = f"HA_{target.name.upper()}"
    os.environ["HA_INSTANCE"] = target.name
    os.environ[f"{prefix}_URL"] = target.url
    if target.ssh:
        os.environ[f"{prefix}_SSH"] = target.ssh
    if not os.environ.get(f"{prefix}_TOKEN") and target.token_command:
        os.environ[f"{prefix}_TOKEN"] = run_token_command(target)
    print(f"project={_current.root}  instance={target.name}  url={target.url}", file=sys.stderr)
    return _current, target


def run_token_command(target: Instance) -> str:
    """Run an instance's token_command and return its first line. The token is never printed."""
    assert target.token_command
    try:
        result = subprocess.run(
            target.token_command, shell=True, capture_output=True, text=True, timeout=60, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise ProjectError(f"token_command for {target.name!r} timed out") from exc
    token = result.stdout.strip().splitlines()[0].strip() if result.stdout.strip() else ""
    if result.returncode != 0 or not token:
        detail = (result.stderr.strip().splitlines() or ["no output"])[-1].rstrip(".")
        raise ProjectError(
            f"token_command for {target.name!r} failed (exit {result.returncode}): {detail}. "
            f"Set HA_{target.name.upper()}_TOKEN instead, or fix the command in {FILENAME}."
        )
    return token


def current() -> Project:
    """The project activated for this process; loads it from the working directory if none was."""
    global _current
    if _current is None:
        _current = load(find())
    return _current
