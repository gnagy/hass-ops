# Configuration

A hass-ops project is one Home Assistant configuration kept as code: a directory, normally a git repository,
with a `hass-ops.toml` at the top.

## Finding the project

Every command first finds `hass-ops.toml`, checking these in order:

1. `-C`/`--project <dir>` on the command line
2. the `HASS_OPS_PROJECT` environment variable, a directory or the file itself
3. the working directory and each directory above it

## hass-ops.toml

```toml
[paths]                          # relative to hass-ops.toml; these are the defaults
config = "ha-config"             # your copy of /config; deploy sends it
desired = "desired"              # names, areas, labels, dashboards you want; apply sends them
exports = "exports"              # what the instance has; pull writes it
rsyncignore = ".rsyncignore"     # deploy's exclude list

[check]
skip_dirs = ["www"]              # directories under config/ that hold no Home Assistant YAML

[instances.prod]
url = "https://homeassistant.example"
ssh = "homeassistant"            # ssh host for deploy, `ha core check` and `hacs preflight`
token_command = "security find-generic-password -s hass-ops -a prod -w"
default = true

[instances.test]
url = "https://ha-test.example"
ssh = "ha-test"

[instances.test.ha_mcp]          # optional; see [ha-mcp](#ha_mcp)
read_only = false

[ha_mcp]                         # optional; only `hass-ops ha-mcp` reads it
package = "ha-mcp==8.5.0"

[ha_mcp.env]
ENABLE_TOOL_SEARCH = true
```

### `[paths]`

All optional. Each is relative to the directory holding `hass-ops.toml`.

| Key           | Default        | What                                                                           |
|---------------|----------------|--------------------------------------------------------------------------------|
| `config`      | `ha-config`    | The directory deploy mirrors to `/config` and `check` reads                    |
| `desired`     | `desired`      | What `apply` reads: `entity-map.yaml` and `dashboards/`                        |
| `exports`     | `exports`      | Where `pull` writes, one subdirectory per instance                             |
| `rsyncignore` | `.rsyncignore` | rsync exclude patterns for `deploy`; see [The exclude list](#the-exclude-list) |

### `[check]`

| Key         | Default   | What                                                                              |
|-------------|-----------|-----------------------------------------------------------------------------------|
| `skip_dirs` | `["www"]` | Directory names under `config` that `check` skips: frontend assets, Python quirks |

`secrets.yaml` is always skipped.

### `[instances.<name>]`

One table per instance. The name is how you select it (`-i prod`) and forms the environment variable names
(`HA_PROD_TOKEN`), so use letters, digits and underscores.

| Key             | Required   | What                                                                        |
|-----------------|------------|-----------------------------------------------------------------------------|
| `url`           | yes        | The instance's base URL                                                     |
| `ssh`           | for deploy | An ssh destination, usually a host alias from `~/.ssh/config`               |
| `token_command` | no         | A shell command that prints the token; used when `HA_<NAME>_TOKEN` is unset |
| `default`       | no         | The instance used when none is named. Exactly one may be the default        |

### `[ha_mcp]`

Settings for `hass-ops ha-mcp`, which runs the [ha-mcp](https://github.com/homeassistant-ai/ha-mcp) MCP
server against the targeted instance. Leave the table out if you don't use it. ha-mcp reads all its settings
from environment variables; hass-ops builds them from this file. See
[MCP servers](operations.md#mcp-servers-ha-mcp).

| Key                                 | Required | What                                                                |
|-------------------------------------|----------|---------------------------------------------------------------------|
| `package`                           | yes      | What `uvx` runs. Pin a version: `ha-mcp==8.5.0`                     |
| `env`                               | no       | ha-mcp variables for every instance; booleans become `true`/`false` |
| `instances.<name>.ha_mcp.read_only` | no       | `READ_ONLY_MODE` for that instance. **Defaults to true**            |
| `instances.<name>.ha_mcp.env`       | no       | Variables for that instance only, overriding `[ha_mcp.env]`         |

`HOMEASSISTANT_URL`, `HOMEASSISTANT_TOKEN` and `READ_ONLY_MODE` come from the instance and may not appear in
an `env` table; the file is refused if they do. hass-ops also sets two defaults that an `env` table may
override: `HA_MCP_DISABLE_SETTINGS_UI=1` and `HA_MCP_CONFIG_DIR=~/.ha-mcp/<instance>`.

## Choosing the instance

The target is resolved once per command: `-i`/`--instance`, then `HA_INSTANCE`, then the instance marked
`default`. If none is named and the file marks no default, or several, the command stops and asks for
`--instance`.

hass-ops then publishes the choice to its own environment, which is how the commands and `deploy`'s shell
script all read the same answer:

| Variable          | Value                                                   |
|-------------------|---------------------------------------------------------|
| `HA_INSTANCE`     | the instance name                                       |
| `HA_<NAME>_URL`   | `url` from the file, replacing any value already set    |
| `HA_<NAME>_SSH`   | `ssh` from the file, when there is one                  |
| `HA_<NAME>_TOKEN` | left alone if set; otherwise the `token_command` output |

`<NAME>` is the instance name in upper case. `hass-ops exec -- <command>` runs any command with these set,
which is how a script built on `hass_ops.ha_api` or `hass_ops.ha_ws`, or another tool that reads a URL and
token from its environment, can use the same instance without its own copy of the token.

## Tokens

A token is a long-lived access token for an administrator user. It is never read from `hass-ops.toml`, never
printed, and never written to a file.

`token_command` runs through the shell, only for the instance a command targets, and its first line of output
is the token. If it fails or prints nothing, the command stops and says to set `HA_<NAME>_TOKEN` instead.
Examples:

```toml
token_command = "security find-generic-password -s hass-ops -a prod -w"   # macOS Keychain
token_command = "secret-tool lookup service hass-ops instance prod"        # libsecret
token_command = "pass show hass-ops/prod"
token_command = "op read op://Private/hass-ops-prod/credential"            # 1Password
```

## The exclude list

`deploy` runs `rsync --delete-after` from the `config` directory to `/config` on the instance. Anything on
the instance that is neither in `config` nor matched by `.rsyncignore` is deleted. The exclude list is
therefore the most important file in the project. It needs to cover:

- Runtime state Home Assistant owns: `.storage/`, the databases, logs, `secrets.yaml`, backups.
- Anything installed by something else: HACS (`custom_components/`, `www/community/`), add-ons, the ESPHome
  Device Builder's build directories.
- Blueprints Home Assistant ships and regenerates on upgrade.
- Anything else on your instance you do not track.

[`examples/.rsyncignore`](../examples/.rsyncignore) is a starting point. As a further guard, `deploy` refuses
outright if the dry run plans to delete anything under `.storage`, any `.db` file or `secrets.yaml`,
whatever the exclude list says.

Run `hass-ops deploy --dry-run` after every change to the exclude list, and read the planned deletions.
