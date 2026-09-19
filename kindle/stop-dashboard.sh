#!/bin/sh
# Name: Stop Kindle Dashboard
# Author: maxpi
# DontUseFBInk

BASE_DIR="/mnt/us/kindle-dashboard"
PID_FILE="$BASE_DIR/dashboard.pid"

if [ -f "$PID_FILE" ]; then
    pid="$(cat "$PID_FILE" 2>/dev/null)"
    if [ -n "$pid" ]; then
        kill "$pid" 2>/dev/null || true
        sleep 1
        kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
fi

lipc-set-prop com.lab126.powerd preventScreenSaver 0 >/dev/null 2>&1 || true
exit 0
