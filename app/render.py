#!/usr/bin/env python3
"""Render a minute-resolution, e-ink dashboard for a Kindle Paperwhite 3."""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.json"
REGULAR_FONT = next(
    candidate
    for candidate in (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    )
    if candidate.exists()
)
BOLD_FONT = next(
    candidate
    for candidate in (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    )
    if candidate.exists()
)
CJK_FONT = next(
    (
        candidate
        for candidate in (
            Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
            Path("/System/Library/Fonts/PingFang.ttc"),
            Path("/System/Library/Fonts/STHeiti Medium.ttc"),
        )
        if candidate.exists()
    ),
    REGULAR_FONT,
)


@dataclass(frozen=True)
class WeatherResult:
    payload: dict[str, Any] | None
    fetched_at: datetime | None
    stale: bool
    error: str | None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def atomic_save_image(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    try:
        image.save(temporary_name, format="PNG", optimize=True)
        os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def read_weather_cache(cache_path: Path) -> tuple[dict[str, Any], datetime] | None:
    try:
        with cache_path.open(encoding="utf-8") as handle:
            cached = json.load(handle)
        return cached["payload"], parse_utc(cached["fetched_at"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def weather_url(config: dict[str, Any]) -> str:
    weather = config["weather"]
    query = urllib.parse.urlencode(
        {
            "latitude": weather["latitude"],
            "longitude": weather["longitude"],
            "timezone": weather["timezone"],
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "forecast_days": int(weather.get("forecast_days", 4)),
            "current": ",".join(
                [
                    "temperature_2m",
                    "apparent_temperature",
                    "relative_humidity_2m",
                    "weather_code",
                    "wind_speed_10m",
                ]
            ),
            "daily": ",".join(
                [
                    "weather_code",
                    "temperature_2m_max",
                    "temperature_2m_min",
                    "sunrise",
                    "sunset",
                    "precipitation_probability_max",
                ]
            ),
        }
    )
    return f"https://api.open-meteo.com/v1/forecast?{query}"


def validate_weather(payload: dict[str, Any]) -> None:
    current = payload["current"]
    daily = payload["daily"]
    for key in (
        "temperature_2m",
        "apparent_temperature",
        "relative_humidity_2m",
        "weather_code",
        "wind_speed_10m",
    ):
        if key not in current:
            raise ValueError(f"Weather response is missing current.{key}")

    required_daily = (
        "time",
        "weather_code",
        "temperature_2m_max",
        "temperature_2m_min",
        "sunrise",
        "sunset",
        "precipitation_probability_max",
    )
    for key in required_daily:
        values = daily.get(key)
        if not isinstance(values, list) or len(values) < 4:
            raise ValueError(f"Weather response requires four daily.{key} values")

def obtain_weather(
    config: dict[str, Any], state_dir: Path, now: datetime | None = None
) -> WeatherResult:
    now = now or utc_now()
    cache_path = state_dir / "weather.json"
    cached = read_weather_cache(cache_path)
    max_age_seconds = int(config["weather"].get("refresh_minutes", 15)) * 60

    if cached:
        payload, fetched_at = cached
        try:
            validate_weather(payload)
        except (KeyError, TypeError, ValueError):
            cached = None
        else:
            if (now - fetched_at).total_seconds() < max_age_seconds:
                return WeatherResult(payload, fetched_at, False, None)

    try:
        request = urllib.request.Request(
            weather_url(config),
            headers={"User-Agent": "maxpi-kindle-dashboard/1.0"},
        )
        timeout = float(config["weather"].get("timeout_seconds", 7))
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
        validate_weather(payload)
        fetched_at = now
        atomic_write_json(
            cache_path,
            {"fetched_at": fetched_at.isoformat(), "payload": payload},
        )
        return WeatherResult(payload, fetched_at, False, None)
    except Exception as error:  # Keep the prior screen useful during API outages.
        message = f"{type(error).__name__}: {error}"
        if cached:
            payload, fetched_at = cached
            return WeatherResult(payload, fetched_at, True, message)
        return WeatherResult(None, None, True, message)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(BOLD_FONT if bold else REGULAR_FONT), size=size)


def cjk_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(CJK_FONT), size=size)


def fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    maximum_width: int,
    initial_size: int,
    bold: bool = False,
    minimum_size: int = 18,
) -> ImageFont.FreeTypeFont:
    size = initial_size
    while size > minimum_size:
        candidate = font(size, bold)
        box = draw.textbbox((0, 0), text, font=candidate)
        if box[2] - box[0] <= maximum_width:
            return candidate
        size -= 2
    return font(minimum_size, bold)


def draw_centered(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    text: str,
    selected_font: ImageFont.FreeTypeFont,
    fill: int = 0,
    vertical_adjustment: int = 0,
) -> None:
    left, top, right, bottom = bounds
    box = draw.textbbox((0, 0), text, font=selected_font)
    width = box[2] - box[0]
    height = box[3] - box[1]
    x = left + (right - left - width) // 2 - box[0]
    y = top + (bottom - top - height) // 2 - box[1] + vertical_adjustment
    draw.text((x, y), text, font=selected_font, fill=fill)


def format_offset(value: datetime) -> str:
    offset = value.utcoffset()
    if offset is None:
        return "UTC"
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "−"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def weather_description(code: int) -> str:
    if code == 0:
        return "Clear"
    if code in (1, 2):
        return "Partly cloudy"
    if code == 3:
        return "Overcast"
    if code in (45, 48):
        return "Fog"
    if code in (51, 53, 55, 56, 57):
        return "Drizzle"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "Rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "Snow"
    if code in (95, 96, 99):
        return "Thunderstorm"
    return "Mixed conditions"


def draw_weather_icon(
    draw: ImageDraw.ImageDraw, code: int, center: tuple[int, int], radius: int = 62
) -> None:
    x, y = center
    ink = 0
    gray = 105

    def sun(cx: int, cy: int, r: int) -> None:
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=ink, width=7)
        for angle in range(0, 360, 45):
            radians = math.radians(angle)
            inner = r + 12
            outer = r + 30
            draw.line(
                (
                    cx + math.cos(radians) * inner,
                    cy + math.sin(radians) * inner,
                    cx + math.cos(radians) * outer,
                    cy + math.sin(radians) * outer,
                ),
                fill=ink,
                width=6,
            )

    def cloud(cx: int, cy: int, width: int) -> None:
        draw.ellipse((cx - width // 2, cy - 25, cx + 8, cy + 38), fill=255, outline=ink, width=7)
        draw.ellipse((cx - 5, cy - 48, cx + width // 2, cy + 38), fill=255, outline=ink, width=7)
        draw.rounded_rectangle((cx - width // 2, cy, cx + width // 2, cy + 50), radius=20, fill=255, outline=ink, width=7)

    if code == 0:
        sun(x, y, radius // 2)
    elif code in (1, 2):
        sun(x - 34, y - 28, radius // 3)
        cloud(x + 16, y + 12, radius * 2)
    elif code in (3, 45, 48):
        cloud(x, y, radius * 2)
        if code in (45, 48):
            for dy in (70, 90):
                draw.line((x - 65, y + dy, x + 65, y + dy), fill=gray, width=6)
    else:
        cloud(x, y - 15, radius * 2)
        if code in (71, 73, 75, 77, 85, 86):
            for dx in (-45, 0, 45):
                draw.text((x + dx - 12, y + 52), "*", font=font(38, True), fill=ink)
        elif code in (95, 96, 99):
            draw.polygon(
                [(x + 4, y + 42), (x - 24, y + 95), (x + 4, y + 88), (x - 8, y + 130), (x + 42, y + 70), (x + 13, y + 77)],
                fill=ink,
            )
        else:
            for dx in (-45, 0, 45):
                draw.line((x + dx, y + 55, x + dx - 15, y + 95), fill=ink, width=7)


def first_daily(payload: dict[str, Any], key: str) -> Any:
    return payload["daily"][key][0]


def rounded_temperature(value: Any) -> str:
    return f"{round(float(value))}°"


def primary_clock_card(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    current: datetime,
) -> None:
    left, top, right, bottom = bounds
    draw.rounded_rectangle(bounds, radius=28, outline=0, width=5, fill=255)
    time_text = current.strftime("%H:%M")
    time_font = fit_font(draw, time_text, right - left - 70, 185, True)
    draw_centered(draw, (left + 20, top + 28, right - 20, bottom - 80), time_text, time_font, vertical_adjustment=-4)
    details = f"{current.strftime('%A')}  ·  {format_offset(current)}"
    details_font = fit_font(draw, details, right - left - 50, 31)
    draw_centered(draw, (left + 20, bottom - 88, right - 20, bottom - 22), details, details_font, fill=65)


def secondary_clock_card(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    native_label: str,
    current: datetime,
) -> None:
    left, top, right, bottom = bounds
    draw.rounded_rectangle(bounds, radius=28, outline=0, width=5, fill=255)
    divider = left + 280
    draw.line((divider, top + 22, divider, bottom - 22), fill=155, width=3)

    native_font = cjk_font(76)
    draw_centered(draw, (left + 20, top + 16, divider - 20, bottom - 16), native_label, native_font)

    time_text = current.strftime("%H:%M")
    time_font = fit_font(draw, time_text, right - divider - 55, 104, True)
    draw_centered(draw, (divider + 20, top + 16, right - 20, bottom - 48), time_text, time_font)
    details = f"{current.strftime('%A')}  ·  {format_offset(current)}"
    details_font = fit_font(draw, details, right - divider - 45, 24)
    draw_centered(draw, (divider + 20, bottom - 50, right - 20, bottom - 8), details, details_font, fill=65)

def render_dashboard(
    config: dict[str, Any], weather: WeatherResult, now: datetime | None = None
) -> Image.Image:
    now = now or utc_now()
    display = config["display"]
    width = int(display.get("logical_width", 1072))
    height = int(display.get("logical_height", 1448))
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)

    clocks = config["clocks"]
    first_time = now.astimezone(ZoneInfo(clocks[0]["timezone"]))
    second_time = now.astimezone(ZoneInfo(clocks[1]["timezone"]))

    date_text = first_time.strftime("%A · %d %B %Y").upper()
    date_font = fit_font(draw, date_text, 650, 36, True)
    draw.text((28, 27), date_text, font=date_font, fill=0)

    update_text = "WEATHER UNAVAILABLE"
    if weather.fetched_at:
        local_update = weather.fetched_at.astimezone(ZoneInfo(config["weather"]["timezone"]))
        prefix = "STALE WEATHER" if weather.stale else "WEATHER UPDATED"
        update_text = f"{prefix} {local_update.strftime('%H:%M')}"
    update_font = fit_font(draw, update_text, 340, 24, True)
    update_box = draw.textbbox((0, 0), update_text, font=update_font)
    draw.text((width - 28 - (update_box[2] - update_box[0]), 36), update_text, font=update_font, fill=70)
    draw.line((28, 94, width - 28, 94), fill=0, width=4)

    margin = 28
    first_bounds = (margin, 118, width - margin, 468)
    second_bounds = (margin, 488, width - margin, 690)
    primary_clock_card(draw, first_bounds, first_time)
    secondary_clock_card(draw, second_bounds, clocks[1]["native_label"], second_time)

    weather_bounds = (margin, 710, width - margin, height - 28)
    draw.rounded_rectangle(weather_bounds, radius=28, outline=0, width=5, fill=255)

    if weather.payload:
        payload = weather.payload
        current = payload["current"]
        daily = payload["daily"]
        code = int(current["weather_code"])
        draw_weather_icon(draw, code, (125, 840), 50)

        temperature = rounded_temperature(current["temperature_2m"])
        temp_font = fit_font(draw, temperature, 330, 120, True)
        draw.text((215, 755), temperature, font=temp_font, fill=0)
        condition = weather_description(code)
        condition_font = fit_font(draw, condition, 360, 32, True)
        draw.text((215, 895), condition, font=condition_font, fill=40)
        feels = f"Feels like {rounded_temperature(current['apparent_temperature'])}C"
        draw.text((215, 940), feels, font=font(25), fill=70)

        draw.line((620, 745, 620, 970), fill=145, width=3)
        sunrise = datetime.fromisoformat(str(first_daily(payload, "sunrise"))).strftime("%H:%M")
        sunset = datetime.fromisoformat(str(first_daily(payload, "sunset"))).strftime("%H:%M")
        draw.text((665, 805), "SUNRISE", font=font(20, True), fill=85)
        draw.text((850, 805), "SUNSET", font=font(20, True), fill=85)
        draw.text((665, 845), sunrise, font=font(42, True), fill=0)
        draw.text((850, 845), sunset, font=font(42, True), fill=0)

        draw.line((62, 995, width - 62, 995), fill=145, width=3)
        metrics = [
            ("HIGH / LOW", f"{rounded_temperature(first_daily(payload, 'temperature_2m_max'))} / {rounded_temperature(first_daily(payload, 'temperature_2m_min'))}C"),
            ("HUMIDITY", f"{round(float(current['relative_humidity_2m']))}%"),
            ("WIND", f"{round(float(current['wind_speed_10m']))} km/h"),
            ("RAIN", f"{round(float(first_daily(payload, 'precipitation_probability_max')))}%"),
        ]
        positions = [65, 315, 565, 815]
        for index, ((label, value), x) in enumerate(zip(metrics, positions)):
            draw.text((x, 1025), label, font=font(20, True), fill=85)
            value_font = fit_font(draw, value, 200, 34, True)
            draw.text((x, 1070), value, font=value_font, fill=0)
            if index < len(metrics) - 1:
                separator = x + 220
                draw.line((separator, 1015, separator, 1140), fill=175, width=2)

        draw.line((62, 1160, width - 62, 1160), fill=145, width=3)
        heading_font = font(23, True)
        draw_centered(draw, (62, 1168, width - 62, 1210), "NEXT 3 DAYS", heading_font, fill=70)

        forecast_left = 62
        forecast_right = width - 62
        cell_width = (forecast_right - forecast_left) // 3
        for cell_index, day_index in enumerate(range(1, 4)):
            left = forecast_left + cell_index * cell_width
            right = forecast_right if cell_index == 2 else left + cell_width
            day_label = datetime.fromisoformat(str(daily["time"][day_index])).strftime("%a").upper()
            forecast_condition = weather_description(int(daily["weather_code"][day_index]))
            high = rounded_temperature(daily["temperature_2m_max"][day_index])
            low = rounded_temperature(daily["temperature_2m_min"][day_index])
            rain = round(float(daily["precipitation_probability_max"][day_index]))

            draw_centered(draw, (left + 8, 1210, right - 8, 1252), day_label, font(26, True))
            condition_font = fit_font(draw, forecast_condition, right - left - 28, 21, True)
            draw_centered(draw, (left + 8, 1250, right - 8, 1290), forecast_condition, condition_font, fill=55)
            temperature_text = f"H {high}  L {low}C"
            temperature_font = fit_font(draw, temperature_text, right - left - 24, 29, True)
            draw_centered(draw, (left + 8, 1290, right - 8, 1342), temperature_text, temperature_font)
            rain_font = font(19)
            draw_centered(draw, (left + 8, 1340, right - 8, 1382), f"Rain {rain}%", rain_font, fill=70)
            if cell_index < 2:
                draw.line((right, 1218, right, 1388), fill=175, width=2)
    else:
        message = "Weather unavailable — clocks remain active"
        message_font = fit_font(draw, message, width - 150, 42, True)
        draw_centered(draw, weather_bounds, message, message_font)

    return image

def write_preview(public_dir: Path) -> None:
    preview = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kindle Dashboard</title><style>html,body{margin:0;background:#222;height:100%;display:grid;place-items:center}img{max-width:100vw;max-height:100vh;background:#fff}</style>
</head><body><img id="dashboard" alt="Kindle dashboard"><script>
function refresh(){document.getElementById('dashboard').src='/dashboard.png?t='+Date.now()} refresh();setInterval(refresh,60000);
</script></body></html>"""
    path = public_dir / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(preview, encoding="utf-8")


def run(config_path: Path, now: datetime | None = None) -> dict[str, Any]:
    config = load_config(config_path)
    state_dir = Path(
        os.environ.get("KINDLE_DASHBOARD_STATE_DIR", str(ROOT / "state"))
    ).expanduser()
    public_dir = Path(
        os.environ.get("KINDLE_DASHBOARD_PUBLIC_DIR", str(ROOT / "public"))
    ).expanduser()
    current = now or utc_now()
    weather = obtain_weather(config, state_dir, current)
    logical = render_dashboard(config, weather, current)
    rotation = int(config["display"].get("kindle_rotation_degrees", 0))
    if rotation not in (0, 90, 270):
        raise ValueError("kindle_rotation_degrees must be 0, 90, or 270")
    physical = logical.copy() if rotation == 0 else logical.rotate(-rotation, expand=True)

    atomic_save_image(logical, public_dir / "dashboard.png")
    atomic_save_image(physical, public_dir / "dashboard-kindle.png")
    write_preview(public_dir)

    status = {
        "rendered_at": current.isoformat(),
        "weather_fetched_at": weather.fetched_at.isoformat() if weather.fetched_at else None,
        "weather_stale": weather.stale,
        "weather_error": weather.error,
        "logical_image": {"width": logical.width, "height": logical.height, "mode": logical.mode},
        "kindle_image": {"width": physical.width, "height": physical.height, "mode": physical.mode},
        "kindle_rotation_degrees": rotation,
    }
    atomic_write_json(public_dir / "status.json", status)
    return status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    arguments = parser.parse_args()
    status = run(arguments.config.resolve())
    print(json.dumps(status, sort_keys=True))


if __name__ == "__main__":
    main()
