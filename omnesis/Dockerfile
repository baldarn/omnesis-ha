ARG BUILD_FROM=ghcr.io/omnesis-dev/omnesis-combined:0.7.0
FROM ${BUILD_FROM}

# The upstream image runs as uid 10001. The Supervisor mounts /data owned by
# root, so run.sh starts as root to prepare it and then drops to 10001.
USER root

# Set here rather than in run.sh so `docker exec <container> omnesis ...`
# sees the same state directory and keyring as the daemons.
ENV OMNESIS_CONFIG_DIR=/data/omnesis \
    OMNESIS_SECRET_STORE=passphrase \
    OMNESIS_KEYRING_PASSPHRASE_FILE=/data/omnesis/.keyring-passphrase

# `docker exec` runs as root; the CLI must not leave root-owned files in the
# state directory, so the wrapper drops to the daemons' uid first.
RUN printf '#!/bin/sh\n[ "$(id -u)" = 0 ] && exec setpriv --reuid=10001 --regid=10001 --clear-groups node /app/packages/cli/dist/index.js "$@"\nexec node /app/packages/cli/dist/index.js "$@"\n' > /usr/local/bin/omnesis \
    && chmod 0555 /usr/local/bin/omnesis

COPY --chmod=0555 run.sh /run.sh
COPY --chmod=0555 announce.sh /announce.sh

ENTRYPOINT []
CMD ["/run.sh"]
