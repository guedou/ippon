# SPDX-License-Identifier: GPL-2.0+
"""French weather descriptions for live data and older offline snapshots."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from ippon import weather


def payload(code=None, description="Light drizzle"):
    current = {"temp_C": "12", "FeelsLikeC": "10"}
    if code is not None:
        current["weatherCode"] = code
    if description is not None:
        current["weatherDesc"] = [{"value": description}]
    return {"current_condition": [current],
            "weather": [{"mintempC": "8", "maxtempC": "13",
                         "hourly": [{"chanceofrain": "30"}]}]}


class WeatherLocaleTests(unittest.TestCase):
    def test_numeric_code_wins_over_provider_language_or_spelling(self):
        for code in ("266", 266):
            for description in ("Light drizzle", "LightDrizle", "Something else", None):
                with self.subTest(code=code, description=description):
                    result = weather.WeatherService._parse(payload(code, description))
                    self.assertEqual(result["description"], "Bruine légère")
        self.assertEqual(weather.WeatherService._parse(payload("389"))["description"],
                         "Pluie orageuse modérée ou forte")

    def test_legacy_english_aliases_french_and_unknown_fallback(self):
        for source, expected in (
                ("LightDrizle", "Bruine légère"),
                (" light drizzle ", "Bruine légère"),
                ("LightDrizzle", "Bruine légère"),
                ("Moderate or heavy rain shower", "Averses modérées ou fortes"),
                ("PartlyCloudy", "Partiellement nuageux"),
                ("Partiellement nuageux", "Partiellement nuageux"),
                ("Bruine légère", "Bruine légère"),
                ("Unknown new English condition", "Conditions inconnues")):
            with self.subTest(source=source):
                self.assertEqual(weather.WeatherService._parse(payload(None, source))["description"], expected)
        self.assertEqual(weather.WeatherService._parse(payload("999", None))["description"],
                         "Conditions inconnues")

    def test_offline_legacy_cache_translated_without_rewriting_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weather.json"
            original = weather.WeatherService._parse(payload("266"))
            original.update(description="LightDrizle", updated_at=1000.0)
            path.write_text(json.dumps(original), encoding="utf-8")
            original_bytes = path.read_bytes()
            with patch.object(weather.requests, "get") as request:
                service = weather.WeatherService(cache_path=path)
                request.assert_not_called()
            self.assertEqual(service.get_snapshot()["description"], "Bruine légère")
            self.assertEqual(service.status()["last_success"], 1000.0)
            self.assertEqual(service.status()["state"], "cached")
            self.assertEqual(path.read_bytes(), original_bytes)
            self.assertIn("Bruine légère", service.text())

    def test_live_request_asks_for_french_and_persists_french_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weather.json"
            response = MagicMock()
            response.json.return_value = payload("266")
            service = weather.WeatherService(cache_path=path)
            with patch.object(weather.requests, "get", return_value=response) as request:
                service._fetch()
            url = request.call_args.args[0]
            self.assertEqual(parse_qs(urlsplit(url).query), {"format": ["j1"], "lang": ["fr"]})
            self.assertEqual(service.get_snapshot()["description"], "Bruine légère")
            self.assertEqual(json.loads(path.read_text())["description"], "Bruine légère")
            self.assertEqual(set(service.get_snapshot()),
                             {"city", "temperature", "feels_like", "description", "minimum",
                              "maximum", "rain_chance", "updated_at"})


if __name__ == "__main__":
    unittest.main()
