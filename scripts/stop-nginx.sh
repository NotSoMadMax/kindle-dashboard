#!/bin/sh
set -eu

CONTAINER="${KINDLE_DASHBOARD_CONTAINER:-kindle-dashboard-nginx}"
docker stop --time 10 "$CONTAINER" >/dev/null 2>&1 || true
