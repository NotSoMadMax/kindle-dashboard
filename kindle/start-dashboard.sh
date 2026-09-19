#!/bin/sh
# Name: Start Kindle Dashboard
# Author: maxpi
# DontUseFBInk

BASE_DIR="/mnt/us/kindle-dashboard"
PID_FILE="$BASE_DIR/dashboard.pid"
LOG_FILE="$BASE_DIR/dashboard.log"
IMAGE_FILE="$BASE_DIR/dashboard.png"
URL="http://192.168.0.100:9090/dashboard-kindle.png"
FULL_REFRESH_INTERVAL=15

mkdir -p "$BASE_DIR"

find_fbink() {
    command -v fbink 2>/dev/null && return 0
    for candidate in /mnt/us/libkh/bin/fbink /usr/bin/fbink /usr/local/bin/fbink /mnt/us/usbnet/bin/fbink /mnt/us/extensions/FBInk/bin/fbink; do
        if [ -x "$candidate" ]; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

cleanup() {
    lipc-set-prop com.lab126.powerd preventScreenSaver 0 >/dev/null 2>&1 || true
    rm -f "$PID_FILE"
}

run_dashboard() {
    trap cleanup EXIT INT TERM
    FBINK="$(find_fbink)"
    if [ -z "$FBINK" ]; then
        echo "FBInk was not found" >>"$LOG_FILE"
        exit 1
    fi

    echo $$ >"$PID_FILE"
    lipc-set-prop com.lab126.powerd preventScreenSaver 1 >/dev/null 2>&1 || true
    count=0

    while :; do
        now="$(date +%s)"
        temporary="$BASE_DIR/dashboard.download.$$"
        if wget -q -T 15 -O "$temporary" "$URL?t=$now" && [ -s "$temporary" ]; then
            mv -f "$temporary" "$IMAGE_FILE"
            count=$((count + 1))
            if [ $((count % FULL_REFRESH_INTERVAL)) -eq 0 ]; then
                "$FBINK" -q -f -i "$IMAGE_FILE" >>"$LOG_FILE" 2>&1
            else
                "$FBINK" -q -i "$IMAGE_FILE" >>"$LOG_FILE" 2>&1
            fi
        else
            rm -f "$temporary"
            echo "$(date): dashboard download failed; retaining previous image" >>"$LOG_FILE"
        fi

        second="$(date +%S)"
        second="${second#0}"
        if [ -z "$second" ]; then
            second=0
        fi
        delay=$((65 - second))
        if [ "$delay" -gt 60 ]; then
            delay=$((delay - 60))
        fi
        sleep "$delay"
    done
}

if [ "${1:-}" = "--run" ]; then
    run_dashboard
    exit $?
fi

if [ -f "$PID_FILE" ]; then
    existing="$(cat "$PID_FILE" 2>/dev/null)"
    if [ -n "$existing" ] && kill -0 "$existing" 2>/dev/null; then
        exit 0
    fi
    rm -f "$PID_FILE"
fi

nohup "$0" --run >>"$LOG_FILE" 2>&1 </dev/null &
echo $! >"$PID_FILE"
exit 0
