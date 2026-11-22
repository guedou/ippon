# SPDX-License-Identifier: GPL-2.0+
"""Select an appliance display mode and verify the state raylib reports.

Prefer borderless mode; fall back to the classic fullscreen toggle if the
backend does not activate it. The dashboard stays on its logical 800x480 canvas.
Native displays already fullscreen before this controller starts are preserved.
"""

import logging
from pathlib import Path
import sys

LOG = logging.getLogger(__name__)
_MODEL_PATHS = ('/proc/device-tree/model',
                '/sys/firmware/devicetree/base/model')


def is_raspberry_pi():
    """Recognize the hardware model, rather than treating every ARM/Linux as Pi."""
    if sys.platform != 'linux':
        return False
    for filename in _MODEL_PATHS:
        try:
            model = Path(filename).read_bytes().rstrip(b'\x00').decode('ascii', errors='ignore')
        except OSError:
            continue
        return model.startswith('Raspberry Pi')
    return False


class DisplayMode:
    """Manage explicit or Pi-default fullscreen mode after window creation."""

    def __init__(self, rl, fullscreen=None):
        self.r = rl
        self.requested = is_raspberry_pi() if fullscreen is None else bool(fullscreen)
        self._mode = 'windowed'
        self._started = False

    @property
    def enabled(self):
        # A void toggle call can exist but be unsupported on a backend.
        return self._observed_mode() != 'windowed'

    @property
    def can_toggle(self):
        return self._mode != 'native'

    def _borderless(self):
        flag = getattr(self.r, 'FLAG_BORDERLESS_WINDOWED_MODE', None)
        query = getattr(self.r, 'is_window_state', None)
        return bool(query(flag)) if flag is not None and callable(query) else False

    def _native_fullscreen(self):
        query = getattr(self.r, 'is_window_fullscreen', None)
        return bool(query()) if callable(query) else False

    def _observed_mode(self):
        if self._borderless():
            return 'borderless'
        return 'exclusive' if self._native_fullscreen() else 'windowed'

    def _focus(self):
        focus = getattr(self.r, 'set_window_focused', None)
        if callable(focus):
            focus()

    def start(self):
        """Apply the initial preference once; call only after init_window()."""
        if self._started:
            return self.enabled
        self._started = True
        observed = self._observed_mode()
        # Ownership is separate from the actual flags: preexisting native
        # fullscreen must not be mistaken for a mode entered by this helper.
        self._mode = 'native' if observed == 'exclusive' else observed
        if self.requested and observed == 'windowed':
            self.toggle()
        return self.enabled

    def toggle(self):
        """Change modes only when raylib confirms the requested result."""
        if not self.can_toggle:
            return False
        before = self._observed_mode()
        if before == 'exclusive' and self._mode not in ('exclusive', 'borderless'):
            self._mode = 'native'
            return False
        if before != 'windowed':
            name = ('toggle_borderless_windowed' if before == 'borderless'
                    else 'toggle_fullscreen')
            toggle = getattr(self.r, name, None)
            if callable(toggle):
                toggle()
            after = self._observed_mode()
            self._mode = after
            if after == 'windowed':
                self._focus()
                return True
            LOG.warning('The raylib backend did not leave fullscreen mode.')
            return False

        borderless = getattr(self.r, 'toggle_borderless_windowed', None)
        if callable(borderless):
            borderless()
            after = self._observed_mode()
            if after != 'windowed':
                self._mode = after
                self._focus()
                return True

        # This is deliberately the same call used by the original viewer.
        # Do not infer success from the symbol existing or from a void return.
        classic = getattr(self.r, 'toggle_fullscreen', None)
        if callable(classic):
            classic()
        after = self._observed_mode()
        self._mode = after
        if after != 'windowed':
            self._focus()
            return True
        LOG.warning('The raylib backend did not activate fullscreen mode.')
        return False
