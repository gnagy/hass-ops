#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["pyyaml>=6"]
# ///
"""Cross-check every entity_id in tier-1 YAML against the live instance.

An invented entity_id is valid YAML. `ha core check` validates schema and will
pass it happily; the automation then deploys, reloads, and silently never fires.
That is the failure mode this repo calls out as the common one, and this script
is the only thing that catches it.

Three tiers of finding:

  PARSE     the file is not valid YAML             -> exit 1
  MISSING   referenced but no such entity exists   -> exit 1
  DEAD      exists but is unavailable/unknown      -> exit 0, or 1 with --strict

DEAD matters as much as MISSING in practice. The upstairs hallway ran for three
months against an IKEA sensor that had dropped off the mesh: the entity_id still
resolved, so nothing anywhere complained.

PARSE covers *every* YAML under ha-config/, including the ones this script does
not scan for entity references. That split is deliberate. Nothing else in the
pipeline reads esphome/ — `ha core check` validates what HA loads, and HA does
not load device firmware definitions — so a syntax error there reaches the
instance unremarked. It has happened: an editor stole keyboard focus and typed a
bare word into the middle of a wifi: block, and the broken file deployed
cleanly. Parsing is nearly free and needs no schema knowledge, so it is
unconditional; only the noisier entity-reference scan is opt-in.

Comments are not scanned — the files are parsed as YAML, so commented-out config
does not produce findings.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ha_api import HaApi, HaApiError  # noqa: E402

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "ha-config"

# Never scanned. secrets.yaml is untracked and holds no entity refs; www/ is
# frontend assets; zha_quirks/ is Python. Stock blueprints are not tracked here
# at all (see .rsyncignore), so they need no entry.
SKIP_NAMES = {"secrets.yaml"}
SKIP_DIRS = {"www", "zha_quirks"}

# ESPHome yamls are device firmware definitions compiled by the add-on, not
# config HA reads. They use a different schema and mention HA entities only
# occasionally, so *entity-reference scanning* over them is opt-in via --esphome
# rather than a default source of noise. They are still always parsed — see the
# module docstring on why the syntax check is unconditional.
ESPHOME_DIR = "esphome"

# A candidate is only treated as an entity reference if its domain is plausible.
# Live domains alone would miss a typo in a domain that has no entities yet, so
# union them with the common built-ins.
KNOWN_DOMAINS = frozenset(
    """
    alarm_control_panel automation binary_sensor button calendar camera climate
    conversation cover date datetime device_tracker event fan group humidifier
    image input_boolean input_button input_datetime input_number input_select
    input_text lawn_mower light lock media_player notify number person remote
    scene schedule script select sensor siren stt switch text time timer todo
    tts update vacuum valve wake_word water_heater weather zone
    """.split()
)

# Suffixes that make a dotted token a filename, not an entity_id. `automation`
# and `script` are real domains, so `automations.yaml` and friends would
# otherwise look like references.
FILE_SUFFIXES = frozenset(
    "yaml yml json py md txt log db sh conf cfg ini jpg jpeg png svg gz bak xml csv".split()
)

DEAD_STATES = {"unavailable", "unknown"}

# domain.object_id, not preceded by a word char, dot or slash (excludes paths
# and the tail of a longer dotted chain), not followed by one (excludes
# `values.keys()` style attribute access on a longer chain).
ENTITY_RE = re.compile(r"(?<![\w./])([a-z][a-z0-9_]{2,})\.([a-z0-9_]+)(?![\w.])")

# The `states.sensor.foo.state` template form, which the rule above rejects.
STATES_ATTR_RE = re.compile(r"\bstates\.([a-z][a-z0-9_]{2,})\.([a-z0-9_]+)")


class HaTagLoader(yaml.SafeLoader):
    """SafeLoader that tolerates Home Assistant's YAML tags.

    !secret, !include, !include_dir_named, !input and friends are meaningless
    outside HA's loader. They resolve to a placeholder here: this script cares
    about literal entity_ids, and nothing behind those tags is one.
    """


def _placeholder(loader: yaml.Loader, tag_suffix: str, node: yaml.Node) -> str:
    return f"<{tag_suffix}>"


HaTagLoader.add_multi_constructor("!", _placeholder)


def iter_config_files() -> list[Path]:
    """Every YAML under ha-config/ worth parsing, esphome/ included."""
    files = []
    for path in sorted(CONFIG_DIR.rglob("*")):
        if path.suffix not in {".yaml", ".yml"} or not path.is_file():
            continue
        relative = path.relative_to(CONFIG_DIR)
        if path.name in SKIP_NAMES:
            continue
        if set(relative.parts[:-1]) & SKIP_DIRS:
            continue
        files.append(path)
    return files


def is_esphome(path: Path) -> bool:
    relative = path.relative_to(CONFIG_DIR)
    return bool(relative.parts) and relative.parts[0] == ESPHOME_DIR


def walk_strings(node: object):
    """Yield every string scalar in a parsed YAML document."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from walk_strings(key)
            yield from walk_strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_strings(item)


def candidates_in(text: str, domains: frozenset[str]) -> set[str]:
    found = set()
    for regex in (ENTITY_RE, STATES_ATTR_RE):
        for domain, object_id in regex.findall(text):
            if domain not in domains or object_id in FILE_SUFFIXES:
                continue
            found.add(f"{domain}.{object_id}")
    return found


def line_of(path: Path, entity_id: str) -> int:
    """First line mentioning the reference, for a clickable location."""
    try:
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if entity_id in line and not line.lstrip().startswith("#"):
                return number
    except OSError:
        pass
    return 0


def collect_references(
    files: list[Path],
    reference_files: set[Path],
    domains: frozenset[str],
    services: set[str],
    live: dict[str, str],
) -> tuple[dict[str, list[tuple[Path, int]]], list[tuple[Path, str]]]:
    """Parse every file; collect entity references only from reference_files.

    Every file is parsed because that is the syntax check, and it is worth
    running over config this script otherwise has no opinion about.
    """
    references: dict[str, list[tuple[Path, int]]] = defaultdict(list)
    parse_errors: list[tuple[Path, str]] = []

    for path in files:
        try:
            documents = list(yaml.load_all(path.read_text(), Loader=HaTagLoader))
        except yaml.YAMLError as exc:
            parse_errors.append((path, str(exc).splitlines()[0]))
            continue

        if path not in reference_files:
            continue  # parsed for syntax only

        seen: set[str] = set()
        for document in documents:
            for text in walk_strings(document):
                seen |= candidates_in(text, domains)

        for entity_id in seen:
            # `light.turn_on` is a service call, not a reference to a missing
            # entity. Only discount it when nothing by that name actually
            # exists — `script.turn_on` could legitimately be both.
            if entity_id in services and entity_id not in live:
                continue
            references[entity_id].append((path, line_of(path, entity_id)))

    return references, parse_errors


def relative(path: Path) -> str:
    return str(path.relative_to(CONFIG_DIR.parent))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat unavailable/unknown entities as failures too",
    )
    parser.add_argument(
        "--esphome",
        action="store_true",
        help=(
            "also scan esphome/ for entity references (noisy; different schema). "
            "esphome/ is always parsed for syntax regardless of this flag"
        ),
    )
    args = parser.parse_args()

    try:
        api = HaApi()
        live = {
            entity["entity_id"]: entity.get("state", "")
            for entity in api.states()
            if isinstance(entity, dict) and "entity_id" in entity
        }
        services = api.service_names()
    except HaApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    domains = KNOWN_DOMAINS | {eid.split(".", 1)[0] for eid in live}

    files = iter_config_files()
    reference_files = {p for p in files if args.esphome or not is_esphome(p)}
    references, parse_errors = collect_references(
        files, reference_files, domains, services, live
    )

    print(
        f"instance={api.instance}  parsed={len(files)}  "
        f"scanned={len(reference_files)}  references={len(references)}  "
        f"live_entities={len(live)}"
    )

    for path, message in parse_errors:
        print(f"\nPARSE  {relative(path)}\n       {message}")

    missing = sorted(eid for eid in references if eid not in live)
    dead = sorted(eid for eid in references if live.get(eid) in DEAD_STATES)

    for entity_id in missing:
        print(f"\nMISSING  {entity_id}")
        for path, line in references[entity_id]:
            print(f"         {relative(path)}:{line}")

    for entity_id in dead:
        print(f"\nDEAD     {entity_id}  (state: {live[entity_id]})")
        for path, line in references[entity_id]:
            print(f"         {relative(path)}:{line}")

    print()
    if not missing and not dead and not parse_errors:
        print(f"ok: all {len(references)} referenced entities resolve and are alive")
        return 0

    print(
        f"summary: {len(missing)} missing, {len(dead)} dead, "
        f"{len(parse_errors)} unparseable"
    )
    if missing or parse_errors:
        return 1
    if dead and args.strict:
        return 1
    print("dead references are warnings; pass --strict to fail on them")
    return 0


if __name__ == "__main__":
    sys.exit(main())
