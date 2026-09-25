# Other operations

## A test instance

A second instance to rehearse on, such as a VM restored from a backup of your house, is worth having. Add it
as another `[instances.<name>]` table in `hass-ops.toml`, with its own token, and target it with `-i`:

```shell
hass-ops -i test deploy --dry-run
hass-ops -i test apply --write
```

Which instance a command targets is decided once: `-i`/`--instance`, then the `HA_INSTANCE` environment
variable, then the instance marked `default = true`. It is printed before anything connects, and every write
logs its target before it acts.

`desired/` is keyed on ids that are the same on every instance (`unique_id`, device identifiers), so the same
file applies to both. `exports/` keeps one directory per instance.

## Scripts and MCP servers: exec

```shell
hass-ops exec -- ./my-script.py
hass-ops -i test exec -- ./my-script.py
```

Runs any command with the targeted instance in its environment: `HA_INSTANCE`, `HA_<NAME>_URL`,
`HA_<NAME>_SSH` and `HA_<NAME>_TOKEN`, the token taken from the keychain as usual. A script, or an MCP server
that gives an AI agent access to Home Assistant, then needs no token of its own, and switching it to the test
instance is `-i test`. Python scripts can use hass-ops's own clients, `hass_ops.ha_api` (REST) and
`hass_ops.ha_ws` (WebSocket), which read the same variables.

For [ha-mcp](https://github.com/homeassistant-ai/ha-mcp), which reads `HOMEASSISTANT_URL` and
`HOMEASSISTANT_TOKEN`, an MCP client entry could be:

```json
{
  "mcpServers": {
    "ha-test": {
      "command": "hass-ops",
      "args": ["-C", "/path/to/my-house", "-i", "test", "exec", "--", "sh", "-c",
               "HOMEASSISTANT_URL=\"$HA_TEST_URL\" HOMEASSISTANT_TOKEN=\"$HA_TEST_TOKEN\" exec uvx ha-mcp"]
    }
  }
}
```

One entry per instance lets you give each its own guardrails, e.g. ha-mcp's `READ_ONLY_MODE=true` in the
entry for your house and writes allowed on the test instance.

## HACS checks

```shell
hass-ops hacs preflight      # before updating anything through HACS
hass-ops hacs resources      # after
```

HACS updates a dashboard card by deleting its files and then downloading the new release. If the GitHub token
HACS holds has been revoked, the download fails and the card is left with no files, while HACS still records
it as installed. Nothing reports it until a dashboard shows "Custom element doesn't exist".

- `preflight` asks GitHub whether HACS's token is still accepted. It runs on the instance over ssh, where the
  token is, and needs `python3` there; the token is never printed or sent back.
- `resources` requests every dashboard resource URL and fails on any that doesn't load.

Both are read-only. Exit codes: 0 fine, 1 a problem found, 2 the instance could not be reached.

## Rotating a token

Create a new long-lived token in Home Assistant, store it where the instance's `token_command` reads it (on
macOS, the same `security add-generic-password -U …` command as during [setup](setup.md#3-give-it-a-token)),
run any read-only command to confirm it works, then delete the old token in Home Assistant. On each machine
you work from, update the stored token.
