# SPDX-License-Identifier: GPL-2.0+

import json
import os
import tempfile
import threading
import time
from datetime import date, timedelta

import pronotepy

from ippon.config import StaticConfiguration

SNAPSHOT_PATH = os.path.join(
    StaticConfiguration.config_data_directory_path, "pronote", "schedule.json"
)


def sync_range(config, days_ahead=14):
    """Fetch PRONOTE lessons and homework from today through ``days_ahead``."""
    credentials = {
        key: value.strip().strip('"') for key, value in config["pronote"].items()
        if key not in {"refresh_seconds", "days_ahead"}
    }
    client_class = (pronotepy.ParentClient
                    if "parent.html" in credentials["pronote_url"]
                    else pronotepy.Client)
    client = client_class.token_login(**credentials)
    if not client.logged_in:
        raise RuntimeError("PRONOTE login failed")

    today = date.today()
    end = today + timedelta(days=min(max(days_ahead, 0), 14))
    days = {str(today + timedelta(days=offset)): {"lessons": [], "homework": []}
            for offset in range((end - today).days + 1)}
    for lesson in client.lessons(today, end):
        entry = days.get(str(lesson.start.date()))
        if entry is not None:
            entry["lessons"].append({
                "start": lesson.start.strftime("%H:%M"),
                "end": lesson.end.strftime("%H:%M"),
                "subject": lesson.subject.name if lesson.subject else "",
                "classroom": lesson.classroom or "",
                "canceled": lesson.canceled,
                "status": lesson.status or "",
            })
    for homework in client.homework(today, end):
        entry = days.get(str(homework.date))
        if entry is not None:
            entry["homework"].append({
                "subject": homework.subject.name,
                "description": homework.description,
                "done": homework.done,
            })

    for entry in days.values():
        entry["lessons"].sort(key=lambda lesson: lesson["start"])

    snapshot = {"days": days}
    os.makedirs(os.path.dirname(SNAPSHOT_PATH), exist_ok=True)
    with open(SNAPSHOT_PATH, "w", encoding="utf-8") as fd:
        json.dump(snapshot, fd, ensure_ascii=False)
    os.chmod(SNAPSHOT_PATH, 0o600)
    config["pronote"].update(client.export_credentials())
    _write_config(config)
    return snapshot


def load_snapshot():
    try:
        with open(SNAPSHOT_PATH, encoding="utf-8") as fd:
            return json.load(fd)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"days": {}}


class PronoteService:
    def __init__(self, config):
        self.config = config
        section = config["pronote"]
        self.interval = max(60, section.getint("refresh_seconds", fallback=900))
        self.days_ahead = min(14, max(0, section.getint("days_ahead", fallback=14)))
        self.display_date = section.get("display_date", fallback=str(date.today()))
        self.snapshot = load_snapshot()
        self.next_refresh = 0
        self.thread = None

    def refresh(self):
        if time.monotonic() < self.next_refresh or (self.thread and self.thread.is_alive()):
            return
        self.next_refresh = time.monotonic() + self.interval
        self.thread = threading.Thread(target=self._refresh, daemon=True)
        self.thread.start()

    def _refresh(self):
        try:
            self.snapshot = sync_range(self.config, self.days_ahead)
        except (KeyError, RuntimeError, ValueError,
                pronotepy.exceptions.PronoteAPIError):
            self.next_refresh = time.monotonic() + 60


def _write_config(config):
    fd, path = tempfile.mkstemp(dir=StaticConfiguration.config_directory_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temporary:
            config.write(temporary)
        os.chmod(path, 0o600)
        os.replace(path, StaticConfiguration.config_file_path)
    finally:
        if os.path.exists(path):
            os.unlink(path)
