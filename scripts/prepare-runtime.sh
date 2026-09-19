#!/bin/sh
set -eu

PROJECT="${PROJECT:-$HOME/Workspace/kindle-dashboard}"
RUNTIME_ROOT="${KINDLE_DASHBOARD_RUNTIME_ROOT:-/dev/shm/kindle-dashboard}"
PUBLIC_DIR="$RUNTIME_ROOT/public"

install -d -m 755 "$RUNTIME_ROOT" "$PUBLIC_DIR" "$PUBLIC_DIR/kindle"
install -m 644 "$PROJECT/kindle/start-dashboard.sh" "$PUBLIC_DIR/kindle/start-dashboard.sh"
install -m 644 "$PROJECT/kindle/stop-dashboard.sh" "$PUBLIC_DIR/kindle/stop-dashboard.sh"

KINDLE_DASHBOARD_PUBLIC_DIR="$PUBLIC_DIR" \
KINDLE_DASHBOARD_STATE_DIR="$PROJECT/state" \
    /usr/bin/python3 "$PROJECT/app/render.py" --config "$PROJECT/config.json"

find "$PUBLIC_DIR" -type f -exec chmod 644 {} \;
printf 'Prepared RAM-backed dashboard runtime at %s\n' "$PUBLIC_DIR"
