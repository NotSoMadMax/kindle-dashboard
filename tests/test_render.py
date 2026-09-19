import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from PIL import Image

from app.render import (
    WeatherResult,
    format_offset,
    load_config,
    render_dashboard,
    run,
    weather_description,
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
        "temperature_2m_max": [18.2],
        "temperature_2m_min": [9.8],
        "sunrise": ["2026-09-19T06:53"],
        "sunset": ["2026-09-19T19:10"],
        "precipitation_probability_max": [20],
    },
}


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "config.json")
        self.now = datetime(2026, 9, 19, 5, 33, tzinfo=timezone.utc)
        self.weather = WeatherResult(SAMPLE_WEATHER, self.now, False, None)

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

    def test_weather_descriptions(self):
        self.assertEqual(weather_description(0), "Clear")
        self.assertEqual(weather_description(63), "Rain")
        self.assertEqual(weather_description(75), "Snow")
        self.assertEqual(weather_description(95), "Thunderstorm")

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
