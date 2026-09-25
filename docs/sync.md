# Bring in changes made on the instance

Your repository is not the only thing that changes Home Assistant. Every edit made on the instance itself
drifts it away from the repository, and the next deploy or `apply` can undo it. Start a session here: find
out what changed on the instance, then keep it or reject it, before you edit anything.

Changes on the instance come in two kinds, and hass-ops sees them differently:

| Changed on the instance                                                                          | Lands in                | How you see it              |
|--------------------------------------------------------------------------------------------------|-------------------------|-----------------------------|
| Entity names, areas, labels, floors, device names, UI dashboards, integrations, HACS installs    | `.storage`              | `hass-ops drift`            |
| Automations, scripts and scenes edited in the UI; the File editor add-on; ESPHome Device Builder | YAML files in `/config` | `hass-ops deploy --dry-run` |

The second row surprises people: the UI's automation, script and scene editors write to `automations.yaml`,
`scripts.yaml` and `scenes.yaml` in `/config`, the same files your repository deploys.

## Registries and dashboards: drift

```shell
hass-ops drift
```

`drift` runs `pull`, then `git diff --stat --exit-code` on `exports/`: it lists which export files changed
since your last commit, not what changed in them, and exits non-zero if any did. It is the same as running
`hass-ops pull` yourself and looking with git, which is what the routine below does. The pulled files stay
in your working tree, like any other change. Read them with `git diff exports/`, and for each change decide:

- **Keep it.** Commit the export. If it is something you manage in `desired/`, also `promote` it, or the next
  `apply` puts it back.
- **Reject it.** If it is managed in `desired/`, `hass-ops apply` plans it back, and `apply --write` restores it.
  If it isn't managed, change it back in the UI, or add it to `desired/` first.

A change `drift` misses: a new dashboard, which appears as a new, untracked file in `exports/`. Check
`git status exports/` as well.

### pull

```shell
hass-ops pull                          # everything
hass-ops pull registry dashboards      # some of it: registry, config_entries, hacs, dashboards
```

Read-only on the instance. Writes normalised YAML into `exports/<instance>/`: the registries, integrations
(domain and title only), installed HACS repositories, and each UI dashboard.
[file-formats.md](file-formats.md#exports) describes the files. Two pulls of an unchanged instance produce
identical files, so any difference is a real change.

### promote

```shell
hass-ops promote entity light.porch sensor.outdoor_temperature      # dry run: shows the diff
hass-ops promote entity light.porch --write
hass-ops promote dashboard energy --write
hass-ops promote dashboard all
```

Adopts what the instance has as what you want: it copies from `exports/` into `desired/`, showing the diff,
and writes nothing without `--write`. It copies from the last pull, not from the instance, so `pull` first if
the UI changed since. It never connects to Home Assistant.

- **An entity** becomes an entry in `desired/entity-map.yaml`, holding only the fields the registry actually
  has set. An existing entry for the same `unique_id` is updated in place, keeping keys the registry does not
  carry, such as `hidden`. Comments in the file survive.
- **A dashboard** is copied to `desired/dashboards/<id>.yaml` as it is.

Afterwards `hass-ops apply` should plan nothing; if it plans something, the promotion did not capture the
instance faithfully.

## YAML files: fetch them back

hass-ops has no command for this yet. A deploy would overwrite a YAML file changed on the instance, so look
before you deploy:

```shell
hass-ops deploy --dry-run
```

Any file it would send that you did not change was changed on the instance. To bring those changes into the
repository, copy from the instance, then review:

```shell
rsync -av --exclude-from=.rsyncignore <ssh-host>:/config/ ha-config/
git diff ha-config/
```

Commit what you want to keep and `git checkout` the rest; the next deploy puts the repository's version back.
This copy never deletes: a file deleted on the instance stays in the repository, and the dry run lists it as
a file to send.

Do this before editing, not after: rsync overwrites your uncommitted local edits to the same files.

## A routine

At the start of a session:

```shell
hass-ops pull
git status exports/          # new or deleted export files, e.g. a dashboard
git diff exports/            # what changed in the ones you have
hass-ops deploy --dry-run
```

When these show nothing unexpected, the repository matches the instance and you can [make
changes](edit.md).
