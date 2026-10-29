# Omnesis add-on

Runs the [Omnesis](https://omnesis.dev) gateway and a collector in one
container on your Home Assistant server. Omnesis indexes your email, messages,
notes, calendars and more than 40 other sources into one search index that
stays on this machine, and answers questions about them with citations.

> Omnesis is in **alpha**. Keep backups of anything you cannot lose.

## Requirements

- A 64-bit system (amd64 or aarch64). Omnesis is heavy: plan for at least
  4 GB of RAM free for it and a few GB of disk for the index and the embedding
  model. A Raspberry Pi 4 with 4 GB will struggle; a Pi 5 with 8 GB or a mini
  PC is a better fit.

## Setup

1. Set a **passphrase** in the Configuration tab and save. It unlocks the
   encryption at rest; there is no way to recover the data without it.
2. Optionally set **Extra certificate names** to the names and IPs you reach
   Home Assistant by (for example `homeassistant.local,192.168.1.10`), so the
   gateway's certificate covers them.
3. Start the add-on and open the **Log** tab. Once the gateway is up it prints
   a portal pairing code.
4. Click **Open Web UI** (it opens `https://<your-ha-host>:7600/portal/`).
   The certificate is self-signed, so your browser warns once; accept it.
   Sign in with the pairing code.
5. Add sources from the portal, or from a shell (see below).
6. Export the keyring's recovery material and keep it offline (see
   [Recovery](#recovery)).

The log also prints the gateway certificate's SHA-256 fingerprint at every
start; the Home Assistant integration asks you to compare it when pairing.

## Using the Omnesis CLI

The `omnesis` command is inside the container. From the
[Advanced SSH & Web Terminal](https://github.com/hassio-addons/addon-ssh)
add-on with **Protection mode** turned off:

```sh
docker exec -it addon_local_omnesis omnesis status
docker exec -it addon_local_omnesis omnesis sources add
docker exec -it addon_local_omnesis omnesis devices pair --kind integration --name "Home Assistant"
```

The container name depends on where you installed the add-on from; find it
with `docker ps --format '{{.Names}}' | grep omnesis`.

Sources that sign in through a browser (Gmail, Outlook, ...) open a redirect
on `localhost:3000-3003` inside the container. Those ports are not published,
so pair those sources from a computer that runs `omnesis` against this
gateway, or follow the remote-setup notes in the
[Omnesis setup guide](https://omnesis.dev/docs/setup).

## Asking Omnesis from Home Assistant

Install the **Omnesis** integration from this same repository (via HACS, as a
custom repository of type *Integration*). It turns Omnesis into a
conversation agent for Assist and adds an `omnesis.ask` action.

1. In the portal, **Settings → Devices → Pair device**, kind **Integration**,
   name `Home Assistant`, and pick an access level. Copy the code.
2. In Home Assistant, **Settings → Devices & services → Add integration →
   Omnesis**. Use `https://<your-ha-host>:7600` as the gateway URL, confirm the
   certificate fingerprint, and paste the code.

## Recovery

The passphrase seals the install root key that encrypts everything Omnesis
stores. Export recovery material for that key once, and keep it somewhere
offline:

```sh
docker exec -it addon_local_omnesis omnesis keyring export-recovery --backend passphrase
```

Changing the **passphrase** option later does not re-seal the key: the add-on
then refuses to start and tells you so. Set it back to the original one.

## Data, backups and updates

- Everything Omnesis stores lives in the add-on's `/data/omnesis`, which is
  included in Home Assistant backups of the add-on. Backups can be large.
- Update Omnesis by updating this add-on. Do **not** run `omnesis update`
  inside the container: it expects to manage its own Docker install.
- Uninstalling the add-on deletes its data.

## Not supported yet

- Home Assistant Ingress (the sidebar panel). The gateway only speaks HTTPS
  and serves the portal under `/portal/`, which Ingress cannot proxy today.
- Apple sources, which need a collector on a Mac. A Mac collector can pair
  with this gateway like with any other.
