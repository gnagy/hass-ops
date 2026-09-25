# Make and validate changes

Changes are made in the repository and checked there, before anything reaches the instance. Start from a
repository that matches the instance: [bring in changes made on the instance](sync.md) first.

There are two places to edit, matching the two kinds of state:

- **`ha-config/`**, the YAML Home Assistant reads: `configuration.yaml`, `automations.yaml`, `packages/`, and
  the rest of `/config`. [Deployed](deploy.md#deploy) with `deploy`.
- **`desired/`**, the state Home Assistant keeps in its registries and UI dashboards: entity names and ids,
  areas, labels, floors, device names. [Applied](deploy.md#apply) with `apply`.

## Edit the YAML

Edit files in `ha-config/` as you would in `/config`. Keep credentials in `secrets.yaml` and refer to them with
`!secret`; `secrets.yaml` is not in git, so it is edited on the instance, or deployed from a copy you keep
elsewhere.

### check

```shell
hass-ops check
hass-ops check --strict      # also fail on entities that are unavailable or unknown
hass-ops check --esphome     # also look for entity references in esphome/
```

Parses every YAML file in `ha-config/`, then looks up each `entity_id` the files mention on the live
instance. It changes nothing.

A misspelled `entity_id` is valid YAML, and `ha core check` accepts it. The automation deploys, reloads, and
never runs. `check` reports three kinds of problem:

| Finding | Meaning                                         | Fails the check      |
|---------|-------------------------------------------------|----------------------|
| PARSE   | the file is not valid YAML                      | yes                  |
| MISSING | referenced, but no such entity exists           | yes                  |
| DEAD    | exists, but its state is unavailable or unknown | only with `--strict` |

Home Assistant tags such as `!secret` and `!include` are accepted. Commented-out lines are ignored, since the
files are parsed rather than searched. Service names like `light.turn_on` look exactly like entity ids and are
not reported.

ESPHome device files are always parsed, because nothing else checks their syntax before they reach the
instance. Looking for entity references in them is optional (`--esphome`), since they use a different schema
and mostly produce noise.

`check` does not validate Home Assistant's schema; `deploy` runs `ha core check` on the instance for that.

## Declare names, areas, labels and dashboards

`desired/entity-map.yaml` lists the registry state you want to manage, and `desired/dashboards/` holds UI
dashboards. Both are **sparse**: only what they name is managed. An entity you don't list is left alone, and
so is a field you leave out. `null` clears a value.

```yaml
entities:
  - unique_id: "0x00158d0001a2b3c4-occupancy"   # the integration's id for the entity, from exports/
    entity_id: binary_sensor.porch_motion        # rename it
    name: Porch motion
    area: porch
    labels: [security]
```

The easiest start is `hass-ops promote`, which writes an entry from what the instance has now; edit it from
there. [file-formats.md](file-formats.md#desired) describes every section and field.

Renaming an `entity_id` breaks every automation, script and dashboard that uses the old one. Change those
references in `ha-config/` in the same commit, and deploy both together. Until the rename is applied, `check` reports
the new id as MISSING; that is expected, and `deploy` runs `check` again after `apply --write` has made it real.

### Plan the change

```shell
hass-ops apply                          # registry and dashboards
hass-ops apply registry                 # or just one of them
```

Without `--write`, `apply` is a dry run: it reads the instance, validates `desired/`, and prints the plan. Every
area, label, device and `unique_id` is resolved first; a typo fails the plan with an error, not a half-applied
change.

For a one-off set of changes that should not stay in `desired/`, such as a batch of renames, put them in a
separate file and plan it with `--entity-map one-off.yaml`.

## Before you deploy

```shell
hass-ops check                 # the YAML is valid and every entity it names exists
hass-ops deploy --dry-run      # exactly the files you meant to change, and no deletions
hass-ops apply                 # exactly the registry changes you meant
```

Then [deploy](deploy.md).
