# SPDX-License-Identifier: GPL-2.0+

import copy
import json
import logging
import math
import os
import tempfile
import threading
import time
import unicodedata
from urllib.parse import urlencode

import requests

from ippon.config import StaticConfiguration

LOGGER = logging.getLogger(__name__)
# wttr.in's j1 weatherCode uses the WorldWeatherOnline condition enumeration.
# https://github.com/chubin/wttr.in#json-output
# https://www.worldweatheronline.com/weather-api/docs/weather-icons/
# English aliases also repair snapshots written before code-based localisation.
_CONDITIONS = {
    113: ("Sunny", "Dégagé"),
    116: ("Partly cloudy", "Partiellement nuageux"),
    119: ("Cloudy", "Nuageux"),
    122: ("Overcast", "Couvert"),
    143: ("Mist", "Brume"),
    176: ("Patchy rain nearby", "Pluie éparse à proximité"),
    179: ("Patchy snow nearby", "Neige éparse à proximité"),
    182: ("Patchy sleet nearby", "Pluie et neige éparses à proximité"),
    185: ("Patchy freezing drizzle nearby", "Bruine verglaçante éparse à proximité"),
    200: ("Thundery outbreaks in nearby", "Orages à proximité"),
    227: ("Blowing snow", "Neige soufflée"),
    230: ("Blizzard", "Blizzard"),
    248: ("Fog", "Brouillard"),
    260: ("Freezing fog", "Brouillard givrant"),
    263: ("Patchy light drizzle", "Bruine légère éparse"),
    266: ("Light drizzle", "Bruine légère"),
    281: ("Freezing drizzle", "Bruine verglaçante"),
    284: ("Heavy freezing drizzle", "Forte bruine verglaçante"),
    293: ("Patchy light rain", "Pluie légère éparse"),
    296: ("Light rain", "Pluie faible"),
    299: ("Moderate rain at times", "Pluie modérée par moments"),
    302: ("Moderate rain", "Pluie modérée"),
    305: ("Heavy rain at times", "Forte pluie par moments"),
    308: ("Heavy rain", "Forte pluie"),
    311: ("Light freezing rain", "Faible pluie verglaçante"),
    314: ("Moderate or heavy freezing rain", "Pluie verglaçante modérée ou forte"),
    317: ("Light sleet", "Faible pluie et neige mêlées"),
    320: ("Moderate or heavy sleet", "Pluie et neige mêlées modérées ou fortes"),
    323: ("Patchy light snow", "Neige légère éparse"),
    326: ("Light snow", "Neige légère"),
    329: ("Patchy moderate snow", "Neige modérée éparse"),
    332: ("Moderate snow", "Neige modérée"),
    335: ("Patchy heavy snow", "Forte neige éparse"),
    338: ("Heavy snow", "Forte neige"),
    350: ("Ice pellets", "Grésil"),
    353: ("Light rain shower", "Averses faibles"),
    356: ("Moderate or heavy rain shower", "Averses modérées ou fortes"),
    359: ("Torrential rain shower", "Averses torrentielles"),
    362: ("Light sleet showers", "Faibles averses de pluie et neige"),
    365: ("Moderate or heavy sleet showers", "Fortes averses de pluie et neige"),
    368: ("Light snow showers", "Faibles averses de neige"),
    371: ("Moderate or heavy snow showers", "Fortes averses de neige"),
    374: ("Light showers of ice pellets", "Faibles averses de grésil"),
    377: ("Moderate or heavy showers of ice pellets", "Fortes averses de grésil"),
    386: ("Patchy light rain in area with thunder", "Faible pluie orageuse éparse"),
    389: ("Moderate or heavy rain in area with thunder", "Pluie orageuse modérée ou forte"),
    392: ("Patchy light snow in area with thunder", "Faible neige orageuse éparse"),
    395: ("Moderate or heavy snow in area with thunder", "Neige orageuse modérée ou forte"),
}
WEATHER_CODES = {str(code): french for code, (_, french) in _CONDITIONS.items()}
WEATHER_DESCRIPTIONS = {english.lower(): french for english, french in _CONDITIONS.values()}
WEATHER_DESCRIPTIONS.update({
    "clear": "Dégagé", "sunny / clear": "Dégagé", "sunny": "Ensoleillé",
    "very cloudy": "Couvert", "light rain shower": "Averses faibles",
    "light rain showers": "Averses faibles", "light showers": "Averses faibles",
    "heavy showers": "Fortes averses", "thundery showers": "Averses orageuses",
    "light sleet showers": "Faibles averses de pluie et neige",
    "patchy rain possible": "Risque de pluie par endroits",
    "patchy snow possible": "Risque de neige par endroits",
    "patchy sleet possible": "Risque de pluie et neige mêlées",
    "patchy freezing drizzle possible": "Risque de bruine verglaçante",
    "thundery outbreaks possible": "Risque d'orages",
    "light rain and drizzle": "Pluie et bruine légères",
    "lightdrizle": "Bruine légère",  # Legacy misspelling reported on the screen.
})
UNKNOWN_DESCRIPTION = "Conditions inconnues"


def _description_key(value):
    text = unicodedata.normalize("NFKD", str(value)).casefold()
    return "".join(char for char in text if char.isascii() and char.isalnum())


# Recognise previously translated snapshots too; do not translate French twice.
_DESCRIPTION_ALIASES = {
    _description_key(label): french
    for english, french in WEATHER_DESCRIPTIONS.items()
    for label in (english, french)
}
_DESCRIPTION_ALIASES.update({_description_key(label): label
                             for label in (*WEATHER_CODES.values(), UNKNOWN_DESCRIPTION)})


def _description_fr(description, weather_code=None):
    if not isinstance(weather_code, bool):
        known = WEATHER_CODES.get(str(weather_code).strip())
        if known is not None:
            return known
    return _DESCRIPTION_ALIASES.get(_description_key(description), UNKNOWN_DESCRIPTION)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("Invalid numeric weather field")
    if not math.isfinite(float(value)):
        raise ValueError("Non-finite weather field")
    return value


def _validate_snapshot(payload, city):
    if not isinstance(payload, dict) or payload.get("city") != city:
        raise ValueError("Invalid weather cache")
    result = {"city": city}
    for key in ("temperature", "feels_like", "minimum", "maximum"):
        result[key] = _number(payload[key])
    description = payload["description"]
    if not isinstance(description, str) or not description.strip():
        raise ValueError("Invalid weather description")
    result["description"] = _description_fr(description)
    rain = _number(payload["rain_chance"])
    if not 0 <= float(rain) <= 100:
        raise ValueError("Invalid rain chance")
    result["rain_chance"] = int(float(rain))
    stamp = _number(payload["updated_at"])
    if not isinstance(stamp, (int, float)) or stamp <= 0:
        raise ValueError("Invalid cache timestamp")
    result["updated_at"] = float(stamp)
    return result


def _write_snapshot(path, snapshot):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, mode=0o700, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".weather-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(snapshot, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class WeatherService:
    """Nonblocking weather with private, persistent snapshots.

    Readers receive independent dictionaries. A refresh builds and persists a
    complete replacement before publishing it under the lock.
    """

    def __init__(self, city="Paris", refresh_interval=15 * 60, cache_path=None):
        self.city = city
        try:
            self.refresh_interval = max(60, int(refresh_interval))
        except (ValueError, TypeError, OverflowError):
            self.refresh_interval = 900
        self.cache_path = os.fspath(cache_path) if cache_path is not None else os.path.join(
            StaticConfiguration.config_data_directory_path, "weather.json"
        )
        self._lock = threading.Lock()
        self._next_refresh = 0
        self._thread = None
        self._snapshot = None
        self._error = None
        self._state = "loading" if isinstance(city, str) and city.strip() else "unconfigured"
        if self._state != "unconfigured":
            try:
                with open(self.cache_path, encoding="utf-8") as stream:
                    self._snapshot = _validate_snapshot(json.load(stream), city)
                self._state = "cached"
            except FileNotFoundError:
                pass
            except (OSError, ValueError, KeyError, TypeError, OverflowError):
                LOGGER.warning("Weather cache could not be loaded; awaiting refresh.")

    def refresh(self):
        """Schedule one background refresh and return immediately."""
        with self._lock:
            if self._state == "unconfigured" or time.monotonic() < self._next_refresh:
                return
            if self._thread and self._thread.is_alive():
                return
            self._next_refresh = time.monotonic() + self.refresh_interval
            if self._snapshot is None:
                self._state = "loading"
            self._thread = threading.Thread(target=self._fetch, daemon=True)
            self._thread.start()

    def get_snapshot(self):
        with self._lock:
            return copy.deepcopy(self._snapshot)

    def status(self):
        with self._lock:
            return {"state": self._state,
                    "last_success": self._snapshot["updated_at"] if self._snapshot else None,
                    "error": self._error}

    def text(self):
        snapshot = self.get_snapshot()
        return self._snapshot_text(snapshot) if snapshot else None

    def _fetch(self):
        try:
            params = urlencode({"format": "j1", "lang": "fr"})
            response = requests.get(f"https://wttr.in/{self.city}?{params}", timeout=5)
            response.raise_for_status()
            snapshot = self._parse(response.json(), self.city)
            _write_snapshot(self.cache_path, snapshot)
        except Exception as exc:
            # Never log provider responses, URLs, credentials or exception text.
            LOGGER.warning("Weather refresh failed (%s).", type(exc).__name__)
            with self._lock:
                self._next_refresh = time.monotonic() + 60
                self._state = "cached" if self._snapshot else "error"
                self._error = "La mise à jour météo a échoué."
            return
        with self._lock:
            self._snapshot = snapshot
            self._state = "ready"
            self._error = None

    @staticmethod
    def _parse(payload, city="Paris"):
        current = payload["current_condition"][0]
        today = payload["weather"][0]
        # Stable numeric codes win over provider wording and language fields.
        # Missing/unknown descriptions receive a French placeholder, never raw
        # English, including when loading a snapshot from an older version.
        descriptions = current.get("weatherDesc") or []
        description = descriptions[0].get("value", "") if descriptions else ""
        description = _description_fr(description, current.get("weatherCode"))
        rain_chance = max(int(hour.get("chanceofrain", 0)) for hour in today["hourly"])
        return _validate_snapshot({
            "city": city, "temperature": current["temp_C"],
            "feels_like": current["FeelsLikeC"], "description": description,
            "minimum": today["mintempC"], "maximum": today["maxtempC"],
            "rain_chance": rain_chance, "updated_at": time.time(),
        }, city)

    @staticmethod
    def _snapshot_text(snapshot):
        return (f"{snapshot['description']} | {snapshot['temperature']}°C | "
                f"ressenti {snapshot['feels_like']}°C\n"
                f"Aujourd'hui : {snapshot['minimum']}-{snapshot['maximum']}°C | "
                f"pluie {snapshot['rain_chance']} %")

    @staticmethod
    def _format(payload):
        """Keep the legacy formatter for callers that only need display text."""
        return WeatherService._snapshot_text(WeatherService._parse(payload))
