# hass-ops

Run a Home Assistant instance from a git repository. hass-ops checks your YAML against the live instance,
deploys it through guarded steps, turns what was changed in the UI into a diff you can review, and gives
scripts and AI agents the instance's URL and token without a copy of either.

For people who already know Home Assistant well, work in a terminal, and want their setup kept as code.

## The problems

Keeping Home Assistant's configuration in git gets you history, but most of the risks stay:

- **Mistakes pass the checks.** An automation that refers to a misspelled `entity_id` is valid YAML, passes
  `ha core check`, reloads, and never runs. Nothing reports it.
- **Deploying is a bare rsync.** Copying the repository to `/config` with `--delete` removes whatever on the
  instance is not in the repository. Miss one line in the exclude list and that can be `.storage`, the
  database or `secrets.yaml`.
- **Half the configuration is not in files.** Entity names, areas, labels, floors and UI dashboards live in
  `.storage`, which Home Assistant owns and rewrites. A rename from a phone never shows up in `git diff`, and
  editing those files by hand is overwritten on the next save.
- **Several consumers, several copies of the token.** Deploy scripts, one-off scripts and an MCP server for
  an AI agent each want the instance's URL and a long-lived token. Each keeps its own copy, in its own
  environment file, and nothing says which instance it is about to write to.

## How it works

Your repository holds the YAML Home Assistant reads, a record of the state Home Assistant keeps to itself
(the entity, device and area **registries**, and UI dashboards), and the part of that state you want to
manage. hass-ops moves data between the repository and the instance in both directions, and never without
showing you first. [Architecture](docs/architecture.md) has the full picture: a diagram of what moves where,
why the registries matter, and every safeguard.

## A session

Changing an automation:

```shell
hass-ops pull                   # copy entity names, areas and dashboards from Home Assistant into exports/
git diff                        # did anyone change them in the UI since last time? commit that first

$EDITOR ha-config/automations.yaml

hass-ops check                  # is the YAML valid, and does every entity it uses exist?
hass-ops deploy                 # shows what it will copy to Home Assistant, asks, then copies it
hass-ops reload automation      # Home Assistant loads the new automations; no restart

# try it; when it works:
git commit -am "Turn the porch light on at sunset"
```

Renaming entities, assigning areas and labels, and editing dashboards from files work the same way, with
`apply` in place of `deploy`: see [Make and validate changes](docs/edit.md).

## Is it for you?

- Your Home Assistant configuration is in git, or you want it to be.
- `deploy` needs ssh into the instance, as on Home Assistant OS or Supervised with an SSH add-on. Everything
  else needs only the URL and a token, so it works with any install.
- hass-ops does not write automations or generate configuration. It checks, deploys and tracks yours.

## Install

```shell
uv tool install git+https://github.com/gnagy/hass-ops
```

Needs [uv](https://docs.astral.sh/uv/), which fetches Python 3.12 or later itself if you don't have it. If
you manage tools with [mise](https://mise.jdx.dev), it can install both uv and hass-ops for you. [Install](docs/install.md)
has the details, including exactly what gets installed where. Then [set up your configuration
repository](docs/setup.md).

## Documentation

| When                     | Read                                                                         | Covers                                                        |
|--------------------------|------------------------------------------------------------------------------|---------------------------------------------------------------|
| Deciding whether it fits | [Architecture](docs/architecture.md)                                         | what moves where and why, the registries, the safeguards      |
| Once per machine         | [Install](docs/install.md)                                                   | uv or mise, and exactly what goes where                       |
| Once per instance        | [Set up your configuration repository](docs/setup.md)                        | the first import of an existing instance                      |
| Start of every session   | [Bring in changes made on the instance](docs/sync.md)                        | `drift`, `pull`, `promote`, and YAML edited on the instance   |
| Making a change          | [Make and validate changes](docs/edit.md)                                    | editing YAML and `desired/`, `check`, planning with `apply`   |
| Sending it               | [Deploy and verify](docs/deploy.md)                                          | `deploy`, `reload`, `apply --write`, verifying and undoing    |
| Everything else          | [Other operations](docs/operations.md)                                       | a test instance, scripts and MCP servers, HACS checks, tokens |
| Reference                | [File formats](docs/file-formats.md), [Configuration](docs/configuration.md) | `exports/` and `desired/`; every setting in `hass-ops.toml`   |

## Status

Early. Extracted in September 2026 from one house's configuration, where it had been in use since August, and
developed against Home Assistant 2026.8 and 2026.9. Command names and file formats may still change. The
registry and dashboard commands use WebSocket messages Home Assistant does not promise to keep stable between
releases.

## Develop

```shell
uv run pytest
```

## License

[Apache-2.0](LICENSE).
