# SPDX-License-Identifier: GPL-2.0+
"""Bound pronotepy's HTTP requests without changing requests globally.

pronotepy 2.15.7 does not expose a session factory or a timeout argument. Its
client constructs _Communication before making its first request. Substitute
that factory only for the duration of an Ippon sync and restore it afterwards.
The requests Session class and the weather/football transports are untouched.
"""

from contextlib import contextmanager
import logging
import threading

from requests.adapters import HTTPAdapter

LOGGER = logging.getLogger(__name__)
REQUEST_TIMEOUT = (5, 15)  # connect and read timeouts, in seconds
_TRANSPORT_LOCK = threading.RLock()


class TimeoutAdapter(HTTPAdapter):
    def __init__(self, timeout=REQUEST_TIMEOUT):
        super().__init__()
        self.default_timeout = timeout

    def send(self, request, stream=False, timeout=None, verify=True, cert=None,
             proxies=None):
        response = super().send(
            request, stream=stream,
            timeout=self.default_timeout if timeout is None else timeout,
            verify=verify, cert=cert, proxies=proxies)
        # Reject HTTP errors before pronotepy tries to parse the initial page.
        if request.method == 'GET':
            response.raise_for_status()
        return response


@contextmanager
def bounded_communication():
    """Install timeouts before login, then close all created HTTP sessions."""
    from pronotepy import clients

    with _TRANSPORT_LOCK:
        original = clients._Communication
        sessions = []

        class TimedCommunication(original):
            def __init__(self, *args, **kwargs):
                try:
                    super().__init__(*args, **kwargs)
                except Exception:
                    session = getattr(self, 'session', None)
                    if session is not None:
                        sessions.append(session)
                    raise
                sessions.append(self.session)
                self.session.mount('https://', TimeoutAdapter())
                self.session.mount('http://', TimeoutAdapter())

        clients._Communication = TimedCommunication
        try:
            yield
        finally:
            clients._Communication = original
            for session in reversed(sessions):
                try:
                    session.close()
                except Exception:
                    LOGGER.warning('Pronote HTTP cleanup failed.')
