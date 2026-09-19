# hass-ops

Operate a Home Assistant instance as code.

- **Tier 1**, the YAML Home Assistant reads: `check` parses it and verifies every `entity_id` it references
  against the live instance; `deploy` rsyncs it to `/config` after a dry run that refuses deletions of
  `.storage`, databases or secrets.
- **Tier 2**, what lives in `.storage` (entity, device, area, floor and label registries; storage-mode
  dashboards): `pull` records it as normalised YAML in `exports/`, `promote` adopts what you want to keep into
  `desired/`, `apply` reconciles the instance toward `desired/` (sparse, keyed on `unique_id`, dry run unless
  `--write`), and `drift` fails when the instance changed outside the repo.

Early: extracted in September 2026 from one house's configuration repo, where it had been growing since
August. Command names and the config file format may still change.

## Use

```shell
uv tool install -e .          # puts `hass-ops` on PATH
cd <your config repo>         # the directory holding hass-ops.toml, or below it
hass-ops pull                 # instance from --instance, HA_INSTANCE, or the file's default
hass-ops -i test apply        # plan against the test instance
hass-ops apply --write
hass-ops deploy --dry-run
hass-ops exec -- <command>   # any command with HA_INSTANCE, HA_<NAME>_URL/_SSH/_TOKEN set,
                              # e.g. a script using hass_ops.ha_ws, or docker compose for an MCP server
hass-ops --help
```

`hass-ops.toml` in the config repo names the paths and the instances; `src/hass_ops/project.py` documents
the format. Tokens never belong in the file: each instance's token is `HA_<INSTANCE>_TOKEN` when that is set,
otherwise the output of the instance's `token_command`, e.g. a macOS Keychain lookup:

```toml
[instances.prod]
url = "https://homeassistant.example"
ssh = "homeassistant"
token_command = "security find-generic-password -s hass-ops -a prod -w"
default = true
```

```shell
security add-generic-password -U -s hass-ops -a prod -w "$TOKEN"
```

Pass the token as an argument. Without one, `-w` prompts for it, and that prompt silently keeps only the first
128 characters; Home Assistant's long-lived tokens are longer, and the truncated one is rejected as invalid.

## Develop

```shell
uv run pytest
```
