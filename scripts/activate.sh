#!/bin/sh
set -eu

PROJECT="$HOME/Workspace/kindle-dashboard"
NGINX_IMAGE="nginx@sha256:30f1c0d78e0ad60901648be663a710bdadf19e4c10ac6782c235200619158284"
CONTAINER="kindle-dashboard-nginx"

chmod 755 "$PROJECT/scripts/activate.sh" "$PROJECT/scripts/prepare-runtime.sh" "$PROJECT/scripts/run-nginx.sh" "$PROJECT/scripts/stop-nginx.sh"
mkdir -p "$HOME/.config/systemd/user"
install -m 644 "$PROJECT/systemd/kindle-dashboard-render.service" "$HOME/.config/systemd/user/"
install -m 644 "$PROJECT/systemd/kindle-dashboard-render.timer" "$HOME/.config/systemd/user/"
install -m 644 "$PROJECT/systemd/kindle-dashboard-nginx.service" "$HOME/.config/systemd/user/"

docker pull "$NGINX_IMAGE"

systemctl --user daemon-reload
systemctl --user enable kindle-dashboard-render.timer kindle-dashboard-nginx.service

# Hand ownership of nginx to user systemd. Disable the old container's
# daemon-level restart policy before removing it to avoid a port race.
systemctl --user stop kindle-dashboard-nginx.service 2>/dev/null || true
if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
    docker update --restart=no "$CONTAINER" >/dev/null
    docker rm -f "$CONTAINER" >/dev/null
fi

systemctl --user start kindle-dashboard-render.timer
systemctl --user start kindle-dashboard-nginx.service

printf 'Dashboard available at http://192.168.0.100:9090/\n'
