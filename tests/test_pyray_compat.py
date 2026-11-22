# SPDX-License-Identifier: GPL-2.0+
"""Exercise the installed pyray argument wrapper without a graphics context."""
import importlib
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cffi import FFI

from ippon.view import ASSETS, Painter


class PyrayCompatibilityTests(unittest.TestCase):
    def test_font_codepoints_cross_the_real_wrapper_as_an_int_pointer(self):
        try:
            rl = importlib.import_module('pyray')
        except ImportError:
            self.skipTest('pyray is not installed')
        if not hasattr(rl, '_wrap_function'):
            self.skipTest('this pyray version does not expose its argument wrapper')
        received = []

        # Run the actual pyray wrapper against a CFFI function with LoadFontEx's
        # argument types. No GLFW window, OpenGL texture or display is needed.
        callback_ffi = FFI()

        @callback_ffi.callback('int(const char *, int, int *, int)')
        def accept_font_arguments(filename, size, codepoints, count):
            received.append((rl.ffi.string(filename).decode(), size,
                             list(rl.ffi.unpack(codepoints, count))))
            return 1

        wrapped = rl._wrap_function(accept_font_arguments)

        def load_font(*args):
            self.assertEqual(wrapped(*args), 1)
            return SimpleNamespace(texture=SimpleNamespace(id=1))

        with (patch.object(rl, 'load_font_ex', side_effect=load_font),
              patch.object(rl, 'set_texture_filter'),
              patch.object(rl, 'unload_font') as unload):
            painter = Painter(rl)
            painter.close()
            self.assertEqual(unload.call_count, 2)

        self.assertEqual([Path(item[0]).name for item in received],
                         ['NotoSans-Regular.ttf', 'NotoSans-Bold.ttf'])
        for filename, size, codepoints in received:
            self.assertTrue(Path(filename).is_relative_to(ASSETS))
            self.assertTrue(Path(filename).is_file())
            self.assertEqual(size, 64)
            self.assertEqual(codepoints[:95], list(range(32, 127)))
            self.assertIn(ord('é'), codepoints)
            self.assertIn(ord('œ'), codepoints)


if __name__ == '__main__':
    unittest.main()
