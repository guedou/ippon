# SPDX-License-Identifier: GPL-2.0+
"""Data and navigation for the tactile viewer, independent of raylib.

Published score snapshots are replaced atomically; consumers must treat them as
read-only. ``last_success`` is a successful local read, never a claim that the
upstream provider was contacted. ``updated_at`` is the oldest loaded file mtime.
Neither timestamp supplies a missing match date.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time as daytime, timezone
import configparser
import gzip
import json
import math
from pathlib import Path
import re
import threading
import time
import zlib

from ippon.config import StaticConfiguration
from ippon.football_rounds import UNKNOWN_ROUND, cached_round_label


class ScoresService:
    """Refresh the on-disk score cache without blocking the rendering thread."""

    def __init__(self, config, directory=None, refresh_interval=15):
        self.directory = Path(directory or
                              StaticConfiguration.config_competitions_directory_path)
        # The viewer needs a cache filename, not the synchronizer's source,
        # season, or credentials. One broken section must not suppress others.
        self.names = []
        self._configuration_errors = []
        for section in config.sections() if config is not None else []:
            if not section.startswith('competition.'):
                continue
            try:
                name = config.get(section, 'name', raw=True)
                if not isinstance(name, str) or not name.strip():
                    raise ValueError('missing competition name')
                if name not in self.names:
                    self.names.append(name)
            except (configparser.Error, ValueError, TypeError):
                self._configuration_errors.append(f'{section} : nom absent ou invalide')
        self.refresh_interval = max(0, refresh_interval)
        self._lock = threading.Lock()
        self._snapshot = {'competitions': {name: {} for name in self.names},
                          'updated_at': None}
        self._state = ('loading' if self.names else
                       'error' if self._configuration_errors else 'unconfigured')
        self._last_success = None
        self._error = '; '.join(self._configuration_errors) or None
        self._next_refresh = 0
        self._records = {}
        self.thread = None

    @property
    def snapshot(self):
        return self.get_snapshot()

    def get_snapshot(self):
        """Return the current, read-only-by-contract snapshot in constant time."""
        with self._lock:
            return self._snapshot

    def status(self):
        with self._lock:
            return {'state': self._state, 'last_success': self._last_success,
                    'error': self._error,
                    'cache_updated_at': self._snapshot['updated_at']}

    def refresh(self, force=False):
        """Schedule at most one worker; a failed read retains previous data."""
        with self._lock:
            if not self.names:
                return
            if self.thread is not None and self.thread.is_alive():
                return
            if not force and time.monotonic() < self._next_refresh:
                return
            self._next_refresh = time.monotonic() + self.refresh_interval
            self.thread = threading.Thread(target=self._refresh, daemon=True,
                                           name='ippon-scores')
            self.thread.start()

    def _refresh(self):
        errors = list(self._configuration_errors)
        did_read = False
        for name in self.names:
            path = self.directory / f'{name}.json.gz'
            try:
                stat = path.stat()
                fingerprint = (stat.st_mtime_ns, stat.st_size)
                previous = self._records.get(name)
                if previous is not None and previous['fingerprint'] == fingerprint:
                    continue
                with gzip.open(path, 'rt', encoding='utf-8') as stream:
                    rounds = _group_matches(json.load(stream))
                # An updater can replace a file while it is being read. Retry
                # next time instead of publishing data with the wrong mtime.
                after = path.stat()
                if (after.st_mtime_ns, after.st_size) != fingerprint:
                    raise OSError('cache modifié pendant la lecture')
                self._records[name] = {'rounds': rounds, 'mtime': stat.st_mtime,
                                       'fingerprint': fingerprint}
                did_read = True
            except FileNotFoundError:
                # A never-built competition is an empty configuration entry.
                # A disappeared cache is an error; keep its previous snapshot.
                if name in self._records:
                    errors.append(f'{name} : cache absent')
            except (OSError, ValueError, TypeError, KeyError, EOFError, zlib.error):
                errors.append(f'{name} : cache illisible ou invalide')

        competitions = {name: self._records.get(name, {}).get('rounds', {})
                        for name in self.names}
        mtimes = [record['mtime'] for record in self._records.values()]
        has_matches = any(matches for rounds in competitions.values()
                          for matches in rounds.values())
        with self._lock:
            self._snapshot = {'competitions': competitions,
                              'updated_at': min(mtimes) if mtimes else None}
            self._error = '; '.join(errors) or None
            if not errors and did_read:
                self._last_success = time.time()
            # Reading a file does not prove the upstream network is healthy.
            self._state = ('cached' if has_matches else
                           'error' if errors else 'empty')
            if errors:
                self._next_refresh = min(self._next_refresh,
                                         time.monotonic() + 5)


def _group_matches(payload):
    if not isinstance(payload, list):
        raise ValueError('expected a list of matchdays')
    rounds = {}
    for batch in payload:
        # The builder writes matchday lists; accepting a flat list also keeps
        # this reader compatible with a direct converter export.
        games = batch if isinstance(batch, list) else [batch]
        for match in games:
            if not isinstance(match, dict):
                raise ValueError('invalid match')
            level = match['competition']['level']
            teams = match['teams']
            if (not isinstance(level, str) or not isinstance(teams, list)
                    or len(teams) != 2):
                raise ValueError('invalid competition or teams')
            for side, team in enumerate(teams, 1):
                if (not isinstance(team, dict)
                        or not isinstance(team.get(f'team{side}'), dict)):
                    raise ValueError('invalid team')
                # Old caches may omit scores/goals; preserve that uncertainty.
                # Explicit malformed values must not reach the drawing loop.
                score = team.get('score')
                if score is not None and _goal_count(score) is None:
                    raise ValueError('invalid score')
                goals = team.get('goals')
                if goals is not None:
                    if not isinstance(goals, list):
                        raise ValueError('invalid goals')
                    for goal in goals:
                        if (not isinstance(goal, (list, tuple))
                                or len(goal) not in (2, 3)
                                or goal[0] is not None and not isinstance(goal[0], str)
                                or goal[1] is not None and not isinstance(goal[1], (str, int))
                                or len(goal) == 3 and goal[2] is not None
                                and not isinstance(goal[2], str)):
                            raise ValueError('invalid goal')
            normalized = cached_round_label(match)
            if normalized != level:
                match = {**match, 'competition': {**match['competition'], 'level': normalized}}
            rounds.setdefault(normalized, []).append(match)
    return rounds


@dataclass
class NavigationState:
    page: str = 'home'
    school_section: str = 'courses'
    selected_day: str | None = None
    competition: str | None = None
    round: str | None = None
    match_index: int = 0
    school_pages: dict = field(default_factory=lambda: {'courses': 0, 'homework': 0})
    detail: str | None = None
    detail_index: int = 0
    detail_page: int = 0
    panel: str | None = None
    panel_page: int = 0
    sources: bool = False
    auto: str = 'off'
    show_school_home: bool = True
    _last_rotation: float | None = field(default=None, repr=False)

    def navigate(self, page):
        if page not in {'home', 'football', 'school', 'options'}:
            raise ValueError(f'Unknown page: {page}')
        self.page = page
        self.detail = self.panel = None
        self.detail_page = self.panel_page = 0
        self.sources = False

    def back(self):
        if self.panel is not None:
            self.panel = None
            self.panel_page = 0
        elif self.sources:
            self.sources = False
        elif self.detail is not None:
            self.detail = None
            self.detail_page = 0
        elif self.page == 'options':
            self.navigate('home')
        else:
            return False
        return True

    def interact(self):
        """Pause rotation on every input. Resuming always requires an action."""
        if self.auto == 'running':
            self.auto = 'paused'

    def set_auto(self, enabled, now=None):
        self.auto = 'running' if enabled else 'off'
        self._last_rotation = time.monotonic() if now is None else now
        if enabled:
            self.navigate('home')

    def tick(self, now, delay=12):
        """Rotate once when due; ``now`` must use a monotonic clock."""
        if self.auto != 'running' or self.panel or self.detail or self.sources:
            return False
        if self._last_rotation is None:
            self._last_rotation = now
            return False
        if now - self._last_rotation < delay:
            return False
        pages = ['home', 'football', 'school'] if self.show_school_home else ['home', 'football']
        current = pages.index(self.page) if self.page in pages else -1
        self.navigate(pages[(current + 1) % len(pages)])
        self._last_rotation = now
        return True


def sorted_rounds(rounds):
    """Sort numbered matchdays, but preserve cache chronology for cup phases."""
    known = [value for value in rounds if value != UNKNOWN_ROUND]
    if not all(re.fullmatch(r'Jour(?:née)?\s*#?\s*\d+', str(value), re.IGNORECASE)
               for value in known):
        return list(rounds)
    def key(value):
        return tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                     for part in re.split(r'(\d+)', str(value)))
    return sorted(rounds, key=lambda value: (value != UNKNOWN_ROUND, key(value)))


def _match_datetime(value):
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, date):
        result = datetime.combine(value, daytime())
    elif value is None:
        return None
    else:
        raw = str(value).strip()
        try:
            if re.fullmatch(r'\d{8}', raw):
                result = datetime.strptime(raw, '%Y%m%d')
            elif re.fullmatch(r'\d{14}', raw):
                result = datetime.strptime(raw, '%Y%m%d%H%M%S')
            else:
                result = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        except ValueError:
            return None
    return result


def latest_match(competitions, competition=None):
    """Find a match using its explicit date, never filesystem order or mtime."""
    choices = ([competitions.get(competition, {})] if competition else
               competitions.values())
    dated = []
    for rounds in choices:
        for matches in rounds.values():
            for match in matches:
                match_date = _match_datetime(match.get('date'))
                if match_date is not None:
                    if match_date.tzinfo is not None:
                        match_date = match_date.astimezone(timezone.utc).replace(tzinfo=None)
                    dated.append((match_date, match))
    return max(dated, key=lambda item: item[0])[1] if dated else None


def school_date(snapshot, today, now=None):
    """Choose the day containing the next non-cancelled lesson, or a loaded day.

    With no future lesson, prefer the next loaded date, then today, then the
    latest past date. This handles weekends/holidays without inventing lessons.
    """
    if isinstance(today, datetime):
        today = today.date()
    today = today.isoformat() if isinstance(today, date) else str(today)
    if isinstance(now, datetime):
        clock = now.time()
    elif isinstance(now, daytime):
        clock = now
    elif isinstance(now, str):
        clock = daytime.fromisoformat(now)
    else:
        clock = datetime.now().time()
    days = snapshot.get('days', {})
    keys = sorted(day for day in days if _match_datetime(day) is not None)
    for day in keys:
        if day < today:
            continue
        for lesson in sorted(days[day].get('lessons', []),
                             key=lambda item: item.get('start', '')):
            if lesson.get('canceled'):
                continue
            try:
                start = daytime.fromisoformat(lesson.get('start', ''))
            except ValueError:
                continue
            if day > today or start >= clock:
                return day
    future = next((day for day in keys if day > today), None)
    return future or (today if today in days else keys[-1] if keys else None)


def _goal_count(value):
    """Return a reliable nonnegative integer, or None for unknown/bad input."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if math.isfinite(value) and value.is_integer() and value >= 0 else None
    if isinstance(value, str) and re.fullmatch(r'\d+', value.strip()):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def all_goals(match):
    """Return known scorers, plus explicit sentinels for missing goal details.

    A sentinel has ``kind='missing'`` and is distinct from a true zero-goal team.
    Goal records retain the scoring team's identity, including own goals.
    """
    result = []
    for side, item in enumerate(match.get('teams', []), 1):
        team = item.get(f'team{side}', {})
        known = []
        records = item.get('goals')
        records = records if isinstance(records, (list, tuple)) else []
        for goal in records:
            if isinstance(goal, (list, tuple)) and goal and goal[0]:
                known.append({'name': str(goal[0]),
                              'minute': str(goal[1] or '') if len(goal) > 1 else '',
                              'kind': goal[2] if len(goal) > 2 else None,
                              'team': team})
        result.extend(known)
        count = _goal_count(item.get('score'))
        missing = count > len(known) if count is not None else not known
        if missing:
            result.append({'name': 'Buteurs non fournis', 'minute': '',
                           'kind': 'missing', 'team': team})

    def minute_key(goal):
        numbers = re.findall(r'\d+', goal['minute'])
        return (int(numbers[0]), int(numbers[1]) if len(numbers) > 1 else 0) if numbers else (10000, 0)
    return sorted(result, key=minute_key)


def format_match_date(value):
    """Format an explicit match date in French without manufacturing an hour."""
    parsed = _match_datetime(value)
    if parsed is None:
        return 'Date non fournie'
    months = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.',
              'août', 'sept.', 'oct.', 'nov.', 'déc.']
    return f'{parsed.day} {months[parsed.month - 1]} {parsed.year}'
