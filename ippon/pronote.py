# SPDX-License-Identifier: GPL-2.0+

import configparser
import copy
import json
import logging
import math
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
import socket

import pronotepy
import requests

from ippon.config import StaticConfiguration

LOGGER = logging.getLogger(__name__)
SNAPSHOT_PATH = os.path.join(
    StaticConfiguration.config_data_directory_path, "pronote", "schedule.json"
)
_CREDENTIAL_KEYS = ("pronote_url", "username", "password", "uuid", "account_pin",
                    "client_identifier", "device_name")


_STAGE_LABELS = {
    "login": "Connexion à Pronote",
    "credentials": "Accès de connexion Pronote",
    "lessons": "Récupération des cours",
    "homework": "Récupération des devoirs",
    "validation": "Validation des données Pronote",
    "cache": "Enregistrement du cache Pronote",
}
_ERROR_MESSAGES = {
    "timeout": "délai réseau dépassé. Réessayez lorsque la connexion est rétablie.",
    "dns": "résolution DNS impossible. Vérifiez la connexion et le nom du serveur.",
    "connection": "connexion réseau impossible.",
    "http": "le serveur a renvoyé une erreur HTTP.",
    "api": "la requête à l’API Pronote a échoué.",
    "mfa": "validation à deux facteurs nécessaire ou refusée.",
    "credentials": "configuration des accès invalide.",
    "validation": "données reçues invalides ou incompatibles.",
    "storage": "écriture locale impossible. Vérifiez les droits et l’espace disque.",
    "unknown": "la synchronisation a échoué.",
}


def _error_code(stage, cause):
    """Classify exception types, including wrapped urllib3 DNS failures.

    Never inspect exception messages: they may contain a URL or a password.
    """
    pending, chain, seen = [cause], [], set()
    while pending and len(chain) < 32:
        error = pending.pop()
        if not isinstance(error, BaseException) or id(error) in seen:
            continue
        seen.add(id(error))
        chain.append(error)
        pending.extend((error.__cause__, error.__context__, getattr(error, "reason", None)))
        pending.extend(arg for arg in error.args if isinstance(arg, BaseException))
    names = {type(error).__name__ for error in chain}
    if "MFAError" in names:
        return "mfa"
    if any(isinstance(error, socket.gaierror) for error in chain) or "NameResolutionError" in names:
        return "dns"
    if any(isinstance(error, (requests.Timeout, TimeoutError)) for error in chain) or names & {
            "ReadTimeoutError", "ConnectTimeoutError"}:
        return "timeout"
    if any(isinstance(error, requests.HTTPError) for error in chain):
        return "http"
    if any(isinstance(error, requests.ConnectionError) for error in chain):
        return "connection"
    if any(isinstance(error, pronotepy.exceptions.PronoteAPIError) for error in chain):
        return "api"
    if stage in ("credentials", "cache") and any(isinstance(error, OSError) for error in chain):
        return "storage"
    if stage == "credentials":
        return "credentials"
    if stage == "validation" or any(isinstance(error, (
            ValueError, TypeError, KeyError, AttributeError,
            pronotepy.exceptions.DataError)) for error in chain):
        return "validation"
    return "unknown"


class PronoteSyncError(Exception):
    """A safe, phase-specific error for the viewer."""

    def __init__(self, stage, cause):
        self.stage = stage if stage in _STAGE_LABELS else "validation"
        self.code = _error_code(self.stage, cause)
        super().__init__(_STAGE_LABELS[self.stage] + " : " + _ERROR_MESSAGES[self.code])


@contextmanager
def _phase(stage):
    try:
        yield
    except PronoteSyncError:
        raise
    except Exception as error:
        raise PronoteSyncError(stage, error) from None


def _validate_snapshot(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("days"), dict):
        raise ValueError("Invalid Pronote snapshot")
    days = {}
    for key, entry in payload["days"].items():
        if not isinstance(key, str) or date.fromisoformat(key).isoformat() != key:
            raise ValueError("Invalid school date")
        if not isinstance(entry, dict):
            raise ValueError("Invalid school day")
        lessons, homework = entry.get("lessons"), entry.get("homework")
        if not isinstance(lessons, list) or not isinstance(homework, list):
            raise ValueError("Invalid school lists")
        for lesson in lessons:
            if not isinstance(lesson, dict):
                raise ValueError("Invalid lesson")
            for field in ("start", "end", "subject", "classroom", "status"):
                if not isinstance(lesson.get(field), str):
                    raise ValueError("Invalid lesson field")
            for field in ("start", "end"):
                if datetime.strptime(lesson[field], "%H:%M").strftime("%H:%M") != lesson[field]:
                    raise ValueError("Invalid lesson time")
            if not isinstance(lesson.get("canceled"), bool):
                raise ValueError("Invalid cancellation flag")
        for task in homework:
            if not isinstance(task, dict) or not isinstance(task.get("subject"), str) or not isinstance(task.get("description"), str) or not isinstance(task.get("done"), bool):
                raise ValueError("Invalid homework")
        days[key] = {"lessons": copy.deepcopy(lessons), "homework": copy.deepcopy(homework)}
        days[key]["lessons"].sort(key=lambda lesson: lesson["start"])
    stamp = payload.get("updated_at")
    if stamp is not None:
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp) or stamp <= 0:
            raise ValueError("Invalid school timestamp")
        stamp = float(stamp)
    return {"days": days, "updated_at": stamp}


def _atomic_json(path, payload):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, mode=0o700, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pronote-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _credentials(config):
    if not config.has_section("pronote"):
        raise ValueError("Pronote is not configured")
    credentials = {key: config.get("pronote", key, raw=True).strip().strip('"')
                   for key in _CREDENTIAL_KEYS if key in config["pronote"]}
    if any(not credentials.get(key) for key in _CREDENTIAL_KEYS[:4]):
        raise ValueError("Incomplete Pronote configuration")
    return credentials


def _save_credentials(config, client):
    """Persist renewed tokens before any subsequent server request can fail."""
    exported = client.export_credentials()
    if not isinstance(exported, dict):
        raise ValueError("Invalid credential export")
    previous = _credentials(config)
    updates = {}
    for key in _CREDENTIAL_KEYS:
        if key not in exported:
            continue
        value = exported[key]
        if value is None and key not in _CREDENTIAL_KEYS[:4]:
            continue
        if not isinstance(value, str) or (key in _CREDENTIAL_KEYS[:4] and not value.strip()):
            raise ValueError("Invalid exported credential")
        # Optional empty values must not erase a previously valid identifier.
        if value.strip() or key in _CREDENTIAL_KEYS[:4]:
            updates[key] = value
    combined = {**previous, **updates}
    if any(not combined.get(key) for key in _CREDENTIAL_KEYS[:4]):
        raise ValueError("Incomplete exported credentials")
    config["pronote"].update(updates)
    _write_config(config)


def _token_login(config, client_class, credentials):
    """Retain a rotated token even if the client constructor later fails.

    Pronotepy updates self.password before it reads ParametresUtilisateur and
    the parent's child list. A malformed response at that point must not lose
    the replacement token just because token_login never returns a client.
    """
    class DurableClient(client_class):
        def __init__(self, *args, **kwargs):
            try:
                super().__init__(*args, **kwargs)
            except Exception:
                password = vars(self).get("password")
                if (isinstance(password, str) and password.strip()
                        and password != credentials["password"]):
                    with _phase("credentials"):
                        _save_credentials(config, self)
                raise

    return DurableClient.token_login(**credentials)


def sync_range(config, days_ahead=14, cache_path=None):
    """Fetch an inclusive date range with bounded, phase-specific failures.

    Token renewal is persisted immediately after authentication, independently
    of later lesson/homework retrieval and of publication of the new cache.
    """
    with _phase("credentials"):
        credentials = _credentials(config)
    with _phase("validation"):
        today = date.today()
        end = today + timedelta(days=min(max(int(days_ahead), 0), 14))
        days = {str(today + timedelta(days=offset)): {"lessons": [], "homework": []}
                for offset in range((end - today).days + 1)}
    # The context installs a bounded transport before token_login's first GET.
    # Its sessions remain bounded throughout collection and are closed on exit.
    from ippon.pronote_transport import bounded_communication
    with _phase("login"):
        with bounded_communication():
            client_class = (pronotepy.ParentClient
                            if "parent.html" in credentials["pronote_url"]
                            else pronotepy.Client)
            with _phase("login"):
                client = _token_login(config, client_class, credentials)
                if not client.logged_in:
                    raise pronotepy.exceptions.PronoteAPIError("Authentication refused")
            with _phase("credentials"):
                _save_credentials(config, client)
            with _phase("lessons"):
                # pronotepy 2.15.x converts even datetime arguments to midnight.
                # Fetch the following midnight, then retain only requested days.
                for lesson in client.lessons(today, end + timedelta(days=1)):
                    entry = days.get(str(lesson.start.date()))
                    if entry is not None:
                        entry["lessons"].append({
                            "start": lesson.start.strftime("%H:%M"),
                            "end": lesson.end.strftime("%H:%M"),
                            "subject": lesson.subject.name if lesson.subject else "",
                            "classroom": lesson.classroom or "",
                            "canceled": lesson.canceled, "status": lesson.status or "",
                        })
            with _phase("homework"):
                for homework in client.homework(today, end):
                    entry = days.get(str(homework.date))
                    if entry is not None:
                        entry["homework"].append({
                            "subject": homework.subject.name,
                            "description": homework.description, "done": homework.done})
            # A long-lived session may itself renew while collecting data.
            with _phase("credentials"):
                _save_credentials(config, client)
    with _phase("validation"):
        snapshot = _validate_snapshot({"days": days, "updated_at": time.time()})
    with _phase("cache"):
        _atomic_json(SNAPSHOT_PATH if cache_path is None else cache_path, snapshot)
    return snapshot


def load_snapshot(cache_path=None):
    try:
        with open(SNAPSHOT_PATH if cache_path is None else cache_path, encoding="utf-8") as stream:
            return _validate_snapshot(json.load(stream))
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        LOGGER.warning("Pronote cache could not be loaded; awaiting refresh.")
    return {"days": {}, "updated_at": None}


class PronoteService:
    """Expose independent snapshots while refreshing a replacement in background."""

    def __init__(self, config, cache_path=None):
        self.config = config
        self.cache_path = SNAPSHOT_PATH if cache_path is None else os.fspath(cache_path)
        self._lock = threading.Lock()
        self._snapshot = {"days": {}, "updated_at": None}
        self._error = None
        self._configured = config is not None and config.has_section("pronote")
        self.interval = 900
        self.days_ahead = 14
        self.display_date = str(date.today())
        self.next_refresh = 0
        self.thread = None
        self._configuration_error = False
        self._state = "loading" if self._configured else "unconfigured"
        if self._configured:
            self._snapshot = load_snapshot(self.cache_path)
            if self._snapshot["days"]:
                self._state = "cached"
            try:
                _credentials(config)
                section = config["pronote"]
                self.interval = max(60, section.getint("refresh_seconds", fallback=900))
                self.days_ahead = min(14, max(0, section.getint("days_ahead", fallback=14)))
                # Legacy display_date only controlled the old compact view.
                # A malformed/obsolete value must never disable synchronization.
                try:
                    self.display_date = date.fromisoformat(
                        section.get("display_date", fallback=str(date.today()))).isoformat()
                except (ValueError, TypeError, configparser.Error):
                    self.display_date = str(date.today())
            except (configparser.Error, ValueError, TypeError, KeyError, OverflowError):
                self._configuration_error = True
                self._state = "cached" if self._snapshot["days"] else "error"
                self._error = "Configuration Pronote invalide."
                LOGGER.warning("Pronote configuration is invalid; refresh disabled.")

    @property
    def snapshot(self):
        """Legacy read API; callers cannot mutate the published snapshot."""
        return self.get_snapshot()

    def get_snapshot(self):
        with self._lock:
            return copy.deepcopy(self._snapshot)

    def status(self):
        with self._lock:
            return {"state": self._state,
                    "last_success": self._snapshot.get("updated_at"),
                    "error": self._error}

    def refresh(self):
        with self._lock:
            if not self._configured or self._configuration_error or time.monotonic() < self.next_refresh:
                return
            if self.thread and self.thread.is_alive():
                return
            self.next_refresh = time.monotonic() + self.interval
            if not self._snapshot["days"]:
                self._state = "loading"
            self.thread = threading.Thread(target=self._refresh, daemon=True)
            self.thread.start()

    def _refresh(self):
        try:
            snapshot = _validate_snapshot(sync_range(self.config, self.days_ahead,
                                                     cache_path=self.cache_path))
        except Exception as exc:
            error = exc if isinstance(exc, PronoteSyncError) else PronoteSyncError("validation", exc)
            # Report only product stages/codes, never provider messages.
            LOGGER.warning("Pronote refresh failed stage=%s code=%s.",
                           error.stage, error.code)
            with self._lock:
                self.next_refresh = time.monotonic() + 60
                self._state = "cached" if self._snapshot["days"] else "error"
                self._error = str(error)
            return
        with self._lock:
            self._snapshot = snapshot
            self._state = "ready" if any(day["lessons"] or day["homework"]
                                          for day in snapshot["days"].values()) else "empty"
            self._error = None


def _write_config(config):
    directory = StaticConfiguration.config_directory_path
    os.makedirs(directory, mode=0o700, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix=".config-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            config.write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(path, StaticConfiguration.config_file_path)
    finally:
        if os.path.exists(path):
            os.unlink(path)
