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

# Resolve the target the same way tools/ha_api.py does. Never hardcode a host.
instance="${HA_INSTANCE:-}"
if [ -z "$instance" ]; then
  echo "error: HA_INSTANCE is not set. Run through \`mise run\`." >&2
  exit 2
fi
ssh_var="HA_$(printf '%s' "$instance" | tr '[:lower:]' '[:upper:]')_SSH"
ssh_target="${!ssh_var:-}"
if [ -z "$ssh_target" ]; then
  echo "error: HA_INSTANCE=$instance but $ssh_var is unset (see mise.toml)." >&2
  exit 2
fi

cd "$(dirname "$0")/.."

echo "instance=$instance  target=$ssh_target:/config/  mode=$mode"
echo
echo "--- dry run ---"
dry_run="$(rsync -avn --delete-after --exclude-from=.rsyncignore ha-config/ "$ssh_target:/config/")"
printf '%s\n' "$dry_run"

deletions="$(printf '%s\n' "$dry_run" | grep '^deleting' || true)"
if [ -n "$deletions" ]; then
  echo
  echo "!! this deploy would DELETE the following from the instance:"
  printf '%s\n' "$deletions" | sed 's/^/   /'
  if printf '%s\n' "$deletions" | grep -qE '\.storage|\.db|secrets\.yaml'; then
    echo
    echo "REFUSING: a planned deletion touches .storage, a database, or secrets.yaml." >&2
    echo "Fix .rsyncignore before going any further." >&2
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
  printf 'Deploy to %s — the live house. Continue? [y/N] ' "$instance"
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
rsync -av --delete-after --exclude-from=.rsyncignore ha-config/ "$ssh_target:/config/"

echo
echo "--- ha core check ---"
ssh "$ssh_target" 'ha core check'

echo
echo "Deployed. Now reload the specific domain, not a restart:"
echo "  mise run reload automation"
