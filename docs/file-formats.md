# File formats

## exports

Written by `pull`; never edit these files, but commit them. They are what `drift` compares against.

`pull` writes one directory per instance, `exports/<instance>/`:

| File                   | Contents                                                                                 |
|------------------------|------------------------------------------------------------------------------------------|
| `registry.yaml`        | entities, devices, areas, floors and labels                                              |
| `config_entries.yaml`  | each integration entry's domain and title, nothing else                                  |
| `hacs.yaml`            | installed HACS repositories and their installed versions, when HACS is present           |
| `dashboards/<id>.yaml` | each storage-mode dashboard: its metadata under `dashboard:`, its config under `config:` |

Three rules make the output worth diffing:

- **Sorted on stable keys**: `unique_id` for entities, the registry id for everything else. Never a display
  name, which would reorder the file on every rename.
- **Named fields only.** Each exporter lists the fields it keeps, and drops everything else. Config entries in
  particular hold integration credentials, so only `domain` and `title` are kept.
- **Nothing that changes on its own**: no timestamps, no firmware versions, no HACS `available_version`.
  Two pulls of an unchanged instance write identical files.

YAML-mode dashboards are skipped: Home Assistant resolves `!secret` when it loads one, so an export could
contain the secrets. A dashboard deleted on the instance has its export removed, so `drift` shows deletions.

## desired

Written by you, or started by `promote`. `apply` reads only these.

### desired/entity-map.yaml

A sparse description of the registries. [`examples/desired/entity-map.yaml`](../examples/desired/entity-map.yaml)
is a commented example.

```yaml
floors:
  - floor_id: ground_floor
    name: Ground Floor
    level: 0

areas:
  - area_id: porch
    name: Porch
    floor_id: ground_floor

labels:
  - label_id: security
    name: Security
    color: red

devices:
  - identifier: "0x00158d0001a2b3c4"
    name: Porch motion sensor
    area: porch

entities:
  - unique_id: "0x00158d0001a2b3c4-occupancy"
    entity_id: binary_sensor.porch_motion
    name: Porch motion
    area: porch
    labels: [security]
    icon: null                  # clear it
```

**Absent and `null` mean different things.** A field that is absent is not managed: `apply` leaves it as it
is. A field set to `null` is managed and should be empty: `apply` clears it. The same holds for entries: an
entity that is not listed is not managed.

The sections are applied in this order: floors, areas, labels, devices, entities. An entity can therefore refer
to an area declared in the same file that the instance does not have yet.

#### floors, areas, labels

Each entry is keyed on its id (`floor_id`, `area_id`, `label_id`). When the instance has that id, the fields
given are updated; when it doesn't, it is created, and `name` is required.

| Section  | Fields                                 |
|----------|----------------------------------------|
| `floors` | `name`, `level`, `icon`, `aliases`     |
| `areas`  | `name`, `floor_id`, `icon`, `aliases`  |
| `labels` | `name`, `icon`, `color`, `description` |

Home Assistant does not let the caller choose the id of a new floor, area or label: it derives one from the
name. `apply` reads back the id it got and reports a mismatch. If that happens, correct the id in the file, or
anything referring to it points at nothing.

#### devices

Keyed on `identifier`: the value part of one of the device's identifiers, as listed under `identifiers:` in
`exports/<instance>/registry.yaml`. An identifier is the integration's own name for the device and is the same
on every instance; the `device_id` is not. It must match exactly one device.

| Field    | Sets                                                                                    |
|----------|-----------------------------------------------------------------------------------------|
| `name`   | the name you give the device (`name_by_user`); the integration's own name is left alone |
| `area`   | the device's area, an `area_id`                                                         |
| `labels` | the device's labels, a list of `label_id`s                                              |

#### entities

Keyed on `unique_id`: the integration's identifier for the entity, which survives renames and is the same on
every instance. It is not the `entity_id`. Find it in `exports/<instance>/registry.yaml`.

| Field       | Sets                                                                            |
|-------------|---------------------------------------------------------------------------------|
| `platform`  | not a setting: narrows the match when two integrations use the same `unique_id` |
| `entity_id` | renames the entity. The domain cannot change                                    |
| `name`      | the entity's name                                                               |
| `icon`      | its icon                                                                        |
| `area`      | its area, an `area_id`                                                          |
| `labels`    | its labels, a list of `label_id`s                                               |
| `hidden`    | `true` hides it, `false` unhides it                                             |
| `disabled`  | `true` disables it, `false` enables it                                          |

When a `unique_id` matches more than one entity, `apply` stops and asks for `platform`. `promote` adds it for
you when it sees the ambiguity.

### desired/dashboards/

One file per dashboard, in the shape `pull` writes:

```yaml
dashboard:
  id: energy          # optional; defaults to the file name
config:
  views:
    - title: Energy
      cards: []
```

`apply` saves `config` to the dashboard with that id. The dashboard must already exist and be in storage
mode: create it in the UI first. `apply` never overwrites a YAML-mode dashboard, since its YAML file owns it.
