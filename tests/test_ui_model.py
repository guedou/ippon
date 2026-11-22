# SPDX-License-Identifier: GPL-2.0+
import configparser
from datetime import date, datetime
import gzip
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import zlib
from unittest.mock import patch

from ippon.ui_model import (NavigationState, ScoresService, all_goals,
                            format_match_date, latest_match, school_date,
                            sorted_rounds)


def match(day='20261121', level='Jour 12', score=(2, 1)):
    return {'sport': 'Football', 'date': day,
            'competition': {'name': 'Ligue 1', 'level': level},
            'teams': [{'team1': {'name': 'Paris', 'logo': 'paris.png'},
                       'score': score[0], 'goals': [['A', '12’', None], ['B', '90’ +8', 'sp']]},
                      {'team2': {'name': 'Lyon', 'logo': 'lyon.png'},
                       'score': score[1], 'goals': [['C', '54’', 'csc']]}]}


class ScoresServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.config = configparser.ConfigParser()
        self.config.read_dict({'competition.ligue1': {'name': 'Ligue 1', 'year': '2026'},
                               'competition.other': {'name': 'Autre', 'year': '2026'}})
        self.service = ScoresService(self.config, self.directory, refresh_interval=0)

    def write(self, name, data):
        path = self.directory / f'{name}.json.gz'
        with gzip.open(path, 'wt', encoding='utf-8') as stream:
            json.dump(data, stream)
        return path

    def refresh(self):
        self.service.refresh(force=True)
        self.service.thread.join(timeout=3)
        self.assertFalse(self.service.thread.is_alive())

    def test_full_matches_preserved_with_empty_configured_competition(self):
        source = match()
        path = self.write('Ligue 1', [[source]])
        os.utime(path, (1000, 1000))
        self.refresh()
        snapshot = self.service.get_snapshot()
        self.assertEqual(snapshot['competitions']['Ligue 1']['Jour 12'], [source])
        self.assertEqual(snapshot['competitions']['Autre'], {})
        self.assertEqual(snapshot['updated_at'], 1000)
        status = self.service.status()
        self.assertEqual(status['state'], 'cached')
        self.assertGreater(status['last_success'], 1000)
        self.assertEqual(status['cache_updated_at'], 1000)

    def test_malformed_score_or_goals_isolate_competition(self):
        invalid_values = [('score', True), ('score', float('inf')),
                          ('score', -1), ('score', {}), ('score', 'bad'),
                          ('goals', 7), ('goals', {}), ('goals', 'scorer'),
                          ('goals', [['Only a name']]),
                          ('goals', [['Scorer', '12', {}]]),
                          ('goals', [[{}, '12', None]])]
        self.write('Autre', [[match()]])
        for field, value in invalid_values:
            with self.subTest(field=field, value=value):
                source = match()
                source['teams'][0][field] = value
                self.write('Ligue 1', [[source]])
                self.refresh()
                self.assertEqual(self.service.snapshot['competitions']['Ligue 1'], {})
                self.assertTrue(self.service.snapshot['competitions']['Autre'])
                self.assertIn('Ligue 1', self.service.status()['error'])

    def test_legacy_missing_score_and_two_field_goals_are_preserved(self):
        source = match()
        source['teams'][0].pop('score')
        source['teams'][0]['goals'] = [['A', None], ['B', '90’ +8', 'sp']]
        source['teams'][1]['score'] = '1'
        self.write('Ligue 1', [[source]])
        self.refresh()
        self.assertEqual(self.service.snapshot['competitions']['Ligue 1']['Jour 12'], [source])
        self.assertIsNone(self.service.status()['error'])

    def test_legacy_regular_season_cache_repaired_in_memory_by_fixture(self):
        first = match(day='20260821', level='Jour #Regular Season')
        first['competition']['name'] = "Ligue 1 McDonald's"
        first['teams'][0]['team1']['name'] = 'Olympique Marseille'
        first['teams'][1]['team2']['name'] = 'RC Strasbourg'
        tenth = match(day='20261106', level='Jour #Regular Season')
        tenth['teams'][0]['team1']['name'] = 'Toulouse FC'
        tenth['teams'][1]['team2']['name'] = 'RC Strasbourg'
        path = self.write('Ligue 1', [[first, tenth]])
        before = path.read_bytes()
        self.refresh()
        rounds = self.service.snapshot['competitions']['Ligue 1']
        self.assertEqual(set(rounds), {'Jour 1', 'Jour 10'})
        self.assertEqual(rounds['Jour 1'][0]['competition']['level'], 'Jour 1')
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(first['competition']['level'], 'Jour #Regular Season')

    def test_legacy_unknown_round_not_applied_to_other_competition(self):
        source = match(level='Jour #Regular Season')
        source['competition']['name'] = 'Premier League'
        source['teams'][0]['team1']['name'] = 'Olympique Marseille'
        source['teams'][1]['team2']['name'] = 'RC Strasbourg'
        self.write('Ligue 1', [[source]])
        self.refresh()
        self.assertIn('Jour #Regular Season', self.service.snapshot['competitions']['Ligue 1'])

    def test_legacy_numbered_label_is_uniform_without_hash(self):
        source = match(level='Jour #1')
        self.write('Ligue 1', [[source]])
        self.refresh()
        self.assertIn('Jour 1', self.service.snapshot['competitions']['Ligue 1'])

    def test_date_never_filled_from_file_mtime(self):
        source = match()
        source.pop('date')
        self.write('Ligue 1', [[source]])
        self.refresh()
        stored = self.service.snapshot['competitions']['Ligue 1']['Jour 12'][0]
        self.assertNotIn('date', stored)
        self.assertIsNone(latest_match(self.service.snapshot['competitions']))

    def test_partial_corruption_retains_previous_competition_and_time(self):
        original = match()
        path = self.write('Ligue 1', [[original]])
        self.refresh()
        previous_success = self.service.status()['last_success']
        path.write_bytes(b'not a gzip file')
        other = match('20261122')
        self.write('Autre', [[other]])
        self.refresh()
        self.assertEqual(self.service.snapshot['competitions']['Ligue 1']['Jour 12'], [original])
        self.assertEqual(self.service.snapshot['competitions']['Autre']['Jour 12'], [other])
        self.assertEqual(self.service.status()['last_success'], previous_success)
        self.assertEqual(self.service.status()['state'], 'cached')
        self.assertIn('Ligue 1', self.service.status()['error'])

    def test_corrupt_competition_does_not_prevent_others(self):
        self.write('Ligue 1', {'not': 'the expected shape'})
        self.write('Autre', [[match()]])
        self.refresh()
        self.assertEqual(self.service.snapshot['competitions']['Ligue 1'], {})
        self.assertTrue(self.service.snapshot['competitions']['Autre'])
        self.assertEqual(self.service.status()['state'], 'cached')
        self.assertIsNotNone(self.service.status()['error'])

    def test_changed_file_is_reloaded_and_old_snapshot_not_mutated(self):
        self.write('Ligue 1', [[match()]])
        self.refresh()
        before = self.service.snapshot
        changed = match('20261122', score=(4, 1))
        self.write('Ligue 1', [[changed]])
        self.refresh()
        self.assertEqual(before['competitions']['Ligue 1']['Jour 12'][0]['date'], '20261121')
        self.assertEqual(self.service.snapshot['competitions']['Ligue 1']['Jour 12'][0], changed)

    def test_absent_or_empty_cache_is_empty(self):
        self.refresh()
        self.assertEqual(self.service.status()['state'], 'empty')
        self.assertIsNone(self.service.status()['last_success'])
        self.write('Ligue 1', [])
        self.refresh()
        self.assertEqual(self.service.status()['state'], 'empty')
        self.assertIsNotNone(self.service.status()['last_success'])

    def test_damaged_deflate_stream_is_isolated(self):
        self.write('Ligue 1', [[match()]])
        self.write('Autre', [[match()]])
        original_open = gzip.open

        def broken(path, *args, **kwargs):
            if Path(path).name == 'Ligue 1.json.gz':
                raise zlib.error('invalid compressed stream')
            return original_open(path, *args, **kwargs)

        with patch('ippon.ui_model.gzip.open', side_effect=broken):
            self.refresh()
        self.assertEqual(self.service.snapshot['competitions']['Ligue 1'], {})
        self.assertTrue(self.service.snapshot['competitions']['Autre'])
        self.assertIn('Ligue 1', self.service.status()['error'])

    def test_first_corruption_is_error_then_recovers(self):
        path = self.directory / 'Ligue 1.json.gz'
        path.write_bytes(b'corrupt')
        self.refresh()
        self.assertEqual(self.service.status()['state'], 'error')
        self.assertIsNone(self.service.status()['last_success'])
        self.write('Ligue 1', [[match()]])
        self.refresh()
        self.assertEqual(self.service.status()['state'], 'cached')
        self.assertIsNone(self.service.status()['error'])

    def test_cache_disappearance_retains_last_data_and_success(self):
        path = self.write('Ligue 1', [[match()]])
        self.refresh()
        previous = self.service.status()['last_success']
        path.unlink()
        self.refresh()
        self.assertTrue(self.service.snapshot['competitions']['Ligue 1'])
        self.assertEqual(self.service.status()['last_success'], previous)
        self.assertIn('cache absent', self.service.status()['error'])

    def test_oldest_cache_mtime_reported_and_no_false_read_refresh(self):
        path = self.write('Ligue 1', [[match()]])
        other = self.write('Autre', [[match()]])
        os.utime(path, (1000, 1000))
        os.utime(other, (2000, 2000))
        self.refresh()
        previous = self.service.status()['last_success']
        self.refresh()
        self.assertEqual(self.service.snapshot['updated_at'], 1000)
        self.assertEqual(self.service.status()['last_success'], previous)

    def test_cache_reader_accepts_name_without_sync_configuration(self):
        config = configparser.ConfigParser(interpolation=None)
        config.read_dict({'competition.minimal': {'name': 'Ligue 1'},
                          'pronote': {'username': 'unused'}})
        self.service = ScoresService(config, self.directory, refresh_interval=0)
        self.write('Ligue 1', [[match()]])
        self.refresh()
        self.assertEqual(self.service.status()['state'], 'cached')
        self.assertTrue(self.service.snapshot['competitions']['Ligue 1'])

    def test_missing_competition_name_does_not_suppress_good_section(self):
        self.config.add_section('competition.bad')
        self.config.add_section('competition.blank')
        self.config.set('competition.blank', 'name', '')
        self.service = ScoresService(self.config, self.directory, refresh_interval=0)
        self.write('Ligue 1', [[match()]])
        self.refresh()
        self.assertTrue(self.service.snapshot['competitions']['Ligue 1'])
        self.assertEqual(self.service.status()['state'], 'cached')
        self.assertIn('competition.bad', self.service.status()['error'])
        self.assertIn('competition.blank', self.service.status()['error'])

    def test_all_competitions_invalid_reports_configuration_error(self):
        config = configparser.ConfigParser()
        config.add_section('competition.bad')
        service = ScoresService(config, self.directory)
        service.refresh()
        self.assertEqual(service.status()['state'], 'error')
        self.assertIn('competition.bad', service.status()['error'])
        self.assertIsNone(service.thread)

    def test_unconfigured_no_worker(self):
        service = ScoresService(configparser.ConfigParser(), self.directory)
        service.refresh()
        self.assertEqual(service.status()['state'], 'unconfigured')
        self.assertIsNone(service.thread)

    def test_worker_does_not_block_or_duplicate(self):
        self.write('Ligue 1', [[match()]])
        started, release = threading.Event(), threading.Event()
        from ippon.ui_model import _group_matches

        def slow(payload):
            started.set()
            release.wait(timeout=3)
            return _group_matches(payload)

        with patch('ippon.ui_model._group_matches', side_effect=slow):
            self.service.refresh()
            worker = self.service.thread
            try:
                self.assertTrue(started.wait(timeout=2))
                self.service.refresh(force=True)
                self.assertIs(self.service.thread, worker)
                self.assertEqual(self.service.snapshot['competitions']['Ligue 1'], {})
            finally:
                release.set()
                worker.join(timeout=3)
        self.assertFalse(worker.is_alive())


class NavigationTests(unittest.TestCase):
    def test_back_closes_only_top_layer(self):
        state = NavigationState(detail='homework', sources=True, panel='day')
        self.assertTrue(state.back())
        self.assertIsNone(state.panel)
        self.assertTrue(state.sources)
        self.assertTrue(state.back())
        self.assertFalse(state.sources)
        self.assertEqual(state.detail, 'homework')
        self.assertTrue(state.back())
        self.assertIsNone(state.detail)
        self.assertFalse(state.back())

    def test_interaction_pauses_until_explicit_resume(self):
        state = NavigationState()
        state.set_auto(True, now=0)
        self.assertTrue(state.tick(12))
        self.assertEqual(state.page, 'football')
        state.interact()
        self.assertEqual(state.auto, 'paused')
        self.assertFalse(state.tick(10000))
        self.assertEqual(state.page, 'football')
        state.set_auto(True, now=10000)
        self.assertEqual(state.page, 'home')
        self.assertFalse(state.tick(10011))
        self.assertTrue(state.tick(10012))

    def test_navigation_clears_overlays_but_preserves_school_position(self):
        state = NavigationState(panel='day', detail='goals', sources=True,
                                selected_day='2026-11-23')
        state.school_pages['courses'] = 3
        state.navigate('school')
        self.assertIsNone(state.panel)
        self.assertIsNone(state.detail)
        self.assertFalse(state.sources)
        self.assertEqual(state.selected_day, '2026-11-23')
        self.assertEqual(state.school_pages['courses'], 3)

    def test_auto_privacy_skips_school_and_no_idle_auto_restart(self):
        state = NavigationState(show_school_home=False)
        state.set_auto(True, now=0)
        state.tick(12)
        self.assertEqual(state.page, 'football')
        state.tick(24)
        self.assertEqual(state.page, 'home')
        state.set_auto(False, now=24)
        self.assertFalse(state.tick(100))
        self.assertEqual(state.auto, 'off')

    def test_dataclass_mutable_state_is_not_shared(self):
        left, right = NavigationState(), NavigationState()
        left.school_pages['courses'] = 4
        self.assertEqual(right.school_pages['courses'], 0)


class HelperTests(unittest.TestCase):
    def test_unknown_round_does_not_hide_latest_numbered_round(self):
        self.assertEqual(sorted_rounds({'Jour inconnu': [], 'Jour 10': [], 'Jour 2': []}),
                         ['Jour inconnu', 'Jour 2', 'Jour 10'])

    def test_cup_rounds_preserve_chronological_cache_order(self):
        rounds = ['Quarts de finale', 'Demi-finales', 'Finale']
        self.assertEqual(sorted_rounds(rounds), rounds)

    def test_mixed_group_and_knockout_rounds_keep_order(self):
        rounds = ['Jour #1', 'Jour #2', 'Demi-finales', 'Finale']
        self.assertEqual(sorted_rounds(rounds), rounds)

    def test_rounds_natural_sort(self):
        self.assertEqual(sorted_rounds({'Jour #10': [], 'Jour #2': [], 'Jour #1': []}),
                         ['Jour #1', 'Jour #2', 'Jour #10'])

    def test_latest_match_uses_real_date_across_rounds_and_competitions(self):
        older, newer = match('20261120'), match('20261122')
        missing = match(None)
        competitions = {'A': {'Jour #99': [older, missing]}, 'B': {'Jour #1': [newer]}}
        self.assertIs(latest_match(competitions), newer)
        self.assertIs(latest_match(competitions, 'A'), older)
        self.assertIsNone(latest_match({'A': {'X': [missing]}}))

    def test_latest_match_mixed_aware_and_naive_dates(self):
        older, newer = match('2026-11-21T21:00:00+01:00'), match('20261122210000')
        self.assertIs(latest_match({'A': {'X': [newer, older]}}), newer)

    def test_formatter_never_invents_a_date_or_time(self):
        self.assertEqual(format_match_date('20261121'), '21 nov. 2026')
        self.assertEqual(format_match_date('2026-11-21'), '21 nov. 2026')
        self.assertEqual(format_match_date(None), 'Date non fournie')
        self.assertEqual(format_match_date('invalid'), 'Date non fournie')
        self.assertEqual(format_match_date('2026-11-21T00:30:00+02:00'), '21 nov. 2026')

    def test_school_day_ignores_cancelled_and_past_lessons(self):
        data = {'days': {'2026-11-22': {'lessons': [
            {'start': '08:30', 'canceled': False}, {'start': '16:00', 'canceled': True}]},
            '2026-11-23': {'lessons': [{'start': '08:30', 'canceled': False}]}}}
        self.assertEqual(school_date(data, date(2026, 11, 22), '09:00'), '2026-11-23')
        data['days']['2026-11-22']['lessons'].append({'start': '10:00', 'canceled': False})
        self.assertEqual(school_date(data, '2026-11-22', datetime(2026, 11, 22, 9)), '2026-11-22')

    def test_school_empty_future_day_and_no_data(self):
        data = {'days': {'2026-11-22': {'lessons': []}, '2026-11-23': {'lessons': []}}}
        self.assertEqual(school_date(data, '2026-11-22', '09:00'), '2026-11-23')
        self.assertIsNone(school_date({'days': {}}, '2026-11-22', '09:00'))

    def test_goals_chronological_preserve_own_goals_and_added_time(self):
        goals = all_goals(match())
        self.assertEqual([goal['name'] for goal in goals], ['A', 'C', 'B'])
        self.assertEqual(goals[1]['kind'], 'csc')
        self.assertEqual(goals[1]['team']['name'], 'Lyon')
        self.assertEqual(goals[2]['minute'], '90’ +8')

    def test_unknown_scores_are_not_a_zero_goal_match(self):
        source = match()
        for team in source['teams']:
            team.pop('score')
            team.pop('goals')
        goals = all_goals(source)
        self.assertEqual([goal['kind'] for goal in goals], ['missing', 'missing'])
        # The helper stays defensive even if called outside the score service.
        for value in (7, {}, 'bad'):
            source['teams'][0]['goals'] = value
            self.assertEqual(all_goals(source)[0]['kind'], 'missing')
        source['teams'][0]['score'] = float('inf')
        self.assertEqual(all_goals(source)[0]['kind'], 'missing')

    def test_missing_goals_distinct_from_zero_and_partial_lists(self):
        source = match(score=(2, 0))
        source['teams'][0]['goals'] = None
        source['teams'][1]['goals'] = []
        goals = all_goals(source)
        self.assertEqual(len(goals), 1)
        self.assertEqual(goals[0]['kind'], 'missing')
        self.assertEqual(goals[0]['team']['name'], 'Paris')
        source['teams'][0]['goals'] = [['A', '10’', None]]
        self.assertEqual([goal['kind'] for goal in all_goals(source)], [None, 'missing'])
        source['teams'][0]['score'] = 0
        source['teams'][0]['goals'] = []
        self.assertEqual(all_goals(source), [])


if __name__ == '__main__':
    unittest.main()
