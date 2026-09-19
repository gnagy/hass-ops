# hass-ops

The `hass-ops` command: operate a Home Assistant instance as code. Extracted on 2026-09-19 from the `tools/`
folder of a private house config repo (gnagy/ha-config), whose history this repo carries. That repo is the
first user; its `hass-ops.toml` is the reference project file.

**Keep it generic.** Nothing about one house belongs here: no URLs, hostnames, entity ids or paths into a
particular config repo. What varies per project goes in `hass-ops.toml`.

Test with `uv run pytest`. Against a real instance, prefer the test instance (`-i test`) and read-only
commands (`check`, `pull`, `drift`, `apply` without `--write`, `deploy --dry-run`).

## Rules

- The instance is resolved once, in `project.py`: `--instance`, then `HA_INSTANCE`, then the default in
  `hass-ops.toml`, and printed before anything connects. Clients read the published
  `HA_{INSTANCE}_URL` / `HA_{INSTANCE}_TOKEN`. **Never hardcode a URL or a path to a config repo**: paths
  come from `hass-ops.toml`.
- Tokens: `HA_{INSTANCE}_TOKEN` from the environment, else the instance's `token_command`, run only for the
  targeted instance. A token is never printed, logged or written to a file.
- `ha_api.py` is stdlib only: every other module imports it, so a dependency there is a dependency everywhere.
- A command is a module with a `main()` that parses its own arguments; `cli.py` registers it in `COMMANDS`.
  Modules read project paths at import, so `cli.py` imports them only after `project.activate()`.
- Service names and entity IDs are shaped identically (`light.turn_on` vs `light.kitchen`). Anything
  scanning YAML for entity references must subtract `HaApi.service_names()` or it will report the
  whole action list as missing entities.
- Every write operation logs which instance it targets, at INFO, *before* acting.
- Writing commands are idempotent and dry-run by default (`--write` to act), printing the diff without writing.
- Pull sorts by `unique_id`. Without deterministic ordering every pull is churn and the diff
  stops meaning anything.
- Registry and Lovelace operations need the **WebSocket** API, not REST.

Write the pull side before the apply side: pull is read-only, so it is safe to iterate on, and it
produces the fixtures apply gets tested against.
