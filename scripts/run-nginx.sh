#!/bin/sh
set -eu

PROJECT="${PROJECT:-$HOME/Workspace/kindle-dashboard}"
RUNTIME_ROOT="${KINDLE_DASHBOARD_RUNTIME_ROOT:-/dev/shm/kindle-dashboard}"
CONTAINER="${KINDLE_DASHBOARD_CONTAINER:-kindle-dashboard-nginx}"
PORT_BIND="${KINDLE_DASHBOARD_PORT_BIND:-9090}"
IMAGE="nginx@sha256:30f1c0d78e0ad60901648be663a710bdadf19e4c10ac6782c235200619158284"

docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
exec docker run --rm \
    --name "$CONTAINER" \
    --pull never \
    --entrypoint /usr/sbin/nginx \
    --user 101:101 \
    --read-only \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --pids-limit 64 \
    --log-driver json-file \
    --log-opt max-size=10m \
    --log-opt max-file=3 \
    --tmpfs /var/cache/nginx:rw,noexec,nosuid,size=16m,uid=101,gid=101,mode=0755 \
    --tmpfs /var/run:rw,noexec,nosuid,size=1m,uid=101,gid=101,mode=0755 \
    --tmpfs /tmp:rw,noexec,nosuid,size=1m,uid=101,gid=101,mode=0755 \
    -p "$PORT_BIND:8080" \
    -v "$RUNTIME_ROOT/public:/usr/share/nginx/html:ro" \
    -v "$PROJECT/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
    -v "$PROJECT/nginx/runtime.conf:/etc/nginx/conf.d/default.conf:ro" \
    "$IMAGE" -g "daemon off;"
