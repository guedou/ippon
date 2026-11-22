# SPDX-License-Identifier: GPL-2.0+
"""Select an appliance display mode without changing the desktop rotation.

The logical dashboard remains 800x480. Desktop fullscreen uses raylib's
borderless API and the current desktop mode; it never requests a larger video
mode. Native DRM/KMS displays that are already fullscreen are left alone.
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
    """Manage explicit or Pi-default borderless mode after window creation."""

    def __init__(self, rl, fullscreen=None):
        self.r = rl
        self.requested = is_raspberry_pi() if fullscreen is None else bool(fullscreen)
        self._mode = 'windowed'
        self._started = False

    @property
    def enabled(self):
        return self._mode != 'windowed'

    def _borderless(self):
        flag = getattr(self.r, 'FLAG_BORDERLESS_WINDOWED_MODE', None)
        query = getattr(self.r, 'is_window_state', None)
        return bool(query(flag)) if flag is not None and callable(query) else False

    def _native_fullscreen(self):
        query = getattr(self.r, 'is_window_fullscreen', None)
        return bool(query()) if callable(query) else False

    def start(self):
        """Apply the initial preference once; call only after init_window()."""
        if self._started:
            return self.enabled
        self._started = True
        if self._borderless():
            self._mode = 'borderless'
        elif self._native_fullscreen():
            # DRM/KMS has no windowed desktop to restore. Also preserve any
            # fullscreen state supplied by an external launcher/backend.
            self._mode = 'native'
        if self.requested and not self.enabled:
            self.toggle()
        return self.enabled

    def toggle(self):
        """Toggle borderless desktop mode, never exclusive video modes."""
        borderless = self._borderless() or self._mode == 'borderless'
        if not borderless and (self._mode == 'native' or self._native_fullscreen()):
            self._mode = 'native'
            return False
        toggle = getattr(self.r, 'toggle_borderless_windowed', None)
        if not callable(toggle):
            LOG.warning('Borderless display mode is not supported by this raylib build.')
            return False
        toggle()
        self._mode = 'windowed' if borderless else 'borderless'
        return True
