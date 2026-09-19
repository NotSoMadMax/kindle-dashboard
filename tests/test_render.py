import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from PIL import Image, ImageChops

from app.render import (
    DOG_PHOTO_BOUNDS,
    DOG_PHOTO_PATH,
    FORECAST_DAYS_TO_DISPLAY,
    WeatherResult,
    astronomy_url,
    format_offset,
    parse_astronomy,
    load_config,
    render_dashboard,
    run,
    validate_weather,
    weather_description,
    weather_url,
)

ROOT = Path(__file__).resolve().parents[1]

SAMPLE_WEATHER = {
    "current": {
        "temperature_2m": 14.4,
        "apparent_temperature": 13.1,
        "relative_humidity_2m": 72,
        "weather_code": 2,
        "wind_speed_10m": 8.7,
    },
    "daily": {
        "time": ["2026-09-19", "2026-09-20", "2026-09-21", "2026-09-22"],
        "weather_code": [2, 3, 61, 0],
        "temperature_2m_max": [18.2, 17.1, 16.5, 19.0],
        "temperature_2m_min": [9.8, 10.2, 8.7, 9.4],
        "sunrise": [
            "2026-09-19T06:53",
            "2026-09-20T06:54",
            "2026-09-21T06:56",
            "2026-09-22T06:57",
        ],
        "sunset": [
            "2026-09-19T19:10",
            "2026-09-20T19:08",
            "2026-09-21T19:06",
            "2026-09-22T19:04",
        ],
        "precipitation_probability_max": [20, 30, 70, 10],
    },
    "astronomy": {
        "date": "2026-09-18",
        "moonrise": "14:08",
        "moonset": "22:46",
    },
}

SAMPLE_ASTRONOMY_RESPONSE = {
    "properties": {
        "data": {
            "moondata": [
                {"phen": "Rise", "time": "14:08"},
                {"phen": "Upper Transit", "time": "18:30"},
                {"phen": "Set", "time": "22:46"},
            ]
        }
    }
}


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "config.json")
        self.now = datetime(2026, 9, 19, 5, 33, tzinfo=timezone.utc)
        self.weather = WeatherResult(SAMPLE_WEATHER, self.now, False, None)

    def test_timezone_display_labels(self):
        self.assertNotIn("label", self.config["clocks"][0])
        self.assertNotIn("label", self.config["clocks"][1])
        self.assertEqual(self.config["clocks"][1]["native_label"], "北京")

    def test_dog_photo_asset_and_render(self):
        self.assertEqual(FORECAST_DAYS_TO_DISPLAY, 2)
        with Image.open(DOG_PHOTO_PATH) as dog:
            dog.load()
            self.assertEqual(dog.size, (290, 202))
            self.assertEqual(dog.mode, "L")
            colors = dog.getcolors(maxcolors=256)
            self.assertIsNotNone(colors)
            self.assertLessEqual(len(colors), 16)
            self.assertFalse(dog.getexif())

            rendered = render_dashboard(self.config, self.weather, self.now)
            rendered_photo = rendered.crop(DOG_PHOTO_BOUNDS)
            self.assertIsNone(
                ImageChops.difference(rendered_photo, dog).getbbox()
            )

    def test_expected_time_zone_offsets(self):
        seattle = self.now.astimezone(ZoneInfo("America/Los_Angeles"))
        beijing = self.now.astimezone(ZoneInfo("Asia/Shanghai"))
        self.assertEqual(seattle.strftime("%H:%M"), "22:33")
        self.assertEqual(beijing.strftime("%H:%M"), "13:33")
        self.assertEqual(format_offset(seattle), "UTC−07:00")
        self.assertEqual(format_offset(beijing), "UTC+08:00")

    def test_seattle_winter_offset_uses_dst_rules(self):
        winter = datetime(2026, 12, 1, tzinfo=timezone.utc).astimezone(
            ZoneInfo("America/Los_Angeles")
        )
        self.assertEqual(format_offset(winter), "UTC−08:00")

    def test_astronomy_contract(self):
        parsed = parse_astronomy(SAMPLE_ASTRONOMY_RESPONSE, "2026-09-18")
        self.assertEqual(
            parsed,
            {"date": "2026-09-18", "moonrise": "14:08", "moonset": "22:46"},
        )
        url = astronomy_url(self.config, self.now)
        self.assertIn("date=2026-09-18", url)
        self.assertIn("coords=47.6062%2C-122.3321", url)
        self.assertIn("tz=-7", url)

    def test_weather_descriptions(self):
        self.assertEqual(weather_description(0), "Clear")
        self.assertEqual(weather_description(63), "Rain")
        self.assertEqual(weather_description(75), "Snow")
        self.assertEqual(weather_description(95), "Thunderstorm")

    def test_four_day_forecast_contract(self):
        validate_weather(SAMPLE_WEATHER)
        request_url = weather_url(self.config)
        self.assertIn("forecast_days=4", request_url)
        self.assertIn("weather_code", request_url)
        self.assertEqual(len(SAMPLE_WEATHER["daily"]["time"]), 4)
        self.assertEqual(self.config["weather"]["refresh_minutes"], 60)

    def test_logical_render_dimensions_and_mode(self):
        image = render_dashboard(self.config, self.weather, self.now)
        self.assertEqual(image.size, (1072, 1448))
        self.assertEqual(image.mode, "L")
        minimum, maximum = image.getextrema()
        self.assertLess(minimum, maximum)

    def test_run_writes_to_environment_selected_public_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_root = Path(directory)
            public_dir = temporary_root / "ram-public"
            state_dir = temporary_root / "persistent-state"
            config_path = temporary_root / "config.json"
            config_path.write_text(json.dumps(self.config), encoding="utf-8")
            environment = {
                "KINDLE_DASHBOARD_PUBLIC_DIR": str(public_dir),
                "KINDLE_DASHBOARD_STATE_DIR": str(state_dir),
            }
            with (
                patch.dict(os.environ, environment),
                patch("app.render.obtain_weather", return_value=self.weather),
            ):
                status = run(config_path, self.now)
            with Image.open(public_dir / "dashboard.png") as logical:
                self.assertEqual(logical.size, (1072, 1448))
            with Image.open(public_dir / "dashboard-kindle.png") as physical:
                self.assertEqual(physical.size, (1072, 1448))
            self.assertEqual(status["kindle_rotation_degrees"], 0)
            self.assertTrue((public_dir / "status.json").exists())
            self.assertTrue((public_dir / "index.html").exists())
            self.assertFalse((temporary_root / "public").exists())


if __name__ == "__main__":
    unittest.main()
