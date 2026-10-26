# SPDX-License-Identifier: GPL-2.0+

import threading
import time
from urllib.parse import urlencode

import requests

WEATHER_DESCRIPTIONS = {
    "clear": "Dégagé",
    "cloudy": "Nuageux",
    "fog": "Brouillard",
    "freezing fog": "Brouillard givrant",
    "heavy rain": "Forte pluie",
    "heavy rain at times": "Fortes pluies par moments",
    "light rain": "Pluie faible",
    "light rain shower": "Averses faibles",
    "mist": "Brume",
    "moderate rain": "Pluie modérée",
    "moderate rain at times": "Pluie modérée par moments",
    "overcast": "Couvert",
    "partly cloudy": "Partiellement nuageux",
    "patchy light rain": "Pluie faible par endroits",
    "patchy rain possible": "Risque de pluie par endroits",
    "sunny": "Ensoleillé",
    "thundery outbreaks possible": "Risque d'orages",
}


class WeatherService:
    """Fetch and cache the current weather without blocking the UI."""

    def __init__(self, city="Paris", refresh_interval=15 * 60):
        self.city = city
        self.refresh_interval = refresh_interval
        self._lock = threading.Lock()
        self._next_refresh = 0
        self._text = None
        self._thread = None

    def refresh(self):
        """Start a refresh when due; return immediately to the caller."""

        with self._lock:
            if time.monotonic() < self._next_refresh:
                return
            if self._thread and self._thread.is_alive():
                return
            self._next_refresh = time.monotonic() + self.refresh_interval
            self._thread = threading.Thread(target=self._fetch, daemon=True)
            self._thread.start()

    def text(self):
        with self._lock:
            return self._text

    def _fetch(self):
        try:
            params = urlencode({"format": "j1"})
            response = requests.get(
                f"https://wttr.in/{self.city}?{params}", timeout=5
            )
            response.raise_for_status()
            text = self._format(response.json())
        except (requests.RequestException, ValueError, KeyError, TypeError):
            # Retry sooner after a failed request while retaining cached weather.
            with self._lock:
                self._next_refresh = time.monotonic() + 60
            return

        with self._lock:
            self._text = text

    @staticmethod
    def _format(payload):
        current = payload["current_condition"][0]
        today = payload["weather"][0]
        description = current["weatherDesc"][0]["value"].strip().lower()
        description = WEATHER_DESCRIPTIONS.get(description, description.capitalize())
        rain_chance = max(
            int(hour.get("chanceofrain", 0)) for hour in today["hourly"]
        )
        return (
            f"{description} | {current['temp_C']}°C | "
            f"ressenti {current['FeelsLikeC']}°C\n"
            f"Aujourd'hui : {today['mintempC']}-{today['maxtempC']}°C | "
            f"pluie {rain_chance} %"
        )
