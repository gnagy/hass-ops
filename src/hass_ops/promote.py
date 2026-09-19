"""Adopt what the instance has as what we intended: exports/ -> desired/.

The missing step between [pull] and [apply]. You change something in the UI,
`drift` reports it, you decide you meant it — and until now the only way to say
so was `cp exports/prod/dashboards/x.yaml desired/dashboards/x.yaml`, which
shows you nothing about what you just adopted.

Promote is the reviewed version of that copy. It prints the diff it would make
to `desired/` and writes nothing without `--write`.

It reads `exports/`, so it adopts **what the last pull recorded**, not what the
instance has this second. Run `hass-ops pull` first if the UI has changed since.

This is the only tool here that never connects to Home Assistant. It is a local
file operation on two directories, both in git, and that is the whole of it.

Two directions it deliberately does not go: it never writes to `exports/` (the
pull owns that), and it never reads `desired/` into `exports/`.
"""

from __future__ import annotations

import argparse
import difflib
import io
import os
import sys
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from hass_ops.project import current

CONFIG_ROOT = current().root
EXPORTS_ROOT = current().exports
DESIRED_ROOT = current().desired
ENTITY_MAP = DESIRED_ROOT / "entity-map.yaml"

DESIRED_HEADER = (
    "# Promoted from {source}.\n"
    "# This is desired state, not a generated file — hand-edit it freely.\n"
)

# Fields carried from the registry into an entity-map entry. Sparse on purpose:
# a field the instance has not set is left out entirely rather than written as
# null, because null means "clear this" to apply and absent means "not managed".
ENTITY_PROMOTE_FIELDS = (
    # (entity-map key, registry key)
    ("entity_id", "entity_id"),
    ("name", "name"),
    ("icon", "icon"),
    ("area", "area_id"),
    ("labels", "labels"),
)


def round_trip_yaml() -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=2, offset=0)
    yaml.width = 100
    return yaml


def instance_name() -> str:
    """Resolve the instance without needing a token — promote never connects."""
    instance = os.environ.get("HA_INSTANCE")
    if not instance:
        raise SystemExit("error: HA_INSTANCE is not set. Run through the `hass-ops` command.")
    return instance


def strip_generated_header(text: str) -> str:
    """Drop the pull's 'never hand-edit' banner.

    It is true of `exports/` and false of `desired/`, and carrying it across
    would tell the next reader the opposite of what the file now is.
    """
    lines = text.splitlines(keepends=True)
    index = 0
    while index < len(lines) and lines[index].lstrip().startswith("#"):
        index += 1
    return "".join(lines[index:])


def show_diff(path: Path, new_text: str) -> bool:
    """Print a unified diff against the current file. True if anything differs."""
    old_text = path.read_text() if path.exists() else ""
    if old_text == new_text:
        return False

    label = path.relative_to(CONFIG_ROOT)
    diff = difflib.unified_diff(
        old_text.splitlines(),
        new_text.splitlines(),
        f"{label} (current)" if old_text else "(new file)",
        f"{label} (promoted)",
        lineterm="",
        n=2,
    )
    for line in diff:
        print(f"    {line}")
    return True


# --- dashboards ------------------------------------------------------------


def promote_dashboards(names: list[str], instance: str, write: bool) -> int:
    source_dir = EXPORTS_ROOT / instance / "dashboards"
    if not source_dir.is_dir():
        raise SystemExit(f"error: {source_dir.relative_to(CONFIG_ROOT)} does not exist. Run `hass-ops pull`.")

    available = sorted(p.stem for p in source_dir.glob("*.yaml"))
    if names == ["all"]:
        names = available

    unknown = [n for n in names if n not in available]
    if unknown:
        raise SystemExit(
            f"error: no export for {', '.join(unknown)}. Available: {', '.join(available) or '(none)'}"
        )

    changed = 0
    for name in names:
        source = source_dir / f"{name}.yaml"
        destination = DESIRED_ROOT / "dashboards" / f"{name}.yaml"

        # Copy the body verbatim rather than re-serialising it. A re-dump would
        # be at the mercy of dumper settings matching the pull's exactly, and a
        # formatting-only diff here would look like a real change.
        body = strip_generated_header(source.read_text())
        header = DESIRED_HEADER.format(source=source.relative_to(CONFIG_ROOT))
        new_text = header + body

        print(f"  dashboard {name}")
        if not show_diff(destination, new_text):
            print("    unchanged")
            continue
        changed += 1
        if write:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(new_text)
    return changed


# --- entities --------------------------------------------------------------


def load_registry_entities(instance: str) -> list[dict]:
    path = EXPORTS_ROOT / instance / "registry.yaml"
    if not path.exists():
        raise SystemExit(f"error: {path.relative_to(CONFIG_ROOT)} does not exist. Run `hass-ops pull`.")
    data = round_trip_yaml().load(path.read_text()) or {}
    return list(data.get("entities") or [])


def build_entry(record: dict, ambiguous: bool) -> CommentedMap:
    entry = CommentedMap()
    entry["unique_id"] = str(record.get("unique_id"))
    for desired_key, registry_key in ENTITY_PROMOTE_FIELDS:
        value = record.get(registry_key)
        if value in (None, "", [], {}):
            continue
        entry[desired_key] = list(value) if isinstance(value, list) else value
    if ambiguous:
        # apply refuses a unique_id that matches several entities, so pin the
        # platform now rather than making the next person debug it.
        entry["platform"] = record.get("platform")
    return entry


def promote_entities(entity_ids: list[str], instance: str, write: bool) -> int:
    records = load_registry_entities(instance)
    by_entity_id = {r.get("entity_id"): r for r in records}

    unique_id_counts: dict[str, int] = {}
    for record in records:
        key = str(record.get("unique_id"))
        unique_id_counts[key] = unique_id_counts.get(key, 0) + 1

    missing = [e for e in entity_ids if e not in by_entity_id]
    if missing:
        raise SystemExit(
            f"error: not in {instance} registry export: {', '.join(missing)}. "
            "Check the entity_id, or run `hass-ops pull` if it is new."
        )

    yaml = round_trip_yaml()
    document = yaml.load(ENTITY_MAP.read_text()) if ENTITY_MAP.exists() else CommentedMap()
    if document is None:
        document = CommentedMap()

    entities = document.get("entities")
    if not entities:
        # `entities: []` round-trips as an empty flow sequence; appending to it
        # would produce a one-line inline list. Replace it with a block one.
        entities = CommentedSeq()
        entities.fa.set_block_style()
        document["entities"] = entities

    existing_by_unique_id = {
        str(item.get("unique_id")): index
        for index, item in enumerate(entities)
        if isinstance(item, dict)
    }

    for entity_id in entity_ids:
        record = by_entity_id[entity_id]
        unique_id = str(record.get("unique_id"))
        entry = build_entry(record, ambiguous=unique_id_counts.get(unique_id, 0) > 1)

        if (index := existing_by_unique_id.get(unique_id)) is not None:
            # Update in place: preserve any key the file has that the registry
            # does not carry, such as `hidden` or a deliberate `null`.
            target = entities[index]
            for key, value in entry.items():
                target[key] = value
        else:
            entities.append(entry)

    buffer = io.StringIO()
    yaml.dump(document, buffer)
    new_text = buffer.getvalue()

    print(f"  {ENTITY_MAP.relative_to(CONFIG_ROOT)}")
    if not show_diff(ENTITY_MAP, new_text):
        print("    unchanged")
        return 0
    if write:
        ENTITY_MAP.write_text(new_text)
    return 1


# --- driver ----------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("kind", choices=["dashboard", "entity"])
    parser.add_argument(
        "names",
        nargs="+",
        metavar="NAME",
        help="dashboard ids (or `all`), or entity_ids",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="actually update desired/. Without this nothing is written",
    )
    args = parser.parse_args()

    instance = instance_name()
    print(
        f"instance={instance}  promoting {args.kind}  "
        f"mode={'WRITE' if args.write else 'dry run'}"
    )
    print(f"source: exports/{instance}/ — what the last `pull` recorded\n")

    if args.kind == "dashboard":
        changed = promote_dashboards(args.names, instance, args.write)
    else:
        changed = promote_entities(args.names, instance, args.write)

    print()
    if not changed:
        print("nothing to promote: desired/ already matches the export")
        return 0
    if not args.write:
        print(f"dry run — {changed} file(s) would change. Re-run with --write.")
        return 0

    print(f"promoted into desired/ ({changed} file(s) changed).")
    print("Review with `git diff desired/`, then `hass-ops apply` should plan nothing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
