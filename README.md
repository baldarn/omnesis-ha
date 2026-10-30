# Omnesis for Home Assistant

Two pieces that bring [Omnesis](https://omnesis.dev) — a self-hosted index of
your email, messages, notes, calendars and 40+ other sources, with an agent
that answers from them — to Home Assistant:

| | What it does | Install |
| --- | --- | --- |
| **[Omnesis add-on](omnesis/DOCS.md)** | Runs the Omnesis gateway and a collector on Home Assistant OS / Supervised. | Add this repository to the add-on store |
| **Omnesis integration** | Makes Omnesis a conversation agent for Assist, adds an `omnesis.ask` action and a gateway connectivity sensor. Works with the add-on or any other Omnesis gateway. | HACS custom repository |

This is a community project, not affiliated with the Omnesis authors.
Omnesis itself is in alpha.

## Add-on

[![Add repository](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fbaldarn%2Fomnesis-ha)

**Settings → Add-ons → Add-on store → ⋮ → Repositories**, add
`https://github.com/baldarn/omnesis-ha`, then install **Omnesis**. Set a
passphrase, start it, and follow [the add-on docs](omnesis/DOCS.md).

## Integration

1. In HACS, **⋮ → Custom repositories**, add
   `https://github.com/baldarn/omnesis-ha` as type **Integration**, and
   download **Omnesis**. Restart Home Assistant.
2. In the Omnesis portal, **Settings → Devices → Pair device**: kind
   **Integration**, name `Home Assistant`, and the access level its answers may
   use. (Or `omnesis devices pair --kind integration --name "Home Assistant"`,
   then pick the level on the device's card.)
3. **Settings → Devices & services → Add integration → Omnesis**. With the
   add-on, keep `https://127.0.0.1:7600`. Compare the certificate fingerprint
   with the one in the add-on log, then paste the pairing code.
4. **Settings → Voice assistants**: pick **Omnesis** as the conversation agent
   of an assistant.

Omnesis answers only once it has an agent model: assign one with
`omnesis model assign`, or set `inference.assignments.agent` in `omnesis.json`. Until then every question
is refused with "Agent disabled".

The integration holds a token with only the `answer` scope: it can ask
questions and nothing else. Which sources answers may draw on, and whether a
privacy reviewer checks them first, is the access level you chose, and you can
change it in the portal at any time. Answers that would need your approval are
never held for it (`approval: never`), since nobody is there to approve them.

### Asking from automations

```yaml
action: omnesis.ask
data:
  question: "Do I have anything on my calendar tomorrow morning?"
response_variable: omnesis
# omnesis.status: released | released_with_reductions | approval_required | denied
# omnesis.answer, omnesis.reductions, omnesis.reason
```

Answers can take a while (the default limit is 120 seconds, set in the
integration's options). A voice satellite may give up sooner than that.

### Certificates

A self-signed gateway certificate is pinned by its SHA-256 fingerprint; a
certificate the system already trusts (Tailscale, a public CA) is verified
normally. If the gateway's certificate changes, the integration asks you to
confirm the new one.

### Revoked token

If the gateway refuses the integration's token (the device was revoked, or the
gateway's data was reset), Home Assistant asks you to reconfigure Omnesis. To
bring the same device back, with its access level, run
`omnesis devices repair <device id>` (in the add-on container:
`docker exec <container> omnesis devices repair <device id>`; `omnesis devices
list` shows the id) and paste the repair code it prints. A new pairing code
from the portal works too, but creates a new device.

## Development

```sh
uv venv -p 3.13 .venv
uv pip install -p .venv -r requirements_test.txt
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

The add-on can be tried without Home Assistant:

```sh
docker build -t local/omnesis-addon omnesis/
mkdir -p tmpdata && echo '{"passphrase":"change-me-long-passphrase","log_portal_pairing_code":true}' > tmpdata/options.json
docker run --rm -v "$PWD/tmpdata:/data" -p 7600:7600 local/omnesis-addon
```

## License

MIT for this repository. The add-on image is built on the Omnesis image,
which is AGPL-3.0-or-later.
