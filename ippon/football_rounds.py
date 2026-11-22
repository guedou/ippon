# SPDX-License-Identifier: GPL-2.0+
"""Resolve missing Ligue 1 rounds from an offline, official season schedule.

The date identifies the season only. Fixture lookup uses the ordered home/away
pair, so a postponed fixture keeps its original round. Provider numbers always
win over the fallback. Other seasons/unknown pairs remain explicitly unknown.
"""

from datetime import date, datetime
from functools import lru_cache
import json
import logging
from pathlib import Path
import re
import unicodedata

LOG = logging.getLogger(__name__)
UNKNOWN_ROUND = 'Jour inconnu'


def _key(value):
    text = unicodedata.normalize('NFKD', str(value or '')).casefold()
    return ''.join(char for char in text if char.isascii() and char.isalnum())


# Explicit aliases seen in the source payload, plus official club names.
_TEAM_ALIASES = {
    'ANGERS SCO': ('Angers',),
    'AJ AUXERRE': ('Auxerre',),
    'STADE BRESTOIS 29': ('Stade Brestois', 'Brest'),
    'LE HAVRE': ('Le Havre AC', 'Havre AC'),
    'LE MANS FC': ('Le Mans',),
    'RC LENS': ('Lens',),
    'LOSC': ('Lille OSC', 'Lille'),
    'FC LORIENT': ('Lorient',),
    'OLYMPIQUE LYONNAIS': ('Lyon', 'OL'),
    'OLYMPIQUE DE MARSEILLE': ('Olympique Marseille', 'Marseille', 'OM'),
    'AS MONACO': ('Monaco',),
    'OGC NICE': ('Nice',),
    'PARIS FC': (),
    'PARIS SAINT-GERMAIN': ('Paris SG', 'PSG'),
    'STADE RENNAIS FC': ('Stade Rennais', 'Rennes'),
    'RC STRASBOURG ALSACE': ('RC Strasbourg', 'Strasbourg'),
    'TOULOUSE FC': ('Toulouse',),
    'ESTAC TROYES': ('Troyes',),
}
_ALIASES = {_key(alias): official for official, aliases in _TEAM_ALIASES.items()
            for alias in (official, *aliases)}


def round_number(value):
    if isinstance(value, bool):
        return None
    text = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode()
    found = re.fullmatch(r'\s*(?:(?:jour|journee)\s*#?\s*)?(\d+)\s*', text, re.I)
    return int(found[1]) if found and int(found[1]) > 0 else None


def is_ligue1(competition):
    return (_key(competition.get('name')) in
            {'ligue1', 'ligue1mcdonalds', 'ligue1ubereats'} or
            competition.get('source') == 'livescore'
            and str(competition.get('source_id')) == '68')


@lru_cache(maxsize=1)
def _official_schedule():
    path = Path(__file__).parent / 'assets' / 'schedules' / 'ligue1_2026.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if data['season_start'] != 2026 or set(data['rounds']) != {str(n) for n in range(1, 35)}:
            raise ValueError('invalid schedule')
        result = {}
        for number, pairs in data['rounds'].items():
            if len(pairs) != 9 or len({club for pair in pairs for club in pair}) != 18:
                raise ValueError('invalid matchday')
            for home, away in pairs:
                if home not in _TEAM_ALIASES or away not in _TEAM_ALIASES or (home, away) in result:
                    raise ValueError('invalid fixture')
                result[home, away] = int(number)
        if len(result) != 306:
            raise ValueError('incomplete schedule')
        return result
    except (OSError, ValueError, TypeError, KeyError):
        LOG.warning('Official Ligue 1 schedule unavailable; missing rounds remain unknown.')
        return {}


def official_round(home, away, season):
    """Return a proven round for the ordered pair in the supported season."""
    if str(season) != '2026':
        return None
    home, away = _ALIASES.get(_key(home)), _ALIASES.get(_key(away))
    return _official_schedule().get((home, away)) if home and away else None


def resolve_round(value, home, away, season):
    """Format an explicit provider number, otherwise use the official fallback."""
    number = round_number(value)
    if number is None and _key(value) in {'', 'regularseason', 'jourregularseason',
                                        'journeeregularseason', 'jourinconnu'}:
        number = official_round(home, away, season)
    return f'Jour {number}' if number is not None else UNKNOWN_ROUND


def _season(match):
    # Only identifies which season's fixture list to use, not a round by date.
    value = match.get('date')
    try:
        if isinstance(value, datetime):
            day = value.date()
        elif isinstance(value, date):
            day = value
        else:
            text = str(value)
            day = (datetime.strptime(text[:8], '%Y%m%d').date() if re.match(r'^\d{8}', text)
                   else date.fromisoformat(text[:10]))
        return day.year if day.month >= 7 else day.year - 1
    except (ValueError, TypeError):
        return None


def cached_round_label(match):
    """Repair legacy numeric labels and Ligue 1's mislabelled phase, in memory."""
    competition = match.get('competition', {})
    value = competition.get('level', '')
    number = round_number(value)
    if number is not None:
        return f'Jour {number}'
    if (_key(value) not in {'regularseason', 'jourregularseason',
                            'journeeregularseason', 'jourinconnu'} or not is_ligue1(competition)):
        return value
    teams = match.get('teams', [])
    if len(teams) != 2:
        return UNKNOWN_ROUND
    home = teams[0].get('team1', {}).get('name')
    away = teams[1].get('team2', {}).get('name')
    return resolve_round(None, home, away, _season(match))
