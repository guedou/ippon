# SPDX-License-Identifier: GPL-2.0+
"""Display-mode policy without importing raylib or opening a native window."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from click.testing import CliRunner

from ippon import main
from ippon.display import DisplayMode, is_raspberry_pi


def fake_raylib(native=False, borderless=False, borderless_works=True,
                fullscreen_works=True):
    state = {'native': native, 'borderless': borderless}
    def toggle_borderless():
        if borderless_works:
            state['borderless'] = not state['borderless']
            if not state['borderless']:
                state['native'] = False
    def toggle_fullscreen():
        if fullscreen_works:
            state['native'] = not state['native']
    return SimpleNamespace(
        FLAG_BORDERLESS_WINDOWED_MODE=32768,
        is_window_state=lambda flag: state['borderless'],
        is_window_fullscreen=lambda: state['native'],
        toggle_borderless_windowed=Mock(side_effect=toggle_borderless),
        toggle_fullscreen=Mock(side_effect=toggle_fullscreen),
        set_window_size=Mock(), set_window_position=Mock(),
        set_window_focused=Mock(), state=state)


class PiDetectionTests(unittest.TestCase):
    def test_only_linux_checks_device_tree(self):
        for platform in ('darwin', 'win32'):
            with self.subTest(platform=platform), patch('ippon.display.sys.platform', platform), \
                    patch('ippon.display.Path.read_bytes') as read:
                self.assertFalse(is_raspberry_pi())
                read.assert_not_called()

    def test_model_identifies_pi_with_kernel_null_terminator(self):
        with patch('ippon.display.sys.platform', 'linux'), \
                patch('ippon.display.Path.read_bytes', return_value=b'Raspberry Pi Zero W Rev 1.1\x00'):
            self.assertTrue(is_raspberry_pi())

    def test_sysfs_fallback_and_non_pi_arm_board(self):
        with patch('ippon.display.sys.platform', 'linux'), \
                patch('ippon.display.Path.read_bytes', side_effect=[FileNotFoundError(), b'Raspberry Pi Zero 2 W\x00']):
            self.assertTrue(is_raspberry_pi())
        with patch('ippon.display.sys.platform', 'linux'), \
                patch('ippon.display.Path.read_bytes', return_value=b'Another ARM Board\x00'):
            self.assertFalse(is_raspberry_pi())

    def test_unreadable_device_tree_keeps_window_default(self):
        with patch('ippon.display.sys.platform', 'linux'), \
                patch('ippon.display.Path.read_bytes', side_effect=PermissionError()):
            self.assertFalse(is_raspberry_pi())


class DisplayModeTests(unittest.TestCase):
    def test_auto_pi_starts_borderless_without_requesting_resolution_or_rotation(self):
        rl = fake_raylib()
        with patch('ippon.display.is_raspberry_pi', return_value=True):
            display = DisplayMode(rl)
        self.assertTrue(display.start())
        self.assertTrue(display.enabled)
        rl.toggle_borderless_windowed.assert_called_once_with()
        rl.toggle_fullscreen.assert_not_called()
        rl.set_window_size.assert_not_called()
        rl.set_window_position.assert_not_called()
        self.assertTrue(display.start())
        self.assertEqual(rl.toggle_borderless_windowed.call_count, 1)

    def test_auto_non_pi_is_windowed(self):
        rl = fake_raylib()
        with patch('ippon.display.is_raspberry_pi', return_value=False):
            display = DisplayMode(rl)
        self.assertFalse(display.start())
        self.assertFalse(display.enabled)
        rl.toggle_borderless_windowed.assert_not_called()

    def test_explicit_windowed_overrides_pi_and_fullscreen_overrides_desktop(self):
        for requested, expected in ((False, False), (True, True)):
            with self.subTest(requested=requested), \
                    patch('ippon.display.is_raspberry_pi') as detect:
                rl = fake_raylib()
                display = DisplayMode(rl, fullscreen=requested)
                self.assertEqual(display.start(), expected)
                detect.assert_not_called()
                self.assertEqual(rl.toggle_borderless_windowed.call_count, int(expected))

    def test_toggle_returns_to_windowed_mode_and_can_reenter(self):
        rl = fake_raylib()
        display = DisplayMode(rl, fullscreen=True)
        display.start()
        self.assertTrue(display.toggle())
        self.assertFalse(display.enabled)
        self.assertTrue(display.toggle())
        self.assertTrue(display.enabled)
        self.assertEqual(rl.toggle_borderless_windowed.call_count, 3)
        rl.toggle_fullscreen.assert_not_called()

    def test_native_fullscreen_backend_is_left_unchanged(self):
        for requested in (False, True):
            with self.subTest(requested=requested):
                rl = fake_raylib(native=True)
                display = DisplayMode(rl, fullscreen=requested)
                self.assertTrue(display.start())
                self.assertFalse(display.can_toggle)
                self.assertFalse(display.toggle())
                rl.set_window_focused.assert_not_called()
                rl.toggle_borderless_windowed.assert_not_called()
                rl.toggle_fullscreen.assert_not_called()

    def test_already_borderless_is_not_inverted_at_start(self):
        rl = fake_raylib(native=True, borderless=True)
        display = DisplayMode(rl, fullscreen=True)
        self.assertTrue(display.start())
        rl.toggle_borderless_windowed.assert_not_called()
        self.assertTrue(display.toggle())
        self.assertFalse(display.enabled)

    def test_missing_borderless_api_falls_back_to_classic_fullscreen(self):
        rl = fake_raylib()
        del rl.toggle_borderless_windowed
        display = DisplayMode(rl, fullscreen=True)
        self.assertTrue(display.start())
        self.assertTrue(display.enabled)
        self.assertTrue(display.can_toggle)
        rl.toggle_fullscreen.assert_called_once_with()
        self.assertTrue(display.toggle())
        self.assertFalse(display.enabled)
        self.assertEqual(rl.toggle_fullscreen.call_count, 2)

    def test_noop_borderless_falls_back_then_classic_mode_remains_exitable(self):
        rl = fake_raylib(borderless_works=False)
        display = DisplayMode(rl, fullscreen=True)
        self.assertTrue(display.start())
        self.assertFalse(rl.state['borderless'])
        self.assertTrue(rl.state['native'])
        self.assertTrue(display.enabled)
        self.assertTrue(display.can_toggle)
        rl.toggle_borderless_windowed.assert_called_once_with()
        rl.toggle_fullscreen.assert_called_once_with()
        self.assertTrue(display.start())
        self.assertEqual(rl.toggle_fullscreen.call_count, 1)
        self.assertTrue(display.toggle())
        self.assertFalse(display.enabled)
        self.assertEqual(rl.toggle_fullscreen.call_count, 2)
        self.assertEqual(rl.toggle_borderless_windowed.call_count, 1)
        self.assertTrue(display.toggle())
        self.assertTrue(display.enabled)
        self.assertTrue(display.can_toggle)

    def test_both_toggle_apis_noop_never_claims_fullscreen(self):
        rl = fake_raylib(borderless_works=False, fullscreen_works=False)
        display = DisplayMode(rl, fullscreen=True)
        with self.assertLogs('ippon.display', level='WARNING'):
            self.assertFalse(display.start())
        self.assertFalse(display.enabled)
        self.assertTrue(display.can_toggle)
        rl.toggle_borderless_windowed.assert_called_once_with()
        rl.toggle_fullscreen.assert_called_once_with()
        rl.set_window_focused.assert_not_called()
        with self.assertLogs('ippon.display', level='WARNING'):
            self.assertFalse(display.toggle())
        self.assertFalse(display.enabled)
        rl.set_window_focused.assert_not_called()

    def test_failed_exit_keeps_the_reported_fullscreen_state(self):
        rl = fake_raylib(borderless_works=False)
        display = DisplayMode(rl, fullscreen=True)
        display.start()
        rl.set_window_focused.reset_mock()
        rl.toggle_fullscreen.side_effect = lambda: None
        with self.assertLogs('ippon.display', level='WARNING'):
            self.assertFalse(display.toggle())
        self.assertTrue(display.enabled)
        self.assertTrue(display.can_toggle)
        rl.set_window_focused.assert_not_called()

    def test_enabled_reflects_raylib_flags_not_previous_success(self):
        rl = fake_raylib()
        display = DisplayMode(rl, fullscreen=True)
        display.start()
        self.assertTrue(display.enabled)
        rl.state['borderless'] = False
        self.assertFalse(display.enabled)

    def test_borderless_api_that_sets_only_fullscreen_flag_is_owned_and_exitable(self):
        rl = fake_raylib()
        rl.toggle_borderless_windowed.side_effect = lambda: rl.state.update(native=True)
        display = DisplayMode(rl, fullscreen=True)
        self.assertTrue(display.start())
        self.assertTrue(display.can_toggle)
        rl.toggle_fullscreen.assert_not_called()
        self.assertTrue(display.toggle())
        self.assertFalse(display.enabled)
        rl.toggle_fullscreen.assert_called_once_with()

    def test_focus_is_requested_once_per_successful_mode_change(self):
        rl = fake_raylib()
        display = DisplayMode(rl, fullscreen=True)
        display.start()
        rl.set_window_focused.assert_called_once_with()
        display.start()
        self.assertEqual(rl.set_window_focused.call_count, 1)
        display.toggle()
        self.assertEqual(rl.set_window_focused.call_count, 2)
        display.toggle()
        self.assertEqual(rl.set_window_focused.call_count, 3)

    def test_optional_focus_api_is_not_required(self):
        rl = fake_raylib()
        del rl.set_window_focused
        display = DisplayMode(rl, fullscreen=True)
        self.assertTrue(display.start())
        self.assertTrue(display.toggle())


class DisplayCliTests(unittest.TestCase):
    def test_cli_preserves_auto_and_both_explicit_preferences(self):
        for options, expected in (([], None), (['--fullscreen'], True), (['--windowed'], False)):
            with self.subTest(options=options), patch('ippon.view.window_logic') as run:
                result = CliRunner().invoke(main, ['view', '--demo', *options])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertIs(run.call_args.kwargs['fullscreen'], expected)


if __name__ == '__main__':
    unittest.main()
