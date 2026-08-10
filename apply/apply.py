#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["pyyaml>=6", "websockets>=13"]
# ///
"""Reconcile the instance toward `desired/`. The only tool here that writes.

Reads `desired/`, never `exports/`. `exports/` is what the instance has;
promoting a line out of it into `desired/` is a deliberate, reviewed human act,
and wiring apply to read it directly would erase that distinction.

Four properties, each load-bearing because there is no staging instance:

  Dry run by default.  Writing needs `--write`. The dry run and the write walk
  the same planned list of changes, so what you read is what executes — not a
  separate rendering that can drift from the real thing.

  Sparse, at both levels.  An entity absent from entity-map.yaml is left alone;
  a field absent from an entry is left alone. Declaring 3 entities out of 896
  changes 3, not 896. An explicit `null` is how you clear a value, which is
  what makes "unmanaged" and "should be empty" different things.

  Validate everything, then write.  All references are resolved before the
  first write goes out. A typo'd area fails the whole run with nothing sent,
  rather than half-applying and leaving the house in a state no file describes.

  Idempotent.  Only differences become changes. A second run plans nothing.

What it deliberately will not do: create or delete dashboards, remove entities
from the registry, or touch anything not named in `desired/`. Destructive
registry operations belong behind a flag nobody has needed yet.
"""

from __future__ import annotations

import argparse
import difflib
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ha_api import HaApiError  # noqa: E402
from ha_ws import HaWs  # noqa: E402

log = logging.getLogger("apply")

CONFIG_ROOT = Path(__file__).resolve().parent.parent.parent
DESIRED_ROOT = CONFIG_ROOT / "desired"
ENTITY_MAP = DESIRED_ROOT / "entity-map.yaml"
DESIRED_DASHBOARDS = DESIRED_ROOT / "dashboards"

# How a desired entity entry maps onto config/entity_registry/update. The
# registry field is on the left of each pair because the desired file uses the
# shorter names from the repo's own entity-map format.
ENTITY_SIMPLE_FIELDS = (
    # (desired key, registry key)
    ("name", "name"),
    ("icon", "icon"),
)

MAX_DIFF_LINES = 40


@dataclass
class Change:
    """One planned WebSocket write.

    Planning and executing share this, so `--write` cannot do anything the dry
    run did not print.
    """

    summary: str
    command: str
    payload: dict
    details: tuple[str, ...] = ()
    # Set for creates whose resulting id Home Assistant chooses itself.
    verify: Any = field(default=None)


def load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise HaApiError(f"{path.relative_to(CONFIG_ROOT)}: {str(exc).splitlines()[0]}") from exc


def describe(before: Any, after: Any) -> str:
    return f"{before!r} -> {after!r}"


# --- registry --------------------------------------------------------------


def plan_registry(ws: HaWs, errors: list[str]) -> list[Change]:
    if not ENTITY_MAP.exists():
        print(f"  registry: no {ENTITY_MAP.relative_to(CONFIG_ROOT)}, nothing declared")
        return []

    desired = load_yaml(ENTITY_MAP) or {}
    if not isinstance(desired, dict):
        errors.append(f"{ENTITY_MAP.name}: expected a mapping at the top level")
        return []

    live_floors = {f["floor_id"]: f for f in ws.command("config/floor_registry/list")}
    live_areas = {a["area_id"]: a for a in ws.command("config/area_registry/list")}
    live_labels = {lbl["label_id"]: lbl for lbl in ws.command("config/label_registry/list")}
    live_entities = ws.command("config/entity_registry/list")

    changes: list[Change] = []

    # Registries first: an entity cannot be put in an area that does not exist
    # yet, so these have to be planned (and applied) ahead of the entities that
    # reference them.
    changes += plan_simple_registry(
        desired.get("floors") or [],
        live_floors,
        key="floor_id",
        fields=("name", "level", "icon", "aliases"),
        create_command="config/floor_registry/create",
        update_command="config/floor_registry/update",
        kind="floor",
        errors=errors,
    )
    changes += plan_simple_registry(
        desired.get("areas") or [],
        live_areas,
        key="area_id",
        fields=("name", "floor_id", "icon", "aliases"),
        create_command="config/area_registry/create",
        update_command="config/area_registry/update",
        kind="area",
        errors=errors,
    )
    changes += plan_simple_registry(
        desired.get("labels") or [],
        live_labels,
        key="label_id",
        fields=("name", "icon", "color", "description"),
        create_command="config/label_registry/create",
        update_command="config/label_registry/update",
        kind="label",
        errors=errors,
    )

    declared_areas = {a["area_id"] for a in desired.get("areas") or [] if a.get("area_id")}
    declared_labels = {l["label_id"] for l in desired.get("labels") or [] if l.get("label_id")}

    changes += plan_entities(
        desired.get("entities") or [],
        live_entities,
        known_areas=set(live_areas) | declared_areas,
        known_labels=set(live_labels) | declared_labels,
        errors=errors,
    )
    return changes


def plan_simple_registry(
    entries: list,
    live: dict,
    *,
    key: str,
    fields: tuple[str, ...],
    create_command: str,
    update_command: str,
    kind: str,
    errors: list[str],
) -> list[Change]:
    changes: list[Change] = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get(key):
            errors.append(f"{kind}: every entry needs a {key}")
            continue
        identifier = entry[key]
        current = live.get(identifier)

        if current is None:
            if not entry.get("name"):
                errors.append(f"{kind} {identifier}: needs a name to be created")
                continue
            payload = {f: entry[f] for f in fields if f in entry}
            changes.append(
                Change(
                    summary=f"CREATE {kind} {identifier}",
                    command=create_command,
                    payload=payload,
                    details=tuple(f"{f}: {payload[f]!r}" for f in sorted(payload)),
                    # Home Assistant derives the id from the name on create and
                    # never lets the caller choose it. If it lands on something
                    # other than what the file declares, every entity
                    # referencing it silently refers to nothing.
                    verify=(kind, key, identifier, entry["name"]),
                )
            )
            continue

        differences = {
            f: entry[f] for f in fields if f in entry and entry[f] != current.get(f)
        }
        if differences:
            changes.append(
                Change(
                    summary=f"UPDATE {kind} {identifier}",
                    command=update_command,
                    payload={key: identifier, **differences},
                    details=tuple(
                        f"{f}: {describe(current.get(f), differences[f])}"
                        for f in sorted(differences)
                    ),
                )
            )
    return changes


def plan_entities(
    entries: list,
    live_entities: list[dict],
    *,
    known_areas: set[str],
    known_labels: set[str],
    errors: list[str],
) -> list[Change]:
    by_unique_id: dict[str, list[dict]] = {}
    for entity in live_entities:
        by_unique_id.setdefault(entity.get("unique_id"), []).append(entity)

    changes: list[Change] = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("unique_id"):
            errors.append("entities: every entry needs a unique_id")
            continue

        unique_id = str(entry["unique_id"])
        matches = by_unique_id.get(unique_id, [])
        if platform := entry.get("platform"):
            matches = [m for m in matches if m.get("platform") == platform]

        if not matches:
            errors.append(
                f"unique_id {unique_id!r}: no such entity in the registry. "
                "unique_id is the integration's identifier, not the entity_id."
            )
            continue
        if len(matches) > 1:
            found = ", ".join(f"{m['entity_id']} (platform={m['platform']})" for m in matches)
            errors.append(
                f"unique_id {unique_id!r} matches {len(matches)} entities: {found}. "
                "Add `platform:` to the entry to disambiguate."
            )
            continue

        current = matches[0]
        payload: dict[str, Any] = {"entity_id": current["entity_id"]}
        details: list[str] = []

        if (desired_id := entry.get("entity_id")) and desired_id != current["entity_id"]:
            current_domain = current["entity_id"].split(".", 1)[0]
            if desired_id.split(".", 1)[0] != current_domain:
                errors.append(
                    f"{current['entity_id']}: cannot become {desired_id} — an entity "
                    f"cannot change domain."
                )
                continue
            payload["new_entity_id"] = desired_id
            details.append(f"entity_id: {describe(current['entity_id'], desired_id)}")

        for desired_key, registry_key in ENTITY_SIMPLE_FIELDS:
            if desired_key in entry and entry[desired_key] != current.get(registry_key):
                payload[registry_key] = entry[desired_key]
                details.append(f"{registry_key}: {describe(current.get(registry_key), entry[desired_key])}")

        if "area" in entry:
            area = entry["area"]
            if area is not None and area not in known_areas:
                errors.append(
                    f"{current['entity_id']}: area {area!r} does not exist and is not "
                    f"declared under `areas:`."
                )
            elif area != current.get("area_id"):
                payload["area_id"] = area
                details.append(f"area_id: {describe(current.get('area_id'), area)}")

        if "labels" in entry:
            desired_labels = sorted(entry["labels"] or [])
            unknown = [l for l in desired_labels if l not in known_labels]
            if unknown:
                errors.append(
                    f"{current['entity_id']}: labels {unknown} do not exist and are not "
                    f"declared under `labels:`."
                )
            elif desired_labels != sorted(current.get("labels") or []):
                payload["labels"] = desired_labels
                details.append(f"labels: {describe(sorted(current.get('labels') or []), desired_labels)}")

        # `hidden: true` and `hidden: false` both mean something; absent means
        # "not managed here".
        for desired_key, registry_key in (("hidden", "hidden_by"), ("disabled", "disabled_by")):
            if desired_key not in entry:
                continue
            target = "user" if entry[desired_key] else None
            if target != current.get(registry_key):
                payload[registry_key] = target
                details.append(f"{registry_key}: {describe(current.get(registry_key), target)}")

        if len(payload) > 1:
            changes.append(
                Change(
                    summary=f"UPDATE entity {current['entity_id']}  (unique_id {unique_id})",
                    command="config/entity_registry/update",
                    payload=payload,
                    details=tuple(details),
                )
            )
    return changes


# --- dashboards ------------------------------------------------------------


def plan_dashboards(ws: HaWs, errors: list[str]) -> list[Change]:
    if not DESIRED_DASHBOARDS.is_dir():
        return []
    files = sorted(DESIRED_DASHBOARDS.glob("*.yaml"))
    if not files:
        print(f"  dashboards: nothing in {DESIRED_DASHBOARDS.relative_to(CONFIG_ROOT)}/")
        return []

    live = {b["id"]: b for b in ws.command("lovelace/dashboards/list")}
    changes: list[Change] = []

    for path in files:
        document = load_yaml(path) or {}
        meta = document.get("dashboard") or {}
        config = document.get("config")
        dashboard_id = meta.get("id") or path.stem

        if config is None:
            errors.append(f"{path.name}: no `config:` key — nothing to apply")
            continue

        board = live.get(dashboard_id)
        if board is None:
            # Creating one is possible, but it is a different act from
            # reconciling an existing dashboard and should be deliberate.
            errors.append(
                f"{path.name}: no dashboard {dashboard_id!r} on the instance. "
                "apply does not create dashboards; make it in the UI first."
            )
            continue
        if board.get("mode") != "storage":
            errors.append(
                f"{path.name}: dashboard {dashboard_id!r} is mode={board.get('mode')!r}, "
                "not storage. Writing it would fight whatever owns the YAML."
            )
            continue

        url_path = board.get("url_path")
        current = ws.try_command("lovelace/config", url_path=url_path, force=False)
        if current == config:
            continue

        changes.append(
            Change(
                summary=f"SAVE dashboard {dashboard_id} ({url_path})",
                command="lovelace/config/save",
                payload={"url_path": url_path, "config": config},
                details=tuple(yaml_diff(current, config)),
            )
        )
    return changes


def yaml_diff(before: Any, after: Any) -> list[str]:
    rendered = [
        yaml.safe_dump(value or {}, sort_keys=True, allow_unicode=True, default_flow_style=False)
        .splitlines()
        for value in (before, after)
    ]
    lines = list(difflib.unified_diff(rendered[0], rendered[1], "instance", "desired", lineterm="", n=1))
    if len(lines) > MAX_DIFF_LINES:
        hidden = len(lines) - MAX_DIFF_LINES
        lines = lines[:MAX_DIFF_LINES] + [f"... {hidden} more diff lines"]
    return lines


# --- driver ----------------------------------------------------------------


def execute(ws: HaWs, changes: list[Change]) -> None:
    for change in changes:
        log.info(
            "WRITE instance=%s command=%s target=%s",
            ws.instance,
            change.command,
            change.summary,
        )
        ws.command(change.command, **change.payload)

        if change.verify:
            kind, key, declared, name = change.verify
            listing = ws.command(f"config/{kind}_registry/list")
            actual = next((r[key] for r in listing if r.get("name") == name), None)
            if actual != declared:
                print(
                    f"  !! {kind} was created as {key}={actual!r}, but the file declares "
                    f"{declared!r}. Home Assistant derives the id from the name and does not "
                    f"accept one. Update desired/entity-map.yaml to {actual!r}."
                )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "targets",
        nargs="*",
        choices=["registry", "dashboards", []],
        help="limit to registry or dashboards; default is both",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="actually apply. Without this nothing is sent to the instance",
    )
    args = parser.parse_args()
    targets = args.targets or ["registry", "dashboards"]

    # Both the plan and the per-write log must land on one stream. Logging to
    # stderr while printing the plan to stdout reorders them under any kind of
    # capture, so a saved log shows writes happening above the plan that
    # produced them — which reads like the tool wrote before it was told to.
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

    try:
        with HaWs() as ws:
            print(f"instance={ws.instance}  targets={', '.join(targets)}  "
                  f"mode={'WRITE' if args.write else 'dry run'}")

            errors: list[str] = []
            changes: list[Change] = []
            if "registry" in targets:
                changes += plan_registry(ws, errors)
            if "dashboards" in targets:
                changes += plan_dashboards(ws, errors)

            if errors:
                print(f"\n{len(errors)} problem(s) — nothing was written:")
                for message in errors:
                    print(f"  ERROR {message}")
                return 1

            if not changes:
                print("\nnothing to do: the instance already matches desired/")
                return 0

            print(f"\n{len(changes)} change(s):\n")
            for change in changes:
                print(f"  {change.summary}")
                for detail in change.details:
                    print(f"      {detail}")
                print()

            if not args.write:
                print("dry run — nothing sent. Re-run with --write to apply.")
                return 0

            sys.stdout.flush()
            execute(ws, changes)
            print(f"\napplied {len(changes)} change(s) to {ws.instance}")
            print("Run `mise run pull` to refresh exports/ so drift stays clean.")

    except HaApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
