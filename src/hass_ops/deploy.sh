#!/usr/bin/env bash
#
# rsync ha-config/ to /config on the instance.
#
# --delete-after removes anything on the instance that is neither tracked in
# ha-config/ nor excluded by .rsyncignore, so the dry run is not a formality.
# The runbook says any planned deletion touching .storage, a database or
# secrets.yaml means stop; that rule is enforced here rather than left to
# whoever is reading the scrollback.
#
#   deploy.sh dry     dry run only (default)
#   deploy.sh apply   dry run, then confirm, then transfer, then `ha core check`
#
# Set HA_DEPLOY_YES=1 to skip the confirmation prompt.

set -euo pipefail

mode="${1:-dry}"
case "$mode" in
  dry | apply) ;;
  *)
    echo "usage: deploy.sh [dry|apply]" >&2
    exit 64
    ;;
esac

# hass-ops deploy publishes the instance and its ssh host (from hass-ops.toml). Never hardcode a host.
instance="${HA_INSTANCE:-}"
if [ -z "$instance" ]; then
  echo "error: HA_INSTANCE is not set. Run through \`hass-ops deploy\`." >&2
  exit 2
fi
ssh_var="HA_$(printf '%s' "$instance" | tr '[:lower:]' '[:upper:]')_SSH"
ssh_target="${!ssh_var:-}"
if [ -z "$ssh_target" ]; then
  echo "error: HA_INSTANCE=$instance but $ssh_var is unset: give the instance an ssh host in hass-ops.toml." >&2
  exit 2
fi

: "${HASS_OPS_ROOT:?run through hass-ops deploy}"
config_dir="${HASS_OPS_CONFIG_DIR:-$HASS_OPS_ROOT/ha-config}"
rsyncignore="${HASS_OPS_RSYNCIGNORE:-$HASS_OPS_ROOT/.rsyncignore}"
cd "$HASS_OPS_ROOT"

echo "instance=$instance  target=$ssh_target:/config/  mode=$mode"
echo
echo "--- dry run ---"
dry_run="$(rsync -avn --delete-after --exclude-from="$rsyncignore" "$config_dir/" "$ssh_target:/config/")"
printf '%s\n' "$dry_run"

deletions="$(printf '%s\n' "$dry_run" | grep '^deleting' || true)"
if [ -n "$deletions" ]; then
  echo
  echo "!! this deploy would DELETE the following from the instance:"
  printf '%s\n' "$deletions" | sed 's/^/   /'
  if printf '%s\n' "$deletions" | grep -qE '\.storage|\.db|secrets\.yaml'; then
    echo
    echo "REFUSING: a planned deletion touches .storage, a database, or secrets.yaml." >&2
    echo "Fix $rsyncignore before going any further." >&2
    exit 3
  fi
fi

if [ "$mode" = "dry" ]; then
  echo
  echo "dry run only; nothing was transferred"
  exit 0
fi

if [ "${HA_DEPLOY_YES:-}" != "1" ]; then
  echo
  printf 'Deploy to %s (%s). Continue? [y/N] ' "$instance" "$ssh_target"
  read -r reply
  case "$reply" in
    y | Y | yes | YES) ;;
    *)
      echo "aborted"
      exit 1
      ;;
  esac
fi

echo
echo "--- transfer ---"
rsync -av --delete-after --exclude-from="$rsyncignore" "$config_dir/" "$ssh_target:/config/"

echo
echo "--- ha core check ---"
ssh "$ssh_target" 'ha core check'

echo
echo "Deployed. Now reload the specific domain, not a restart:"
echo "  hass-ops reload automation"
