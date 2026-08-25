import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from casper import browser
import location


class RuntimeLocationProfileTests(unittest.TestCase):
    def test_us_profile_is_cached_for_one_week_with_unit_and_engine_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "location.json"
            with patch.object(location, "_profile_path", return_value=path), patch.object(
                location, "_windows_country_code", return_value="US"
            ), patch.object(
                location, "_locale_country_code", return_value=""
            ), patch.object(
                location, "_system_time_zone", return_value="Pacific Standard Time"
            ), patch.object(
                location, "_offset_text", return_value="-07:00"
            ):
                first = location.initialize_location_profile()
                second = location.initialize_location_profile()
            self.assertEqual(first, second)
            self.assertEqual(first["country_code"], "US")
            self.assertEqual(first["unit_system"], "US_CUSTOMARY")
            self.assertEqual(first["preferred_search_engines"], ["google", "bing"])
            self.assertTrue(path.is_file())
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["schema_version"], 1)
            self.assertIn("expires_at", saved)

    def test_cached_engine_pair_bypasses_per_query_ai_planning(self):
        region = {
            "country_code": "US",
            "country_name": "United States",
            "location_name": "United States",
            "time_zone": "Pacific Standard Time",
            "source": "windows_system_profile",
            "confidence": "high",
            "preferred_search_engines": ["google", "bing"],
        }
        with patch.object(
            browser, "_detected_search_region", return_value=region
        ), patch.object(
            browser,
            "_ai_search_engine_policy",
            side_effect=AssertionError("fresh cache must bypass engine AI"),
        ) as engine_ai:
            engines = browser._search_engine_policy(None, "any new query")
        self.assertEqual(engines, ("google", "bing"))
        engine_ai.assert_not_called()

    def test_location_context_is_compact_json_for_prompt_injection(self):
        profile = {
            "country_code": "US",
            "country_name": "United States",
            "location_name": "United States",
            "time_zone": "Pacific Standard Time",
            "utc_offset": "-07:00",
            "unit_system": "US_CUSTOMARY",
            "distance_unit": "mile",
            "temperature_unit": "fahrenheit",
            "weight_unit": "pound",
            "volume_unit": "fluid_ounce",
            "currency": "USD",
            "preferred_search_engines": ["google", "bing"],
            "source": "windows_system_profile",
            "confidence": "high",
            "expires_at": "2026-08-26T09:00:00-07:00",
        }
        with patch.object(
            location, "initialize_location_profile", return_value=profile
        ):
            context = location.get_localization_context()
        self.assertIn('"unit_system":"US_CUSTOMARY"', context)
        self.assertIn('"preferred_search_engines":["google","bing"]', context)
        self.assertIn("explicit current user requests override", context)


if __name__ == "__main__":
    unittest.main()
