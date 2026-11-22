# SPDX-License-Identifier: GPL-2.0+
from collections import Counter
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from ippon.football_rounds import (UNKNOWN_ROUND, cached_round_label, official_round,
                                   resolve_round, round_number)


class OfficialRoundTests(unittest.TestCase):
    def test_official_schedule_is_a_complete_double_round_robin(self):
        asset = Path(__file__).parents[1] / 'ippon/assets/schedules/ligue1_2026.json'
        schedule = json.loads(asset.read_text())
        self.assertEqual(schedule['season_start'], 2026)
        self.assertEqual(len(schedule['rounds']), 34)
        pairs = []
        for number, fixtures in schedule['rounds'].items():
            with self.subTest(round=number):
                self.assertEqual(len(fixtures), 9)
                self.assertEqual(len({team for pair in fixtures for team in pair}), 18)
            pairs.extend(tuple(pair) for pair in fixtures)
        self.assertEqual(len(set(pairs)), 306)
        self.assertTrue(all((away, home) in pairs for home, away in pairs))
        self.assertEqual(set(Counter(home for home, _ in pairs).values()), {17})
        self.assertEqual(set(Counter(away for _, away in pairs).values()), {17})
        self.assertTrue(schedule['provenance']['announcement_url'].startswith('https://www.lfp.fr/'))

    def test_official_fixtures_from_first_middle_and_last_round(self):
        self.assertEqual(official_round('Olympique Marseille', 'RC Strasbourg', 2026), 1)
        self.assertEqual(official_round('ESTAC Troyes', 'Le Mans FC', 2026), 9)
        self.assertEqual(official_round('Stade Rennais', 'Paris Saint-Germain', 2026), 23)
        self.assertEqual(official_round('Olympique Lyonnais', 'Paris FC', 2026), 34)

    def test_direction_season_and_team_identity_are_not_guessed(self):
        self.assertEqual(official_round('Paris Saint-Germain', 'Stade Rennais', 2026), 1)
        self.assertEqual(official_round('Stade Rennais', 'Paris Saint-Germain', 2026), 23)
        self.assertIsNone(official_round('Paris', 'Stade Rennais', 2026))
        self.assertIsNone(official_round('Paris Saint-Germain', 'Stade Rennais', 2025))
        self.assertIsNone(official_round('Paris Saint-Germain', 'Stade Rennais', None))

    def test_provider_number_is_primary_and_missing_schedule_is_safe(self):
        self.assertEqual(resolve_round('12', 'Olympique Marseille', 'RC Strasbourg', 2026), 'Jour 12')
        self.assertEqual(resolve_round('Play-off', 'Olympique Marseille', 'RC Strasbourg', 2026), UNKNOWN_ROUND)
        self.assertEqual(resolve_round('Finale', 'Paris Saint-Germain', 'Stade Rennais', 2026), UNKNOWN_ROUND)
        with patch('ippon.football_rounds._official_schedule', return_value={}):
            self.assertEqual(resolve_round('Regular Season', 'Olympique Marseille', 'RC Strasbourg', 2026), UNKNOWN_ROUND)

    def test_legacy_cache_season_from_date_but_round_from_ordered_pair(self):
        source = {'date': '20270103',
                  'competition': {'name': 'Ligue 1', 'level': 'Jour #Regular Season'},
                  'teams': [{'team1': {'name': 'Olympique Marseille'}},
                            {'team2': {'name': 'RC Strasbourg'}}]}
        # A fixture moved to January still belongs to J1, not January's round.
        self.assertEqual(cached_round_label(source), 'Jour 1')
        source['date'] = '20280103'
        self.assertEqual(cached_round_label(source), UNKNOWN_ROUND)
        source['date'] = None
        self.assertEqual(cached_round_label(source), UNKNOWN_ROUND)

    def test_number_formats_and_non_numbers(self):
        for value in (1, '1', 'Jour 1', 'Jour #1', 'Journée 1'):
            self.assertEqual(round_number(value), 1)
        for value in (None, False, 'Regular Season', 'Jour #Regular Season', 'Finale', '0'):
            self.assertIsNone(round_number(value))


if __name__ == '__main__':
    unittest.main()
