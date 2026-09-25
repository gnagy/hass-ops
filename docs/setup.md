# Set up your configuration repository

This takes an existing Home Assistant instance and puts its configuration into a git repository that
hass-ops works from. It reads from the instance and changes nothing on it. At the end, a deploy from the
repository would change nothing, which is how you know the copy is complete.

It assumes hass-ops is [installed](install.md).

## What you need

- **An administrator's long-lived access token.** In Home Assistant, open your profile, then the Security tab,
  and create one. Changing names, areas and labels needs admin rights.
- **An ssh login into the instance**, for copying the configuration and for `deploy`. On Home Assistant OS or
  Supervised, that is an SSH add-on with your key authorised. The session needs `rsync` and the `ha` command.
  Check with:

  ```shell
  ssh <ssh-host> 'rsync --version && ha core info'
  ```

  Without ssh (a Container or Core install), everything except `deploy` and `hacs preflight` still works;
  copy `/config` into the repository by whatever means you have.
- **A recent backup**, made in Home Assistant under Settings, System, Backups. Nothing here writes to the
  instance, but you will be deploying from this repository soon.
- **git.**

## What you will end up with

```text
my-house/
├── .gitignore
├── hass-ops.toml        which instances, and where the parts below are
├── .rsyncignore         what deploy must never touch on the instance
├── ha-config/           a copy of the instance's /config directory; deploy sends it back
├── desired/             names, areas, labels and dashboards you want; apply sends them
│   ├── entity-map.yaml
│   └── dashboards/
└── exports/             what the instance currently has; pull writes it, you commit it
    └── prod/
```

hass-ops finds `hass-ops.toml` by walking up from the working directory, so commands work anywhere inside
the repository. The directory names are the defaults; [configuration.md](configuration.md) shows how to
change them.

## 1. Create the repository

```shell
mkdir my-house && cd my-house
git init
```

Copy [`examples/.gitignore`](../examples/.gitignore) into it. It keeps `secrets.yaml`, at any depth, and Home
Assistant's runtime state out of git.

## 2. Describe the instance

Copy [`examples/hass-ops.toml`](../examples/hass-ops.toml) and set the instance's `url` and `ssh` host. The
`ssh` value is whatever you pass to `ssh`, typically a host alias from `~/.ssh/config`. Delete the `test`
instance if you don't have one.

## 3. Give it a token

Tokens never go in `hass-ops.toml`. An instance's token is the `HA_<INSTANCE>_TOKEN` environment variable
when that is set, otherwise the output of the instance's `token_command`. The command runs only for the
instance being targeted, and the token is never printed or written to a file.

On macOS, keep it in the Keychain, which is what the example file's `token_command` reads:

```shell
security add-generic-password -U -s hass-ops -a prod -w "$TOKEN"
```

Pass the token as an argument. Without one, `-w` prompts for it, and that prompt silently keeps only the first
128 characters; Home Assistant's long-lived tokens are longer, and the truncated one is rejected as invalid.

On Linux, `secret-tool`, `pass` or `op` work the same way; [configuration.md](configuration.md#tokens) has
examples. Check that it works:

```shell
hass-ops check
```

It prints the instance it targets and connects. With `ha-config/` still empty there is nothing to check yet;
that is the next step.

## 4. Write the exclude list

Copy [`examples/.rsyncignore`](../examples/.rsyncignore) to `.rsyncignore` and read it. It lists what lives
on the instance but is not configuration you track: Home Assistant's own state in `.storage`, databases,
logs, anything HACS or add-ons install.

It matters twice. Now, it decides what the copy in the next step leaves behind. Later, `deploy` deletes
anything on the instance that is neither in `ha-config/` nor listed here. Add anything else you find in
`/config` that you don't want in git: see what's there with `ssh <ssh-host> ls -la /config`.

## 5. Copy the configuration

```shell
rsync -av --exclude-from=.rsyncignore <ssh-host>:/config/ ha-config/
```

This only reads from the instance.

**Before you commit, look for credentials.** `secrets.yaml` is excluded, but other files can hold them
written out in full. ESPHome device files often carry API encryption keys, OTA passwords and fallback
hotspot passwords, and integrations configured in YAML sometimes carry API keys. A starting point:

```shell
grep -rnE '(password|passwd|api_key|token|key):' ha-config --include='*.yaml' | grep -v '!secret'
```

Move each one into `secrets.yaml` (ESPHome has its own, `esphome/secrets.yaml`) and refer to it with
`!secret`. Do it now: once a credential is in git history, removing it means rewriting that history.

Then commit:

```shell
git add -A && git commit -m "Import configuration from the instance"
```

## 6. Confirm the copy is complete

```shell
hass-ops check
hass-ops deploy --dry-run
```

`check` should parse every file. It may well find references to entities that no longer exist; those were
already broken, and are worth fixing in their own commits.

The dry run is the real test. It should plan **no transfers and no deletions**:

- A file it would **delete** is on the instance but neither copied nor excluded. Add it to `.rsyncignore`, or
  copy it into `ha-config/`.
- A file it would **send** differs between the repository and the instance, most often because you just
  replaced a credential with `!secret`. Those are the changes your first deploy will make; check each is
  intended.

Repeat until the dry run is empty, apart from changes you mean to make.

## 7. Record the rest of the state

```shell
hass-ops pull
git add exports && git commit -m "Record the instance's registries and dashboards"
```

This records entity names, areas, labels, floors, dashboards made in the UI, integrations and HACS
installs in `exports/`. From now on `hass-ops drift` tells you when any of it changes outside the repository.

`desired/` starts empty, and `apply` does nothing until you add to it. [Make and validate changes](edit.md#declare-names-areas-labels-and-dashboards) explains how.

## Next

- [Bring in changes made on the instance](sync.md): start every session here.
- [Make and validate changes](edit.md).
- [Deploy and verify](deploy.md).
- [Other operations](operations.md): a test instance, scripts and MCP servers, HACS checks.
