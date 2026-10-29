#!/bin/sh
# Home Assistant add-on entrypoint for the Omnesis combined image.
# Runs as root only long enough to prepare /data, then hands over to the
# upstream entrypoint and supervisor as the image's own uid.
set -eu

OPTIONS=/data/options.json
STATE_DIR="$OMNESIS_CONFIG_DIR"
PASSPHRASE_FILE="$OMNESIS_KEYRING_PASSPHRASE_FILE"
OMNESIS_UID=10001
OMNESIS_GID=10001

option() {
  node -e '
    const o = JSON.parse(require("fs").readFileSync(process.argv[1], "utf8"));
    const v = o[process.argv[2]];
    process.stdout.write(v === undefined || v === null ? "" : String(v));
  ' "$OPTIONS" "$1"
}

log() { echo "[omnesis-addon] $*"; }

if [ ! -f "$OPTIONS" ]; then
  log "Missing $OPTIONS; is this running under the Home Assistant Supervisor?"
  exit 1
fi

PASSPHRASE="$(option passphrase)"
if [ -z "$PASSPHRASE" ]; then
  log "Set 'passphrase' in the add-on configuration. It unlocks Omnesis's encryption at rest;"
  log "keep it safe, because the data cannot be read without it."
  exit 1
fi

install -d -m 0700 -o "$OMNESIS_UID" -g "$OMNESIS_GID" "$STATE_DIR"
# Data written by an earlier start keeps its owner; fix anything that does not.
find "$STATE_DIR" ! -uid "$OMNESIS_UID" -exec chown "$OMNESIS_UID:$OMNESIS_GID" {} +

(umask 0377; printf '%s' "$PASSPHRASE" > "$PASSPHRASE_FILE.new")
chown "$OMNESIS_UID:$OMNESIS_GID" "$PASSPHRASE_FILE.new"
mv -f "$PASSPHRASE_FILE.new" "$PASSPHRASE_FILE"
unset PASSPHRASE

export HOME=/home/omnesis
export OMNESIS_TLS_EXTRA_NAMES="$(option tls_extra_names)"

# Creates the install root key on first start, so every store is encrypted
# from the beginning; on later starts it only checks the passphrase opens it.
if ! omnesis keyring init --backend passphrase >/dev/null; then
  log "Could not open the Omnesis keyring. If you changed 'passphrase', set it back to the"
  log "one used when the add-on was first started."
  exit 1
fi

ANNOUNCE=""
[ "$(option log_portal_pairing_code)" = "true" ] && ANNOUNCE=portal
setpriv --reuid="$OMNESIS_UID" --regid="$OMNESIS_GID" --clear-groups /announce.sh $ANNOUNCE &

log "Starting Omnesis (state in $STATE_DIR)"
exec setpriv --reuid="$OMNESIS_UID" --regid="$OMNESIS_GID" --clear-groups \
  /usr/bin/tini -s -- /app/scripts/seeded-state/entrypoint.sh \
  node /app/scripts/docker/supervisor.mjs
