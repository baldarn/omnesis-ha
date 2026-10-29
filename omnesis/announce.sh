#!/bin/sh
# Once the gateway is healthy, print what setting it up needs to the add-on
# log: the certificate fingerprint to compare when pairing the Home Assistant
# integration, and (with "portal" as the argument) a portal pairing code, so
# the first portal login needs no shell access.
set -u

PORT="${OMNESIS_GATEWAY_PORT:-7600}"
for _ in $(seq 1 120); do
  if curl --fail --insecure --silent "https://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    FINGERPRINT="$(omnesis tls status 2>/dev/null | node -e '
      let s = "";
      process.stdin.on("data", (d) => (s += d)).on("end", () => {
        try { process.stdout.write(JSON.parse(s).served.fingerprintSha256 || ""); } catch {}
      });')"
    if [ -n "$FINGERPRINT" ]; then
      echo "[omnesis-addon] Gateway certificate SHA-256 fingerprint: $FINGERPRINT"
    fi
    if [ "${1:-}" = "portal" ]; then
      echo "[omnesis-addon] Portal pairing code (valid for 10 minutes; restart the add-on for a new one):"
      omnesis devices pair --kind portal --name "Home Assistant portal" 2>&1 | sed 's/^/[omnesis-addon]   /'
    fi
    exit 0
  fi
  sleep 5
done
echo "[omnesis-addon] The gateway did not become healthy within 10 minutes."
