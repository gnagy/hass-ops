# Deploy and verify

This sends [validated](edit.md) changes to the instance. `deploy` copies your working tree as it is, so
you can try a change before committing it. If you have a test instance, run each
step there first with `-i test`; everything below works the same against it.

## deploy

Sends the YAML in `ha-config/` to `/config` on the instance.

```shell
hass-ops deploy --dry-run    # show what would change; send nothing
hass-ops deploy              # check, dry run, confirm, send, ha core check
hass-ops deploy --yes        # without the confirmation prompt
```

`deploy` copies with rsync over ssh. In order, it:

1. runs `check`, and stops if it fails (`--skip-check` skips this);
2. runs rsync as a dry run and prints every file it would change;
3. lists any files it would delete, separately, so they cannot scroll past;
4. refuses outright if a deletion would touch `.storage`, a database or `secrets.yaml`;
5. asks before sending anything;
6. sends the files, then runs `ha core check` on the instance.

**Deletions are the risk.** rsync runs with `--delete-after`: a file on the instance that is neither in
`ha-config/` nor matched by `.rsyncignore` is deleted. Read the planned deletions every time. If one surprises
you, the file belongs in `.rsyncignore` or in `ha-config/`. [configuration.md](configuration.md#the-exclude-list)
covers what the exclude list must cover.

A file the dry run would send that you did not change was changed on the instance, and deploying overwrites
it. [Fetch it back](sync.md#yaml-files-fetch-them-back) first if you want to keep it.

### reload

Home Assistant does not pick up deployed YAML by itself. Reload the parts you changed:

```shell
hass-ops reload automation
hass-ops reload automation script scene
```

A restart takes minutes, during which no automation runs; a reload takes a second. Common ones: `automation`,
`script`, `scene`, `template`, `input_boolean`, `group`. Any integration that offers a `reload` service works.

Some changes still need a restart, such as adding an integration configured in YAML. `ha core check` tells you
whether the configuration is valid, not whether a reload is enough.

## apply

Changes the instance's registries and UI dashboards to match `desired/`.

```shell
hass-ops apply               # the plan again
hass-ops apply --write       # send it
```

- **It does exactly what the dry run printed.** The plan and the write go through the same list of changes.
- **Everything is validated before anything is written.** An unknown area, label or `unique_id` fails the run
  with nothing sent.
- **Only what `desired/` names is touched.** `apply` never deletes registry entries, and never creates or
  deletes dashboards.
- **Idempotent.** Run it again and it plans nothing.
- Floors, areas and labels are written first, then devices, then entities, so an entity can use an area the
  same run creates.

Home Assistant chooses the id of a new floor, area or label itself, from its name. `apply` reads back the id
it got and says if it differs from the one in `desired/`; correct the file if so, or anything referring to the
old id points at nothing.

When a change renames entities and edits YAML that uses the new names, `apply --write` first, then `deploy`,
then reload: the automations then find the entities they refer to as soon as they load.

## Verify

```shell
hass-ops check --strict      # every entity the YAML names exists and is reporting
```

Then watch the change work: trigger the automation, look at the dashboard, and read Home Assistant's log for
errors from what you changed. If it doesn't work, fix and deploy again.

When it works, record it:

```shell
hass-ops pull                # the instance's new state into exports/
git add -A && git commit     # your change and the new exports/ together
```

## Undo

- **YAML, not yet committed:** `git checkout ha-config/`, `deploy`, reload.
- **YAML, committed:** `git revert` the commit, `deploy`, reload.
- **Registry and dashboards:** revert the change to `desired/`, then `apply --write`. For state `desired/` didn't
  manage before, the previous values are in the history of `exports/` (`git log -p exports/`): copy them
  into `desired/` and apply.
- **Anything else:** restore the backup you made before starting.
