# SPDX-License-Identifier: GPL-2.0+
"""Service contracts exercised without any network or real credentials."""

import configparser
import copy
from datetime import date, datetime, timedelta
import json
import os
import socket
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import requests

from ippon import pronote, weather


PAYLOAD = {
    "current_condition": [{"temp_C": "12", "FeelsLikeC": "10",
                           "weatherDesc": [{"value": "Partly cloudy"}]}],
    "weather": [{"mintempC": "8", "maxtempC": "13",
                 "hourly": [{"chanceofrain": "10"}, {"chanceofrain": "30"}]}],
}


def config(**options):
    result = configparser.ConfigParser(interpolation=None)
    result["pronote"] = {"pronote_url": "https://example.invalid/eleve.html",
                          "username": "synthetic-user", "password": "synthetic-password",
                          "uuid": "synthetic-uuid", **options}
    return result


def snapshot(stamp=1000.0, empty=False):
    lesson = {"start": "08:30", "end": "09:25", "subject": "Mathématiques",
              "classroom": "204", "canceled": False, "status": ""}
    return {"days": {str(date.today()): {"lessons": [] if empty else [lesson],
                                        "homework": []}}, "updated_at": stamp}


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "data" / "cache.json"

    def fetch_weather(self, service, payload=None):
        response = MagicMock()
        response.json.return_value = PAYLOAD if payload is None else payload
        with patch.object(weather.requests, "get", return_value=response) as request:
            service._fetch()
        return request

    def test_weather_first_success_persisted_and_legacy_text(self):
        service = weather.WeatherService(cache_path=self.path)
        self.assertEqual(service.status(), {"state": "loading", "last_success": None, "error": None})
        self.assertIsNone(service.get_snapshot())
        self.assertIsNone(service.text())
        self.fetch_weather(service)
        result = service.get_snapshot()
        self.assertEqual(result["temperature"], "12")
        self.assertEqual(result["description"], "Partiellement nuageux")
        self.assertEqual(result["rain_chance"], 30)
        self.assertEqual(service.status()["state"], "ready")
        self.assertEqual(service.status()["last_success"], result["updated_at"])
        self.assertEqual(json.loads(self.path.read_text()), result)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertIn("ressenti 10°C", service.text())
        self.assertEqual(service.text(), weather.WeatherService._format(PAYLOAD))
        restored = weather.WeatherService(cache_path=self.path)
        self.assertEqual(restored.status()["state"], "cached")
        self.assertEqual(restored.get_snapshot(), result)
        result["temperature"] = "999"
        self.assertEqual(service.get_snapshot()["temperature"], "12")

    def test_weather_failure_retains_persisted_timestamp_without_secret_logs(self):
        service = weather.WeatherService(cache_path=self.path)
        self.fetch_weather(service)
        before = service.get_snapshot()
        persisted = self.path.read_bytes()
        with patch.object(weather.requests, "get", side_effect=requests.Timeout("secret-token-in-url")):
            with self.assertLogs(weather.LOGGER, level="WARNING") as logs:
                service._fetch()
        self.assertNotIn("secret-token", " ".join(logs.output))
        self.assertEqual(service.status()["state"], "cached")
        self.assertEqual(service.status()["last_success"], before["updated_at"])
        self.assertTrue(service.status()["error"])
        self.assertEqual(service.get_snapshot(), before)
        self.assertEqual(self.path.read_bytes(), persisted)

    def test_weather_error_without_cache_and_malformed_provider(self):
        for bad in ({}, {"current_condition": []}, {**PAYLOAD, "weather": []}):
            with self.subTest(payload=bad):
                service = weather.WeatherService(cache_path=self.path)
                with self.assertLogs(weather.LOGGER, level="WARNING"):
                    self.fetch_weather(service, bad)
                self.assertEqual(service.status()["state"], "error")
                self.assertIsNone(service.status()["last_success"])
                self.assertIsNone(service.get_snapshot())
                self.assertFalse(self.path.exists())

    def test_weather_invalid_cache_and_wrong_city_ignored(self):
        self.path.parent.mkdir()
        good = weather.WeatherService._parse(PAYLOAD)
        for invalid in ([], {"temperature": "NaN"}, {**good, "city": "Tokyo"},
                        {**good, "updated_at": True}, {**good, "rain_chance": 130}):
            with self.subTest(cache=invalid):
                self.path.write_text(json.dumps(invalid))
                with self.assertLogs(weather.LOGGER, level="WARNING"):
                    service = weather.WeatherService(cache_path=self.path)
                self.assertEqual(service.status()["state"], "loading")
                self.assertIsNone(service.get_snapshot())

    def test_weather_atomic_replace_failure_keeps_previous_disk_and_memory(self):
        service = weather.WeatherService(cache_path=self.path)
        self.fetch_weather(service)
        before, persisted = service.get_snapshot(), self.path.read_bytes()
        with patch.object(weather.os, "replace", side_effect=OSError("synthetic disk error")):
            with self.assertLogs(weather.LOGGER, level="WARNING"):
                self.fetch_weather(service)
        self.assertEqual(self.path.read_bytes(), persisted)
        self.assertEqual(service.get_snapshot(), before)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        self.assertEqual(service.status()["state"], "cached")

    def test_weather_refresh_is_nonblocking_and_starts_only_one_worker(self):
        entered, finish = threading.Event(), threading.Event()
        response = MagicMock()
        def delayed(*args, **kwargs):
            entered.set()
            if not finish.wait(2):
                raise RuntimeError("test worker timeout")
            return response
        response.json.return_value = PAYLOAD
        service = weather.WeatherService(cache_path=self.path)
        with patch.object(weather.requests, "get", side_effect=delayed) as request:
            try:
                service.refresh()
                self.assertTrue(entered.wait(1))
                self.assertEqual(service.status()["state"], "loading")
                service.refresh()
                self.assertEqual(request.call_count, 1)
            finally:
                finish.set()
                service._thread.join(2)
        self.assertFalse(service._thread.is_alive())
        self.assertEqual(service.status()["state"], "ready")

    def test_weather_unconfigured_and_interval_fallback(self):
        service = weather.WeatherService(city="", refresh_interval="invalid", cache_path=self.path)
        with patch.object(weather.requests, "get") as request:
            service.refresh()
        self.assertEqual(service.status()["state"], "unconfigured")
        self.assertEqual(service.refresh_interval, 900)
        request.assert_not_called()

    def test_pronote_legacy_cache_has_unknown_freshness_not_file_mtime(self):
        self.path.parent.mkdir()
        legacy = snapshot()
        del legacy["updated_at"]
        self.path.write_text(json.dumps(legacy))
        os.utime(self.path, (2000, 2000))
        service = pronote.PronoteService(config(), cache_path=self.path)
        self.assertEqual(service.status()["state"], "cached")
        self.assertIsNone(service.status()["last_success"])
        self.assertIsNone(service.get_snapshot()["updated_at"])
        result = service.snapshot
        result["days"][str(date.today())]["lessons"].clear()
        self.assertTrue(service.snapshot["days"][str(date.today())]["lessons"])

    def test_pronote_corrupt_structures_are_ignored(self):
        self.path.parent.mkdir()
        bad_lesson = snapshot()
        bad_lesson["days"][str(date.today())]["lessons"][0]["start"] = "28:99"
        for invalid in ([], {"days": []}, {"days": {"not-a-date": {}}},
                        {"days": {str(date.today()): {"lessons": {}, "homework": []}}},
                        {**snapshot(), "updated_at": float("nan")}, bad_lesson):
            with self.subTest(cache=invalid):
                self.path.write_text(json.dumps(invalid))
                with self.assertLogs(pronote.LOGGER, level="WARNING"):
                    result = pronote.load_snapshot(self.path)
                self.assertEqual(result, {"days": {}, "updated_at": None})

    def test_pronote_success_status_empty_and_snapshot_isolation(self):
        service = pronote.PronoteService(config(), cache_path=self.path)
        published = snapshot()
        with patch.object(pronote, "sync_range", return_value=published):
            service._refresh()
        self.assertEqual(service.status(), {"state": "ready", "last_success": 1000., "error": None})
        published["days"].clear()
        self.assertTrue(service.get_snapshot()["days"])
        with patch.object(pronote, "sync_range", return_value=snapshot(stamp=1100, empty=True)):
            service._refresh()
        self.assertEqual(service.status()["state"], "empty")
        self.assertEqual(service.status()["last_success"], 1100.)

    def test_pronote_network_failure_retains_cache_and_hides_exception(self):
        self.path.parent.mkdir()
        self.path.write_text(json.dumps(snapshot()))
        service = pronote.PronoteService(config(), cache_path=self.path)
        before = service.get_snapshot()
        with patch.object(pronote, "sync_range", side_effect=requests.ConnectionError("synthetic-secret")):
            with self.assertLogs(pronote.LOGGER, level="WARNING") as logs:
                service._refresh()
        self.assertNotIn("synthetic-secret", " ".join(logs.output))
        self.assertNotIn("synthetic-secret", service.status()["error"])
        self.assertEqual(service.get_snapshot(), before)
        self.assertEqual(service.status()["state"], "cached")
        self.assertEqual(service.status()["last_success"], 1000.)

    def test_pronote_first_network_failure_has_no_freshness(self):
        service = pronote.PronoteService(config(), cache_path=self.path)
        with patch.object(pronote, "sync_range", side_effect=requests.Timeout("offline")):
            with self.assertLogs(pronote.LOGGER, level="WARNING"):
                service._refresh()
        self.assertEqual(service.status()["state"], "error")
        self.assertIsNone(service.status()["last_success"])

    def test_pronote_missing_or_invalid_configuration_never_starts_network(self):
        unconfigured = pronote.PronoteService(configparser.ConfigParser(), cache_path=self.path)
        with patch.object(pronote, "sync_range") as fetch:
            unconfigured.refresh()
        self.assertEqual(unconfigured.status()["state"], "unconfigured")
        fetch.assert_not_called()
        for options in ({"refresh_seconds": "oops"}, {"days_ahead": "oops"},
                        {"password": ""}):
            with self.subTest(options=options):
                with self.assertLogs(pronote.LOGGER, level="WARNING"):
                    service = pronote.PronoteService(config(**options), cache_path=self.path)
                self.assertEqual(service.status()["state"], "error")
                with patch.object(pronote, "sync_range") as fetch:
                    service.refresh()
                fetch.assert_not_called()

    def test_pronote_refresh_is_nonblocking_and_starts_only_one_worker(self):
        entered, finish = threading.Event(), threading.Event()
        def delayed(*args, **kwargs):
            entered.set()
            if not finish.wait(2):
                raise RuntimeError("test worker timeout")
            return snapshot()
        service = pronote.PronoteService(config(), cache_path=self.path)
        with patch.object(pronote, "sync_range", side_effect=delayed) as fetch:
            try:
                service.refresh()
                self.assertTrue(entered.wait(1))
                self.assertEqual(service.status()["state"], "loading")
                service.refresh()
                self.assertEqual(fetch.call_count, 1)
            finally:
                finish.set()
                service.thread.join(2)
        self.assertEqual(service.status()["state"], "ready")

    def test_sync_range_filters_ui_options_and_atomically_persists_private_cache(self):
        client = MagicMock()
        client.logged_in = True
        start = datetime.combine(date.today(), datetime.strptime("08:30", "%H:%M").time())
        client.lessons.return_value = [SimpleNamespace(
            start=start, end=start + timedelta(minutes=55),
            subject=SimpleNamespace(name="Mathématiques"), classroom="204", canceled=False, status="")]
        client.homework.return_value = [SimpleNamespace(
            date=date.today(), subject=SimpleNamespace(name="Français"), description="Lire le chapitre.", done=False)]
        client.export_credentials.return_value = {}
        settings = config(display_date=str(date.today()), refresh_seconds="900", days_ahead="2")
        with patch.object(pronote.pronotepy.Client, "token_login", return_value=client) as login:
            with patch.object(pronote, "_write_config"):
                result = pronote.sync_range(settings, days_ahead=2, cache_path=self.path)
        self.assertNotIn("display_date", login.call_args.kwargs)
        self.assertNotIn("refresh_seconds", login.call_args.kwargs)
        self.assertNotIn("days_ahead", login.call_args.kwargs)
        self.assertEqual(len(result["days"]), 3)
        self.assertEqual(json.loads(self.path.read_text()), result)
        self.assertGreater(result["updated_at"], 0)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_pronote_failed_atomic_replace_preserves_old_cache(self):
        self.path.parent.mkdir()
        old = snapshot()
        self.path.write_text(json.dumps(old))
        original = self.path.read_bytes()
        with patch.object(pronote.os, "replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                pronote._atomic_json(self.path, snapshot(stamp=2000))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_config_write_is_private_and_replaces_atomically(self):
        destination = Path(self.temporary.name) / "config" / "config.ini"
        with patch.object(pronote.StaticConfiguration, "config_directory_path", str(destination.parent)):
            with patch.object(pronote.StaticConfiguration, "config_file_path", str(destination)):
                pronote._write_config(config())
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        restored = configparser.ConfigParser()
        restored.read(destination)
        self.assertEqual(restored["pronote"]["uuid"], "synthetic-uuid")

    def test_loaded_config_preserves_literal_percent_through_token_export(self):
        destination = Path(self.temporary.name) / "config" / "config.ini"
        destination.parent.mkdir()
        destination.write_text(
            "[core]\nfootball_data_token = synthetic%football-token\n"
            "[pronote]\n"
            "pronote_url = https://example.invalid/parent.html?x=%2F\n"
            "username = synthetic%user\npassword = initial%password\n"
            "uuid = synthetic%uuid\ndisplay_date = " + str(date.today()) + "\n",
            encoding="utf-8")
        settings = pronote.StaticConfiguration
        from ippon.config import load_configuation
        loaded = load_configuation(destination)
        self.assertEqual(loaded["pronote"]["password"], "initial%password")
        self.assertEqual(loaded["core"]["football_data_token"], "synthetic%football-token")
        client = MagicMock()
        client.logged_in = True
        client.lessons.return_value = []
        client.homework.return_value = []
        client.export_credentials.return_value = {
            "password": "renewed%token", "username": "synthetic%user",
            "pronote_url": "https://example.invalid/parent.html?x=%2F",
            "uuid": "renewed%uuid"}
        with patch.object(pronote.pronotepy.ParentClient, "token_login", return_value=client) as login:
            with patch.object(settings, "config_directory_path", str(destination.parent)):
                with patch.object(settings, "config_file_path", str(destination)):
                    result = pronote.sync_range(loaded, 0, cache_path=self.path)
        self.assertEqual(login.call_args.kwargs["password"], "initial%password")
        self.assertEqual(login.call_args.kwargs["pronote_url"],
                         "https://example.invalid/parent.html?x=%2F")
        restored = load_configuation(destination)
        self.assertEqual(restored["pronote"]["password"], "renewed%token")
        self.assertEqual(restored["pronote"]["uuid"], "renewed%uuid")
        self.assertEqual(restored["pronote"]["username"], "synthetic%user")
        self.assertEqual(restored["core"]["football_data_token"], "synthetic%football-token")
        self.assertEqual(pronote.load_snapshot(self.path), result)
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_pronote_parent_login_and_percent_in_credentials(self):
        settings = config(pronote_url="https://example.invalid/parent.html", password="synthetic%password")
        client = MagicMock()
        client.logged_in = True
        client.lessons.return_value = []
        client.homework.return_value = []
        client.export_credentials.return_value = {}
        with patch.object(pronote.pronotepy.ParentClient, "token_login", return_value=client) as login:
            with patch.object(pronote, "_write_config"):
                result = pronote.sync_range(settings, 0, cache_path=self.path)
        self.assertEqual(login.call_args.kwargs["password"], "synthetic%password")
        self.assertEqual(len(result["days"]), 1)


    def test_obsolete_display_date_does_not_disable_refresh(self):
        for value in ("not-a-date", "2026-10-27"):
            with self.subTest(display_date=value):
                service = pronote.PronoteService(config(display_date=value), cache_path=self.path)
                self.assertFalse(service._configuration_error)
                with patch.object(pronote, "sync_range", return_value=snapshot()) as fetch:
                    service.refresh()
                    service.thread.join(2)
                fetch.assert_called_once()
                self.assertEqual(service.status()["state"], "ready")
        self.assertEqual(pronote.PronoteService(
            config(display_date="not-a-date"), cache_path=self.path).display_date, str(date.today()))

    def test_renewed_token_saved_before_lesson_failure_without_publishing_cache(self):
        destination = Path(self.temporary.name) / "config.ini"
        self.path.parent.mkdir()
        self.path.write_text(json.dumps(snapshot()))
        old_cache = self.path.read_bytes()
        settings = config(client_identifier="old-synthetic-identifier")
        client = MagicMock()
        client.logged_in = True
        client.export_credentials.return_value = {
            "password": "renewed-synthetic-token", "client_identifier": None}
        def fail_lessons(*args):
            persisted = configparser.ConfigParser(interpolation=None)
            persisted.read(destination)
            self.assertEqual(persisted["pronote"]["password"], "renewed-synthetic-token")
            self.assertEqual(persisted["pronote"]["client_identifier"], "old-synthetic-identifier")
            raise requests.Timeout("synthetic-private-url-and-token")
        client.lessons.side_effect = fail_lessons
        with patch.object(pronote.pronotepy.Client, "token_login", return_value=client):
            with patch.object(pronote.StaticConfiguration, "config_directory_path", self.temporary.name):
                with patch.object(pronote.StaticConfiguration, "config_file_path", str(destination)):
                    with self.assertRaises(pronote.PronoteSyncError) as caught:
                        pronote.sync_range(settings, cache_path=self.path)
        self.assertEqual(caught.exception.stage, "lessons")
        self.assertEqual(caught.exception.code, "timeout")
        self.assertNotIn("synthetic-private", str(caught.exception))
        self.assertEqual(self.path.read_bytes(), old_cache)
        client.homework.assert_not_called()

    def test_null_optional_export_does_not_erase_good_identifier(self):
        settings = config(client_identifier="synthetic-original")
        client = SimpleNamespace(export_credentials=lambda: {"client_identifier": None})
        with patch.object(pronote, "_write_config"):
            pronote._save_credentials(settings, client)
        self.assertEqual(settings["pronote"]["client_identifier"], "synthetic-original")
        self.assertEqual(settings["pronote"]["password"], "synthetic-password")

    def test_invalid_required_export_leaves_config_unmodified(self):
        for value in (None, "", 42):
            with self.subTest(value=value):
                settings = config()
                before = dict(settings["pronote"])
                client = SimpleNamespace(export_credentials=lambda: {
                    "username": "should-not-be-applied", "password": value})
                with patch.object(pronote, "_write_config") as writer:
                    with self.assertRaises(ValueError):
                        pronote._save_credentials(settings, client)
                writer.assert_not_called()
                self.assertEqual(dict(settings["pronote"]), before)

    def test_real_pronotepy_lesson_filter_includes_last_requested_day(self):
        # Use the installed library's real filtering and Lesson parser, instead
        # of MagicMock's unconstrained lessons(date_from, date_to) return value.
        for ahead in (0, 2):
            with self.subTest(days_ahead=ahead):
                end = date.today() + timedelta(days=ahead)
                entries = []
                for selected, hour in ((date.today(), 9), (end, 14), (end + timedelta(days=1), 0)):
                    start = datetime.combine(selected, datetime.min.time()).replace(hour=hour)
                    entries.append({
                        "N": "synthetic-lesson", "estAnnule": False,
                        "DateDuCours": {"V": start.strftime("%d/%m/%Y %H:%M:%S")},
                        "DateDuCoursFin": {"V": (start + timedelta(minutes=55)).strftime("%d/%m/%Y %H:%M:%S")},
                        "ListeContenus": {"V": [
                            {"G": 16, "N": "subject-id", "L": "Mathématiques"},
                            {"G": 17, "L": "204"}]}})
                client = SimpleNamespace(
                    logged_in=True,
                    parametres_utilisateur={"dataSec": {"data": {"ressource": {}}}},
                    get_week=lambda value: 1,
                    post=lambda *args: {"dataSec": {"data": {"ListeCours": entries}}},
                    export_credentials=lambda: {}, homework=lambda *args: [])
                client.lessons = lambda first, last: pronote.pronotepy.Client.lessons(client, first, last)
                with patch.object(pronote.pronotepy.Client, "token_login", return_value=client):
                    with patch.object(pronote, "_write_config"):
                        result = pronote.sync_range(config(), ahead, cache_path=self.path)
                self.assertEqual(len(result["days"]), ahead + 1)
                self.assertIn("14:00", [item["start"] for item in result["days"][str(end)]["lessons"]])
                self.assertNotIn(str(end + timedelta(days=1)), result["days"])

    def test_sync_errors_are_phase_specific_and_sanitized(self):
        class NameResolutionError(Exception):
            pass
        cases = [(requests.Timeout("secret-token"), "timeout"),
                 (requests.ConnectionError(NameResolutionError("https://private.invalid")), "dns"),
                 (socket.gaierror(8, "private.invalid"), "dns"),
                 (requests.ConnectionError("secret-token"), "connection"),
                 (requests.HTTPError("https://private.invalid/secret-token"), "http"),
                 (pronote.pronotepy.exceptions.PronoteAPIError("secret-token"), "api"),
                 (pronote.pronotepy.exceptions.MFAError("secret-token"), "mfa")]
        for cause, code in cases:
            with self.subTest(code=code):
                with patch.object(pronote.pronotepy.Client, "token_login", side_effect=cause):
                    with self.assertRaises(pronote.PronoteSyncError) as caught:
                        pronote.sync_range(config(), cache_path=self.path)
                error = caught.exception
                self.assertEqual(error.stage, "login")
                self.assertEqual(error.code, code)
                self.assertNotIn("secret-token", str(error))
                self.assertNotIn("private.invalid", str(error))
                self.assertFalse(self.path.exists())

    def test_credential_write_failure_stops_before_collection(self):
        client = MagicMock()
        client.logged_in = True
        client.export_credentials.return_value = {}
        with patch.object(pronote.pronotepy.Client, "token_login", return_value=client):
            with patch.object(pronote, "_write_config", side_effect=PermissionError("private-path")):
                with self.assertRaises(pronote.PronoteSyncError) as caught:
                    pronote.sync_range(config(), cache_path=self.path)
        self.assertEqual(caught.exception.stage, "credentials")
        self.assertEqual(caught.exception.code, "storage")
        client.lessons.assert_not_called()
        client.homework.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_homework_validation_and_cache_error_stages(self):
        client = MagicMock()
        client.logged_in = True
        client.export_credentials.return_value = {}
        client.lessons.return_value = []
        for phase in ("homework", "validation", "cache"):
            with self.subTest(phase=phase):
                client.homework.side_effect = None
                client.homework.return_value = []
                if phase == "homework":
                    client.homework.side_effect = requests.Timeout("private-url")
                if phase == "validation":
                    client.homework.return_value = [SimpleNamespace(
                        date=date.today(), subject=SimpleNamespace(name="Français"),
                        description="Texte", done="not-a-bool")]
                with patch.object(pronote.pronotepy.Client, "token_login", return_value=client):
                    with patch.object(pronote, "_write_config"):
                        with patch.object(pronote, "_atomic_json", side_effect=OSError("private-path")) as writer:
                            with self.assertRaises(pronote.PronoteSyncError) as caught:
                                pronote.sync_range(config(), cache_path=self.path)
                self.assertEqual(caught.exception.stage, phase)
                self.assertEqual(caught.exception.code, "timeout" if phase == "homework" else
                                 "validation" if phase == "validation" else "storage")
                if phase != "cache":
                    writer.assert_not_called()

    def test_bounded_transport_active_during_authentication_and_restored_after_error(self):
        from pronotepy import clients
        original = clients._Communication
        def reject(**credentials):
            self.assertIsNot(clients._Communication, original)
            raise requests.Timeout("synthetic-private-token")
        with patch.object(pronote.pronotepy.Client, "token_login", side_effect=reject):
            with self.assertRaises(pronote.PronoteSyncError):
                pronote.sync_range(config(), cache_path=self.path)
        self.assertIs(clients._Communication, original)

    def test_service_exposes_safe_phase_error_and_retains_cache_after_dns_failure(self):
        self.path.parent.mkdir()
        self.path.write_text(json.dumps(snapshot()))
        service = pronote.PronoteService(config(), cache_path=self.path)
        with patch.object(pronote.pronotepy.Client, "token_login", side_effect=
                          requests.ConnectionError(socket.gaierror(8, "private.invalid secret-token"))):
            with self.assertLogs(pronote.LOGGER, level="WARNING") as logs:
                service._refresh()
        self.assertEqual(service.status()["state"], "cached")
        self.assertEqual(service.status()["last_success"], 1000.)
        self.assertIn("DNS", service.status()["error"])
        self.assertIn("stage=login", " ".join(logs.output))
        self.assertIn("code=dns", " ".join(logs.output))
        for forbidden in ("private.invalid", "secret-token"):
            self.assertNotIn(forbidden, service.status()["error"])
            self.assertNotIn(forbidden, " ".join(logs.output))


if __name__ == "__main__":
    unittest.main()
