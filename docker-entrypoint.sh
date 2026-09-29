#!/bin/sh
# Starts as root only to make the certs directory writable for the app user (Docker creates a
# missing bind-mount source such as ./certs owned by root), then runs the server as app.
set -e
if [ "$(id -u)" = "0" ]; then
    mkdir -p /app/certs
    # Fails harmlessly where the mount does not support it (e.g. Docker Desktop on Windows)
    chown app:app /app/certs 2>/dev/null || true
    exec setpriv --reuid=app --regid=app --init-groups python main.py "$@"
fi
exec python main.py "$@"
