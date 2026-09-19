# Kindle Dashboard

Kindle Dashboard turns a jailbroken e-reader into an always-on information display. It presents dual-timezone clocks, local weather, and solar information in an e-ink-friendly layout.

## Architecture

- A Python renderer combines time and weather data into grayscale dashboard images.
- A Raspberry Pi schedules rendering and serves the generated output through nginx.
- The Kindle periodically downloads the latest image and displays it with FBInk.
- Runtime output is kept in memory; configuration and cached data remain persistent.

## Repository layout

- `app/` — data and rendering logic
- `kindle/` — Kindle start and stop scripts
- `nginx/`, `systemd/`, `scripts/` — hosting and lifecycle management
- `tests/` — renderer and timezone validation
