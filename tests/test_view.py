# SPDX-License-Identifier: GPL-2.0+
"""Interaction and content regressions; no graphics context or raylib import.

Fake font metrics deliberately test preservation and pagination, not whether a
real typeface fits a physical screen. Native screenshots cover that separately.
"""
from collections import OrderedDict
from copy import deepcopy
from datetime import date, datetime
import gzip
import json
from pathlib import Path
import re
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from ippon.demo import SCENARIOS
from ippon.view import Painter, PointerTracker, Viewer, plain_text, wrap_pixels, window_logic


class FakePainter:
    def __init__(self):
        self.buttons = []
        self.pressed = None
        self.texts = []
        self.text_calls = []
        self.r = SimpleNamespace(clear_background=Mock(), draw_line=Mock(), draw_circle=Mock())

    def color(self, value):
        return value

    def measure(self, text, size, bold=False):
        return len(str(text)) * size / 2

    def text(self, text, *args, **kwargs):
        self.texts.append(str(text))
        self.text_calls.append((str(text), args, kwargs))

    lines = Painter.lines

    def card(self, *args, **kwargs):
        pass

    def logo(self, *args, **kwargs):
        pass

    def icon(self, *args, **kwargs):
        pass

    def button(self, box, label, action, value=None, primary=False,
               disabled=False, sub=None, icon=None, align='center'):
        self.buttons.append((box, action, value, disabled))
        if label:
            self.texts.append(label)
        if sub:
            self.texts.append(sub)

    def close(self):
        pass


class PointerTests(unittest.TestCase):
    def setUp(self):
        self.pointer = PointerTracker()
        self.buttons = [((0, 0, 100, 80), 'nav', 'home', False),
                        ((100, 0, 100, 80), 'nav', 'school', False)]

    def update(self, x, down, y=40, buttons=None):
        return self.pointer.update((x, y), down,
                                   self.buttons if buttons is None else buttons)

    def test_only_release_activates_once(self):
        self.assertIsNone(self.update(40, True))
        self.assertIsNone(self.update(41, True))
        self.assertEqual(self.update(41, False), ('nav', 'home'))
        self.assertIsNone(self.update(41, False))

    def test_movement_first_observed_on_release_cancels_click(self):
        self.update(20, True)
        self.assertIsNone(self.update(70, False))
        self.update(20, True)
        self.assertEqual(self.update(20, False), ('nav', 'home'))

    def test_release_on_different_target_does_not_activate(self):
        self.update(95, True)
        self.assertIsNone(self.update(105, False))

    def test_drag_remains_cancelled_after_return_to_origin(self):
        self.update(30, True)
        self.update(60, True)
        self.update(30, True)
        self.assertIsNone(self.update(30, False))
        # A cancelled gesture must not poison the following tap.
        self.update(30, True)
        self.assertEqual(self.update(30, False), ('nav', 'home'))

    def test_crossing_another_target_cancels_even_short_excursion(self):
        self.update(95, True)
        self.update(105, True)
        self.update(95, True)
        self.assertIsNone(self.update(95, False))

    def test_disabled_button_never_activates(self):
        buttons = [((0, 0, 100, 80), 'match-next', None, True)]
        self.update(20, True, buttons=buttons)
        self.assertIsNone(self.update(20, False, buttons=buttons))

    def test_target_removed_or_disabled_before_release_does_not_activate(self):
        self.update(20, True)
        self.assertIsNone(self.update(20, False, buttons=[]))
        self.update(20, True)
        disabled = [((0, 0, 100, 80), 'nav', 'home', True)]
        self.assertIsNone(self.update(20, False, buttons=disabled))

    def test_tap_must_start_inside_a_target(self):
        self.update(-2, True)
        self.assertIsNone(self.update(3, False))
        self.assertIsNone(self.update(100, True, y=80))
        self.assertIsNone(self.update(100, False, y=80))

    def test_touch_on_topmost_control_does_not_activate_underlying_control(self):
        buttons = self.buttons + [((20, 0, 50, 80), 'choose', 'selection', False)]
        self.update(30, True, buttons=buttons)
        self.assertEqual(self.update(30, False, buttons=buttons), ('choose', 'selection'))


class TextTests(unittest.TestCase):
    def test_button_title_does_not_overlap_subtitle(self):
        painter = FakePainter()
        Painter.button(painter, (0, 0, 200, 80), 'Titre long\nDeuxième ligne',
                       'choose', sub='Sous-titre')
        title, subtitle = painter.text_calls
        self.assertLessEqual(title[1][1] + title[1][2], subtitle[1][1])
        self.assertTrue(title[0].endswith('…'))

    def test_heading_title_does_not_overlap_date(self):
        painter = FakePainter()
        viewer = Viewer(painter, demo=True)
        viewer.heading('Mathématiques\nApprofondissement', '22 novembre')
        title, subtitle = painter.text_calls
        self.assertLessEqual(title[1][1] + title[1][2], subtitle[1][1])
        self.assertTrue(title[0].endswith('…'))

    def test_full_homework_text_preserved_when_words_wrap(self):
        text = 'Lire le chapitre 3 puis préparer une réponse complète et détaillée.'
        lines = wrap_pixels(text, 19, len)
        self.assertGreater(len(lines), 1)
        self.assertEqual(' '.join(lines), text)
        self.assertTrue(all(len(line) <= 19 for line in lines))

    def test_unbroken_token_preserved_in_full(self):
        text = 'Début anticonstitutionnellementsupercalifragilisticexpialidocious fin.'
        lines = wrap_pixels(text, 12, len)
        self.assertTrue(all(len(line) <= 12 for line in lines))
        self.assertEqual(''.join(lines).replace(' ', ''), text.replace(' ', ''))
        self.assertTrue(lines[-1].endswith('fin.'))

    def test_wrap_respects_paragraph_breaks_and_empty_lines(self):
        self.assertEqual(wrap_pixels('Chapitre 1\r\n\r\nChapitre 2\n', 40, len),
                         ['Chapitre 1', '', 'Chapitre 2', ''])
        self.assertEqual(wrap_pixels('', 40, len), [''])

    def test_wrap_uses_measured_width_instead_of_character_count(self):
        def measured(text):
            return sum(4 if char == 'W' else 1 for char in text)
        lines = wrap_pixels('iiii WWWW iiii', 8, measured)
        self.assertTrue(all(measured(line) <= 8 for line in lines))
        self.assertEqual(''.join(lines).replace(' ', ''), 'iiiiWWWWiiii')

    def test_html_homework_becomes_readable_paragraphs_and_entities(self):
        result = plain_text('<p>Lire <strong>la leçon</strong> &amp; réviser.</p>'
                            '<div>Faire :<br>exercice&nbsp;4</div>'
                            '<ul><li>un</li><li>deux</li></ul>')
        self.assertEqual(re.sub(r'\s+', ' ', result),
                         'Lire la leçon & réviser. Faire : exercice 4 un deux')
        self.assertIn('\n', result)
        self.assertNotIn('<strong>', result)
        self.assertEqual(plain_text(None), '')
        self.assertEqual(plain_text('Texte sans HTML, éèàù.'), 'Texte sans HTML, éèàù.')


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.painter = FakePainter()
        self.viewer = Viewer(self.painter, demo=True)

    def draw(self):
        self.painter.texts.clear()
        self.viewer.draw()
        return '\n'.join(self.painter.texts)

    def test_initial_selection_prefers_nonempty_competition(self):
        viewer = self.viewer
        viewer.data['football']['competitions'] = {
            'Empty': {}, 'Loaded': {'Jour #1': [{'date': '20261101'}]}}
        viewer.state.competition = None
        viewer.state.round = None
        viewer.reconcile()
        self.assertEqual(viewer.state.competition, 'Loaded')
        self.assertEqual(viewer.state.round, 'Jour #1')
        # An explicit choice of an empty competition must remain respected.
        viewer.state.competition = 'Empty'
        viewer.reconcile()
        self.assertEqual(viewer.state.competition, 'Empty')
        self.assertIsNone(viewer.state.round)

    def test_initial_round_uses_latest_match_date_not_label(self):
        viewer = self.viewer
        viewer.data['football']['competitions'] = {'Cup': {
            'Finale': [{'date': '20261120'}],
            'Quarts de finale': [{'date': '20261101'}],
            'Demi-finales': [{'date': '20261110'}]}}
        viewer.state.competition = None
        viewer.state.round = None
        viewer.reconcile()
        self.assertEqual(viewer.state.round, 'Finale')
        viewer.state.round = 'Quarts de finale'
        viewer.reconcile()
        self.assertEqual(viewer.state.round, 'Quarts de finale')

    def test_undated_cup_rounds_keep_cache_chronology(self):
        viewer = self.viewer
        viewer.data['football']['competitions'] = {'Cup': {
            'Quarts de finale': [{}], 'Demi-finales': [{}], 'Finale': [{}]}}
        viewer.state.competition = None
        viewer.state.round = None
        viewer.reconcile()
        self.assertEqual(viewer.state.round, 'Finale')

    def test_demo_all_scenarios_all_sections_and_sources_draw_without_network(self):
        with patch('ippon.view.configparser.ConfigParser.read',
                   side_effect=AssertionError('demo read config')):
            for scenario in SCENARIOS:
                with self.subTest(scenario=scenario):
                    viewer = Viewer(FakePainter(), demo=True, demo_scenario=scenario)
                    self.assertEqual(viewer.services, {})
                    for page in ('home', 'football', 'school', 'options'):
                        viewer.dispatch('nav', page)
                        viewer.draw()
                    viewer.dispatch('sources')
                    viewer.draw()
                    self.assertEqual(viewer.source_state('football'),
                                     'cached' if scenario == 'offline' else
                                     scenario if scenario in {'loading', 'empty', 'error'} else 'ready')

    def test_header_keeps_seconds_and_right_aligns_clock_inside_canvas(self):
        with patch('ippon.view.datetime', wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 11, 22, 3, 4, 5)
            self.viewer.draw()
        clocks = [(args, kwargs) for text, args, kwargs in self.painter.text_calls
                  if text == '03:04:05']
        self.assertEqual(len(clocks), 1)
        args, kwargs = clocks[0]
        x, y, size = args[:3]
        self.assertEqual(size, 26)
        self.assertTrue(kwargs.get('bold', False))
        self.assertLessEqual(x + self.painter.measure('03:04:05', size, bold=True), 780)
        self.assertGreaterEqual(x, 0)

    def test_courses_and_homework_pagination_are_independent(self):
        viewer = self.viewer
        viewer.dispatch('nav', 'school')
        viewer.dispatch('school-next')
        viewer.dispatch('school-next')
        self.assertEqual(viewer.state.school_pages['courses'], 2)
        self.assertIn('Sciences de la vie', self.draw())
        viewer.dispatch('section', 'homework')
        self.assertEqual(viewer.state.school_pages['homework'], 0)
        viewer.dispatch('school-next')
        self.assertEqual(viewer.state.school_pages['homework'], 1)
        viewer.dispatch('section', 'courses')
        self.assertEqual(viewer.state.school_pages['courses'], 2)

    def test_homework_detail_returns_to_same_list_position(self):
        viewer = self.viewer
        viewer.dispatch('nav', 'school')
        viewer.dispatch('section', 'homework')
        viewer.dispatch('school-next')
        self.draw()
        row = next(button for button in self.painter.buttons if button[1] == 'homework')
        viewer.dispatch(*row[1:3])
        self.assertEqual(viewer.state.detail_index, 2)
        self.assertIn('Réviser le vocabulaire', self.draw())
        viewer.dispatch('back')
        self.assertIsNone(viewer.state.detail)
        self.assertEqual(viewer.state.school_pages['homework'], 1)
        self.assertIn('Anglais', self.draw())

    def test_long_homework_reaches_last_instruction_without_losing_content(self):
        viewer = Viewer(self.painter, demo=True, demo_scenario='long')
        viewer.dispatch('nav', 'school')
        viewer.dispatch('section', 'homework')
        viewer.dispatch('homework', 1)
        pages = viewer.homework_pages()
        self.assertGreater(len(pages), 1)
        source = plain_text(viewer.school_items('homework')[1]['description'])
        self.assertEqual(re.sub(r'\s+', '', ''.join(pages)), re.sub(r'\s+', '', source))
        for _ in range(len(pages) - 1):
            viewer.dispatch('detail-next')
            viewer.draw()
        self.assertEqual(viewer.state.detail_page, len(pages) - 1)
        self.assertTrue(any('pagination.' in value for value in self.painter.texts))
        viewer.dispatch('detail-next')
        viewer.draw()
        self.assertEqual(viewer.state.detail_page, len(pages) - 1)

    def test_reconciliation_handles_disappearing_day_and_open_homework(self):
        viewer = self.viewer
        viewer.dispatch('nav', 'school')
        viewer.dispatch('section', 'homework')
        viewer.dispatch('school-next')
        viewer.dispatch('school-next')
        viewer.dispatch('homework', 5)
        selected = viewer.state.selected_day
        viewer.data['school']['days'][selected]['homework'] = []
        viewer.reconcile()
        self.assertEqual(viewer.state.school_pages['homework'], 0)
        self.assertIsNone(viewer.state.detail)
        del viewer.data['school']['days'][selected]
        viewer.reconcile()
        self.assertEqual(viewer.state.selected_day, viewer.today.isoformat())
        viewer.draw()

    def test_reordered_or_removed_homework_closes_detail_even_when_index_remains_valid(self):
        for change in ('reorder', 'remove'):
            with self.subTest(change=change):
                viewer = Viewer(FakePainter(), demo=True)
                viewer.dispatch('nav', 'school')
                viewer.dispatch('section', 'homework')
                viewer.dispatch('school-next')
                viewer.dispatch('homework', 2)
                viewer.state.detail_page = 1
                selected = viewer.state.selected_day
                updated = deepcopy(viewer.data['school'])
                tasks = updated['days'][selected]['homework']
                if change == 'reorder':
                    tasks[1], tasks[2] = tasks[2], tasks[1]
                else:
                    tasks.pop(0)
                self.assertLess(viewer.state.detail_index, len(tasks))
                service = Mock()
                service.get_snapshot.return_value = updated
                service.status.return_value = viewer.statuses['school']
                viewer.services = {'school': service}
                viewer.demo = False
                self.assertTrue(viewer.refresh(force=True))
                self.assertIsNone(viewer.state.detail)
                self.assertEqual(viewer.state.detail_page, 0)
                self.assertEqual(viewer.state.school_pages['homework'], 1)
                self.assertEqual(viewer.state.selected_day, selected)
                self.assertEqual(viewer.state.page, 'school')
                viewer.draw()

    def test_reordered_or_removed_matches_close_scorer_detail_with_surviving_matches(self):
        for change in ('reorder', 'remove'):
            with self.subTest(change=change):
                viewer = Viewer(FakePainter(), demo=True)
                viewer.dispatch('nav', 'football')
                viewer.dispatch('match-next')
                viewer.dispatch('goals')
                viewer.state.detail_page = 1
                updated = deepcopy(viewer.data['football'])
                games = updated['competitions'][viewer.state.competition][viewer.state.round]
                if change == 'reorder':
                    games[0], games[1] = games[1], games[0]
                else:
                    games.pop(0)
                self.assertLess(viewer.state.match_index, len(games))
                service = Mock()
                service.get_snapshot.return_value = updated
                service.status.return_value = viewer.statuses['football']
                viewer.services = {'football': service}
                viewer.demo = False
                self.assertTrue(viewer.refresh(force=True))
                self.assertIsNone(viewer.state.detail)
                self.assertEqual(viewer.state.detail_page, 0)
                self.assertEqual(viewer.state.page, 'football')
                self.assertIsNotNone(viewer.match)
                viewer.draw()

    def test_unrelated_refresh_does_not_interrupt_open_detail(self):
        for kind in ('homework', 'goals'):
            with self.subTest(detail=kind):
                viewer = Viewer(FakePainter(), demo=True)
                if kind == 'homework':
                    viewer.dispatch('nav', 'school')
                    viewer.dispatch('homework', 0)
                    key = 'school'
                    updated = deepcopy(viewer.data[key])
                    other_day = next(day for day in updated['days']
                                     if day != viewer.state.selected_day)
                    updated['days'][other_day]['homework'].reverse()
                else:
                    viewer.dispatch('nav', 'football')
                    viewer.dispatch('goals')
                    key = 'football'
                    updated = deepcopy(viewer.data[key])
                    other_competition = next(name for name in updated['competitions']
                                             if name != viewer.state.competition)
                    next(iter(updated['competitions'][other_competition].values())).reverse()
                viewer.state.detail_page = 1
                service = Mock()
                service.get_snapshot.return_value = updated
                service.status.return_value = viewer.statuses[key]
                viewer.services = {key: service}
                viewer.demo = False
                self.assertTrue(viewer.refresh(force=True))
                self.assertEqual(viewer.state.detail, kind)
                self.assertEqual(viewer.state.detail_page, 1)
                self.assertFalse(viewer.refresh(force=True))
                self.assertEqual(viewer.state.detail, kind)

    @staticmethod
    def school_day(subject='Mathématiques'):
        return {'lessons': [{'start': '08:30', 'end': '09:20', 'subject': subject,
                             'classroom': '204', 'canceled': False}],
                'homework': [{'subject': subject, 'description': 'Exercice 4.', 'done': False}]}

    def test_old_pronote_cache_never_substitutes_a_past_day_for_today(self):
        viewer = self.viewer
        viewer.today = date(2026, 11, 22)
        viewer.data['school'] = {'days': {
            '2026-10-27': self.school_day('ANCIEN COURS OCTOBRE'),
            '2026-11-10': self.school_day('ANCIEN COURS NOVEMBRE')},
            'updated_at': 1793091600}
        viewer.statuses['school']['state'] = 'cached'
        viewer.state.selected_day = '2026-10-27'
        original = deepcopy(viewer.data['school'])
        viewer.reconcile()
        self.assertEqual(viewer.state.selected_day, '2026-11-22')
        viewer.state.navigate('school')
        self.assertEqual(viewer.school_items(), [])
        text = self.draw()
        self.assertIn('Journée non chargée', text)
        self.assertNotIn('Journée reçue', text)
        self.assertNotIn('Aucun cours pour ce jour', text)
        self.assertNotIn('ANCIEN COURS', text)
        self.assertEqual(viewer.data['school'], original)
        viewer.dispatch('select-day')
        self.assertEqual([value for value, label in viewer.selector_values()], ['2026-11-22'])

    def test_home_with_only_old_school_cache_requests_update_and_opens_today(self):
        viewer = self.viewer
        viewer.today = date(2026, 11, 22)
        viewer.data['school'] = {'days': {
            '2026-10-27': self.school_day('COURS PÉRIMÉ OCTOBRE'),
            '2026-11-10': self.school_day('COURS PÉRIMÉ NOVEMBRE')},
            'updated_at': 1793091600}
        viewer.statuses['school']['state'] = 'cached'
        viewer.reconcile()
        text = self.draw()
        self.assertIn('À actualiser', text)
        self.assertIn('Aucune donnée pour aujourd’hui.', text)
        self.assertIn('DIMANCHE 22 NOVEMBRE', text)
        self.assertNotIn('COURS PÉRIMÉ', text)
        self.assertNotIn('Début à', text)
        self.assertNotIn('Prochain à', text)
        hero_content = '\n'.join(value for value, args, kwargs in self.painter.text_calls
                                 if len(args) >= 2 and args[0] == 36
                                 and 140 <= args[1] <= 290)
        self.assertNotIn('08:30', hero_content)
        # Activate the drawn hero through the same release tracker as the UI.
        hero = next(button for button in self.painter.buttons if button[1] == 'home-school')
        x, y, width, height = hero[0]
        point = (x + width / 2, y + height / 2)
        pointer = PointerTracker()
        self.assertIsNone(pointer.update(point, True, self.painter.buttons))
        action = pointer.update(point, False, self.painter.buttons)
        self.assertEqual(action, ('home-school', None))
        with patch('ippon.view.date', wraps=date) as calendar:
            calendar.today.return_value = date(2026, 11, 22)
            viewer.dispatch(*action)
        self.assertEqual(viewer.state.page, 'school')
        self.assertEqual(viewer.state.selected_day, '2026-11-22')
        self.assertIn('Journée non chargée', self.draw())

    def test_school_day_selector_starts_today_hides_past_and_keeps_sorted_future(self):
        viewer = self.viewer
        viewer.today = date(2026, 11, 22)
        viewer.data['school']['days'] = {
            '2026-11-24': self.school_day(),
            '2026-10-27': self.school_day(),
            '2026-11-23': self.school_day()}
        viewer.state.selected_day = None
        viewer.reconcile()
        viewer.dispatch('select-day')
        self.assertEqual([value for value, label in viewer.selector_values()],
                         ['2026-11-22', '2026-11-23', '2026-11-24'])
        self.draw()
        choices = [button[2] for button in self.painter.buttons if button[1] == 'choose']
        self.assertEqual(choices, ['2026-11-22', '2026-11-23'])
        viewer.dispatch('choose', '2026-11-24')
        self.assertEqual(viewer.state.selected_day, '2026-11-24')
        viewer.data['school']['days']['2026-11-22'] = self.school_day()
        viewer.dispatch('select-day')
        self.assertEqual(sum(value == '2026-11-22' for value, label in viewer.selector_values()), 1)

    def test_missing_today_differs_from_received_day_with_no_lessons_or_homework(self):
        viewer = self.viewer
        viewer.today = date(2026, 11, 22)
        viewer.data['school']['days'] = {'2026-11-23': self.school_day()}
        viewer.statuses['school']['state'] = 'ready'
        viewer.state.selected_day = None
        viewer.reconcile()
        viewer.state.navigate('school')
        self.assertIn('Journée non chargée', self.draw())
        viewer.data['school']['days']['2026-11-22'] = {'lessons': [], 'homework': []}
        viewer.reconcile()
        text = self.draw()
        self.assertIn('Aucun cours pour ce jour', text)
        self.assertIn('Journée reçue', text)
        self.assertNotIn('Journée non chargée', text)
        viewer.dispatch('section', 'homework')
        self.assertIn('Aucun devoir pour ce jour', self.draw())
        del viewer.data['school']['days']['2026-11-22']
        viewer.reconcile()
        text = self.draw()
        self.assertIn('Journée non chargée', text)
        self.assertNotIn('Aucun devoir pour ce jour', text)

    def test_initial_school_navigation_defaults_to_today_while_next_day_card_opens_its_day(self):
        viewer = self.viewer
        viewer.today = date(2026, 11, 22)
        viewer.data['school']['days'] = {'2026-11-24': self.school_day()}
        viewer.state.selected_day = None
        viewer.state.school_pages = {'courses': 2, 'homework': 2}
        with patch('ippon.view.date', wraps=date) as calendar:
            calendar.today.return_value = date(2026, 11, 22)
            viewer.dispatch('nav', 'school')
            self.assertEqual(viewer.state.selected_day, '2026-11-22')
            self.assertEqual(viewer.state.school_pages, {'courses': 0, 'homework': 0})
            viewer.dispatch('home-school')
        self.assertEqual(viewer.state.selected_day, '2026-11-24')

    def test_midnight_resets_day_pagination_and_detail_even_in_demo(self):
        for demo in (True, False):
            for overlay in ('homework', 'day'):
                with self.subTest(demo=demo, overlay=overlay):
                    viewer = Viewer(FakePainter(), demo=True)
                    viewer.demo = demo
                    viewer.today = date(2026, 11, 22)
                    viewer.data['school']['days'] = {
                        '2026-11-23': self.school_day(),
                        '2026-11-24': self.school_day()}
                    viewer.state.selected_day = '2026-11-24'
                    viewer.state.school_pages = {'courses': 2, 'homework': 2}
                    if overlay == 'homework':
                        viewer.state.detail = 'homework'
                        viewer.state.detail_page = 2
                    else:
                        viewer.state.panel = 'day'
                        viewer.state.panel_page = 2
                    with patch('ippon.view.date', wraps=date) as calendar:
                        calendar.today.return_value = date(2026, 11, 23)
                        self.assertTrue(viewer.refresh(force=True))
                    self.assertEqual(viewer.today, date(2026, 11, 23))
                    self.assertEqual(viewer.state.selected_day, '2026-11-23')
                    self.assertEqual(viewer.state.school_pages, {'courses': 0, 'homework': 0})
                    self.assertIsNone(viewer.state.detail)
                    self.assertEqual(viewer.state.detail_page, 0)
                    if overlay == 'day':
                        self.assertEqual(viewer.state.panel_page, 0)
                    viewer.draw()

    def test_changing_day_resets_both_school_paginators(self):
        viewer = self.viewer
        viewer.state.school_pages = {'courses': 2, 'homework': 2}
        other_day = next(day for day in viewer.data['school']['days']
                         if day != viewer.state.selected_day)
        viewer.dispatch('select-day')
        viewer.dispatch('choose', other_day)
        self.assertEqual(viewer.state.selected_day, other_day)
        self.assertEqual(viewer.state.school_pages, {'courses': 0, 'homework': 0})
        self.assertIsNone(viewer.state.panel)

    def test_removing_current_competition_does_not_leave_stale_match_index(self):
        viewer = self.viewer
        viewer.dispatch('nav', 'football')
        viewer.dispatch('match-next')
        viewer.dispatch('match-next')
        old = viewer.state.competition
        del viewer.data['football']['competitions'][old]
        viewer.reconcile()
        self.assertNotEqual(viewer.state.competition, old)
        self.assertLess(viewer.state.match_index, len(viewer.games))
        viewer.data['football']['competitions'] = {}
        viewer.reconcile()
        self.assertEqual(viewer.state.match_index, 0)
        self.assertIsNone(viewer.match)
        self.assertIn('Aucun résultat', self.draw())

    def test_scores_unavailable_does_not_block_school_or_weather(self):
        viewer = self.viewer
        viewer.data['football'] = {'competitions': {}}
        viewer.statuses['football'] = {'state': 'error'}
        viewer.reconcile()
        self.assertIn('12°', self.draw())
        viewer.dispatch('nav', 'school')
        self.assertTrue(viewer.school_items())
        self.assertIn('Cours', self.draw())
        viewer.dispatch('section', 'homework')
        self.assertIn('Mathématiques', self.draw())

    def test_selectors_are_dismissible_and_competition_change_chooses_available_round(self):
        viewer = self.viewer
        viewer.dispatch('nav', 'football')
        viewer.dispatch('select-competition')
        self.draw()
        options = viewer.selector_values()
        self.assertEqual(len(options), len(viewer.competitions))
        viewer.dispatch('choose', options[-1][0])
        self.assertIsNone(viewer.state.panel)
        self.assertIn(viewer.state.round, viewer.competitions[viewer.state.competition])
        viewer.dispatch('select-round')
        viewer.dispatch('back')
        self.assertIsNone(viewer.state.panel)
        self.assertEqual(viewer.state.page, 'football')

    def test_source_states_are_not_confused_with_legitimate_empty_day(self):
        viewer = self.viewer
        viewer.dispatch('nav', 'school')
        viewer.data['school']['days'][viewer.state.selected_day] = {'lessons': [], 'homework': []}
        for state, expected in [('ready', 'Aucun cours pour ce jour'),
                                ('loading', 'Chargement en cours'),
                                ('unconfigured', 'Source non configurée'),
                                ('error', 'Données indisponibles')]:
            with self.subTest(state=state):
                viewer.statuses['school']['state'] = state
                self.assertIn(expected, self.draw())

    def test_privacy_hides_school_summary_and_auto_requires_explicit_resume(self):
        viewer = self.viewer
        viewer.dispatch('privacy')
        text = self.draw()
        self.assertIn('Côté terrain.', text)
        self.assertNotIn('Mathématiques', text)
        viewer.dispatch('auto')
        self.assertEqual(viewer.state.auto, 'running')
        viewer.dispatch('nav', 'school')
        self.assertEqual(viewer.state.auto, 'paused')
        self.assertFalse(viewer.state.tick(10**12))
        viewer.dispatch('auto-off')
        self.assertEqual(viewer.state.auto, 'off')

    def test_disappearing_match_closes_goal_detail_instead_of_claiming_zero_goals(self):
        viewer = self.viewer
        viewer.dispatch('nav', 'football')
        viewer.dispatch('goals')
        viewer.dispatch('detail-next')
        self.assertEqual(viewer.state.detail, 'goals')
        viewer.data['football']['competitions'] = {}
        viewer.statuses['football']['state'] = 'error'
        viewer.reconcile()
        self.assertIsNone(viewer.state.detail)
        self.assertEqual(viewer.state.detail_page, 0)
        text = self.draw()
        self.assertIn('Données indisponibles', text)
        self.assertNotIn('Ce match s’est terminé sans but.', text)
        self.assertNotIn('Aucun but', text)

    def test_offline_weather_card_displays_cache_timestamp_without_opening_sources(self):
        viewer = Viewer(self.painter, demo=True, demo_scenario='offline')
        self.painter.text_calls.clear()
        viewer.draw()
        # There are several cache stamps on home. Require the weather card's
        # own bottom line, so an unrelated football/school stamp cannot pass.
        weather_bottom = [text for text, args, kwargs in self.painter.text_calls
                          if len(args) >= 2 and args[0] == 492 and args[1] == 176]
        self.assertEqual(weather_bottom, [viewer.stamp('weather')])
        self.assertTrue(weather_bottom[0].startswith('Cache · '))
        self.assertNotIn('pluie', weather_bottom[0])
        self.assertEqual(viewer.state.page, 'home')
        self.assertFalse(viewer.state.sources)

    def test_incomplete_pronote_configuration_keeps_valid_football_cache_available(self):
        from ippon.config import StaticConfiguration
        from ippon.ui_model import ScoresService

        weather = Mock()
        weather.get_snapshot.return_value = None
        weather.status.return_value = {'state': 'loading', 'last_success': None}
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / 'config.ini'
            config_path.write_text(
                '[competition.ligue1]\nname = Ligue 1\nyear = 2026\n'
                'source = livescore\nsource_id = 68\n'
                '[pronote]\npronote_url = https://example.test/pronote/\n',
                encoding='utf-8')
            with gzip.open(Path(directory) / 'Ligue 1.json.gz', 'wt', encoding='utf-8') as stream:
                json.dump([[self.viewer.match]], stream)
            # Use the real configuration reader and score cache loader. Only
            # scheduling and the unrelated weather source are substituted.
            with patch.object(StaticConfiguration, 'config_file_path', str(config_path)), \
                    patch.object(StaticConfiguration, 'config_competitions_directory_path', directory), \
                    patch.object(ScoresService, 'refresh', lambda service: service._refresh()), \
                    patch('ippon.pronote.load_snapshot', return_value={'days': {}, 'updated_at': None}), \
                    patch('ippon.weather.WeatherService', return_value=weather), \
                    self.assertLogs('ippon.pronote', level='WARNING'):
                viewer = Viewer(self.painter)
            self.assertIsNone(viewer.config_error)
            self.assertEqual(viewer.source_state('school'), 'error')
            self.assertIsNone(viewer.services['school'].thread)
            self.assertIn('Ligue 1', viewer.competitions)
            self.assertIsNotNone(viewer.match)
            viewer.dispatch('nav', 'football')
            self.painter.texts.clear()
            viewer.draw()
            self.assertIn('Buteurs →', self.painter.texts)
            self.assertNotIn('Données indisponibles', self.painter.texts)
            weather.refresh.assert_called_once()

    def test_football_detail_reaches_all_goals_and_back_preserves_match(self):
        viewer = Viewer(self.painter, demo=True, demo_scenario='long')
        viewer.dispatch('nav', 'football')
        viewer.dispatch('goals')
        for _ in range(3):
            viewer.draw()
            viewer.dispatch('detail-next')
        viewer.draw()
        self.assertEqual(viewer.state.detail_page, 3)
        self.assertTrue(any('Joueur Démo G' in text for text in self.painter.texts))
        viewer.dispatch('back')
        self.assertIsNone(viewer.state.detail)
        self.assertEqual(viewer.state.match_index, 0)


class LogoTests(unittest.TestCase):
    def painter(self):
        painter = Painter.__new__(Painter)
        painter.textures = OrderedDict()
        painter.r = SimpleNamespace(load_texture=Mock(side_effect=RuntimeError('invalid PNG')))
        painter.card = Mock()
        painter.lines = Mock()
        return painter

    def test_missing_logo_renders_initials_without_loading_texture(self):
        painter = self.painter()
        painter.logo({'name': 'Paris Saint Germain', 'logo': ''}, (0, 0, 56, 56))
        painter.r.load_texture.assert_not_called()
        self.assertEqual(painter.lines.call_args.args[0], 'PSG')

    def test_invalid_cached_png_falls_back_and_does_not_retry_every_frame(self):
        painter = self.painter()
        with patch('ippon.view.Path.is_file', return_value=True):
            painter.logo({'name': 'Lyon', 'logo': 'https://example.test/logo.png'}, (0, 0, 56, 56))
            painter.logo({'name': 'Lyon', 'logo': 'https://example.test/logo.png'}, (0, 0, 56, 56))
        self.assertEqual(painter.r.load_texture.call_count, 1)
        self.assertEqual(painter.lines.call_args.args[0], 'L')


class WindowCoordinateTests(unittest.TestCase):
    def fake_raylib(self, frame, press_frame=None):
        rl = ModuleType('pyray')
        for constant in ('LOG_WARNING', 'FLAG_WINDOW_RESIZABLE', 'FLAG_WINDOW_HIGHDPI',
                         'KEY_NULL', 'KEY_Q', 'KEY_F', 'KEY_ESCAPE',
                         'TEXTURE_FILTER_BILINEAR', 'MOUSE_BUTTON_LEFT', 'WHITE'):
            setattr(rl, constant, 0)
        for method in ('set_trace_log_level', 'set_config_flags', 'init_window',
                       'set_window_min_size', 'set_target_fps', 'set_exit_key',
                       'set_texture_filter', 'begin_texture_mode', 'end_texture_mode',
                       'begin_drawing', 'clear_background', 'unload_render_texture',
                       'close_window'):
            setattr(rl, method, Mock())
        rl.load_render_texture = Mock(return_value=SimpleNamespace(id=1, texture=object()))
        rl.get_screen_width = lambda: 1600
        rl.get_screen_height = lambda: 1000
        rl.get_touch_point_count = lambda: 0
        rl.is_key_pressed = lambda key: False
        rl.window_should_close = lambda: False
        rl.is_mouse_button_down = lambda button: frame[0] == press_frame
        # 1600×1000 letterboxes the logical canvas by 20 px vertically.
        rl.get_mouse_position = lambda: SimpleNamespace(x=1100, y=880)
        rl.Vector2 = lambda x, y: SimpleNamespace(x=x, y=y)
        rl.Rectangle = lambda *args: args
        rl.draw_texture_pro = Mock()
        rl.end_drawing = lambda: frame.__setitem__(0, frame[0] + 1)
        return rl

    def test_letterboxed_window_maps_release_to_logical_touch_target(self):
        """Exercise production transform through its event loop, not a copy of it."""
        painter = FakePainter()
        viewer = Viewer(painter, demo=True)
        frame = [0]
        rl = self.fake_raylib(frame, press_frame=1)
        with patch.dict(sys.modules, {'pyray': rl}), \
                patch('ippon.view.Painter', return_value=painter), \
                patch('ippon.view.Viewer', return_value=viewer):
            window_logic(demo=True, frames=3)
        self.assertEqual(viewer.state.page, 'school')
        destination = rl.draw_texture_pro.call_args.args[2]
        self.assertEqual(destination, (0, 20, 1600, 960))
        rl.close_window.assert_called_once()

    def test_second_boundary_redraws_without_input_or_source_updates(self):
        painter = FakePainter()
        viewer = Viewer(painter, demo=True)
        viewer.refresh = Mock(return_value=False)
        viewer.draw = Mock(wraps=viewer.draw)
        frame = [0]
        rl = self.fake_raylib(frame)
        with patch.dict(sys.modules, {'pyray': rl}), \
                patch('ippon.view.Painter', return_value=painter), \
                patch('ippon.view.Viewer', return_value=viewer), \
                patch('ippon.view.datetime', wraps=datetime) as clock:
            # Four frames, no interactions; only the third crosses a second.
            clock.now.side_effect = lambda: datetime(2026, 11, 22, 3, 4, 5 + frame[0] // 2)
            window_logic(demo=True, frames=4)
        self.assertEqual(viewer.draw.call_count, 2)
        self.assertEqual(rl.begin_texture_mode.call_count, 2)
        drawn_clocks = [text for text in painter.texts
                        if re.fullmatch(r'03:04:\d{2}', text)]
        self.assertEqual(drawn_clocks, ['03:04:05', '03:04:06'])
        self.assertEqual(viewer.refresh.call_count, 4)
        self.assertEqual(viewer.state.auto, 'off')


if __name__ == '__main__':
    unittest.main()
