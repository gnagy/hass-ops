# Install

This puts the `hass-ops` command on the machine you work from. Setting up a repository for your Home Assistant
configuration is the next step: [Set up your configuration repository](setup.md).

## Install uv

hass-ops installs with [uv](https://docs.astral.sh/uv/), a Python package and tool manager. Install uv
whichever way you prefer:

- the [standalone installer or a package manager](https://docs.astral.sh/uv/getting-started/installation/)
  (Homebrew, winget and others);
- or, if you manage tools with [mise](https://mise.jdx.dev), see [With mise](#with-mise) below.

You don't need Python installed first: uv fetches Python 3.12 or later itself if there isn't one.

## Install hass-ops

```shell
uv tool install git+https://github.com/gnagy/hass-ops
hass-ops --help
```

From a clone of the repository, `uv tool install -e .` installs the working tree instead.

## What the install sets up, and where

`uv tool install` does everything in one step, and nothing else happens behind your back. On macOS and Linux:

| What                            | Where                               | Created by                                                                   |
|---------------------------------|-------------------------------------|------------------------------------------------------------------------------|
| An isolated Python environment  | `~/.local/share/uv/tools/hass-ops/` | uv: hass-ops and its three dependencies, and nothing shared with other tools |
| A Python interpreter, if needed | `~/.local/share/uv/python/`         | uv, only when no Python 3.12 or later is installed; other tools can share it |
| The `hass-ops` command          | `~/.local/bin/hass-ops`             | uv: a link into the environment, so no activation step is needed             |
| Downloaded packages             | `~/.cache/uv/`                      | uv's download cache; safe to delete                                          |

`~/.local/bin` has to be on your `PATH`. uv warns when it isn't, and `uv tool update-shell` adds it to your
shell's startup file. On other systems, or with `XDG_*` variables set, `uv tool dir`, `uv tool dir --bin`,
`uv python dir` and `uv cache dir` print the actual locations.

To upgrade or remove it:

```shell
uv tool upgrade hass-ops
uv tool uninstall hass-ops      # removes the environment and the command; the Python stays for other tools
```

hass-ops itself stores nothing outside your project. It has no settings file in your home directory and
keeps no cache. It writes only `exports/` (on `pull`) and `desired/` (on `promote --write`) inside the
project, and, when you tell it to, the Home Assistant instance. Tokens are read from your keychain or the
environment each time and never saved.

## With mise

If you use [mise](https://mise.jdx.dev) for your tools, let it install uv and hass-ops, pinned in your config
repository's `mise.toml` so every machine you work from gets the same version:

```toml
[tools]
uv = "latest"
"pipx:gnagy/hass-ops" = "master"
```

```shell
mise install
```

mise's `pipx:` backend installs Python tools with uv when uv is available. The environment then lives in
mise's own directory, `~/.local/share/mise/installs/pipx-gnagy-hass-ops/<version>/`, one per version, and
`mise uninstall` removes it. `master` follows the latest commit; once there are tagged releases, pin one
instead (`"pipx:gnagy/hass-ops" = "0.1.0"`). To install it for your user rather than per repository:
`mise use -g uv "pipx:gnagy/hass-ops@master"`.

mise can also hold the project's shorthands as tasks, e.g.:

```toml
[tasks.deploy]
run = "hass-ops deploy"

[tasks.drift]
run = "hass-ops drift"
```

Keep tokens out of `mise.toml`: use `token_command` (see [Tokens](setup.md#3-give-it-a-token)), or
`HA_<INSTANCE>_TOKEN` in an untracked `mise.local.toml` if you must.
