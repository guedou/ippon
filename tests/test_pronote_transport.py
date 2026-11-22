# SPDX-License-Identifier: GPL-2.0+
"""Exercise installed pronotepy transport wiring with every HTTP send mocked."""

from contextlib import ExitStack
import unittest
from unittest.mock import MagicMock, patch

import pronotepy
from pronotepy import clients
import requests
from requests.adapters import HTTPAdapter

from ippon.pronote_transport import (REQUEST_TIMEOUT, TimeoutAdapter,
                                     bounded_communication)


class TimeoutAdapterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = TimeoutAdapter()
        self.addCleanup(self.adapter.close)
        self.request = requests.Request('GET', 'https://example.invalid/eleve.html').prepare()

    def test_default_timeout_reaches_http_adapter_without_changing_tls(self):
        with patch.object(HTTPAdapter, 'send', autospec=True) as send:
            self.adapter.send(self.request)
        self.assertEqual(REQUEST_TIMEOUT, (5, 15))
        self.assertEqual(send.call_args.kwargs['timeout'], (5, 15))
        self.assertIs(send.call_args.kwargs['verify'], True)
        self.assertIsNone(send.call_args.kwargs['cert'])
        self.assertIs(send.call_args.args[1], self.request)

    def test_explicit_timeout_stream_tls_and_proxy_options_are_preserved(self):
        proxies = {'https': 'http://proxy.example.invalid:3128'}
        for timeout in ((2, 7), 9, 0):
            with self.subTest(timeout=timeout):
                with patch.object(HTTPAdapter, 'send', autospec=True) as send:
                    self.adapter.send(self.request, timeout=timeout, stream=True,
                                      verify='/synthetic-ca.pem',
                                      cert=('/synthetic-cert.pem', '/synthetic-key.pem'),
                                      proxies=proxies)
                options = send.call_args.kwargs
                self.assertEqual(options['timeout'], timeout)
                self.assertTrue(options['stream'])
                self.assertEqual(options['verify'], '/synthetic-ca.pem')
                self.assertEqual(options['cert'], ('/synthetic-cert.pem', '/synthetic-key.pem'))
                self.assertIs(options['proxies'], proxies)

    def test_http_get_error_is_propagated_without_parsing_response(self):
        response = requests.Response()
        response.status_code = 403
        response.url = 'https://example.invalid/eleve.html'
        with patch.object(HTTPAdapter, 'send', autospec=True, return_value=response):
            with self.assertRaises(requests.HTTPError) as caught:
                self.adapter.send(self.request)
        self.assertIs(caught.exception.response, response)

    def test_adapter_can_override_default_without_overriding_explicit_timeout(self):
        custom = TimeoutAdapter(timeout=(3, 8))
        self.addCleanup(custom.close)
        with patch.object(HTTPAdapter, 'send', autospec=True) as send:
            custom.send(self.request, timeout=None)
        self.assertEqual(send.call_args.kwargs['timeout'], (3, 8))


class BoundedCommunicationTests(unittest.TestCase):
    def setUp(self):
        self.original_factory = clients._Communication
        self.original_session_class = requests.Session

    def assert_restored(self):
        self.assertIs(clients._Communication, self.original_factory)
        self.assertIs(requests.Session, self.original_session_class)

    def test_real_initialise_first_get_is_bounded_then_session_closes_on_timeout(self):
        # The real 2.15.7 constructor creates Session; initialise sends its first
        # GET. Mock the base adapter's send, not Session or the Pronote methods.
        with ExitStack() as patches:
            send = patches.enter_context(patch.object(
                HTTPAdapter, 'send', autospec=True,
                side_effect=requests.Timeout('synthetic timeout')))
            with self.assertRaises(requests.Timeout):
                with bounded_communication():
                    self.assertIsNot(clients._Communication, self.original_factory)
                    communication = clients._Communication(
                        'https://example.invalid/eleve.html', None, False)
                    close = patches.enter_context(patch.object(
                        communication.session, 'close', wraps=communication.session.close))
                    self.assertIsInstance(communication.session.get_adapter('https://example.invalid'),
                                          TimeoutAdapter)
                    self.assertIsInstance(communication.session.get_adapter('http://example.invalid'),
                                          TimeoutAdapter)
                    communication.initialise()
            close.assert_called_once_with()
            send.assert_called_once()
            adapter, request = send.call_args.args
            self.assertIsInstance(adapter, TimeoutAdapter)
            self.assertEqual(request.method, 'GET')
            self.assertEqual(send.call_args.kwargs['timeout'], (5, 15))
            self.assertIs(send.call_args.kwargs['verify'], True)
        self.assert_restored()

    def test_real_client_construction_uses_factory_before_any_http_request(self):
        with patch.object(HTTPAdapter, 'send', autospec=True,
                          side_effect=requests.Timeout('synthetic timeout')) as send:
            with self.assertRaises(requests.Timeout):
                with bounded_communication():
                    pronotepy.Client.token_login(
                        'https://example.invalid/eleve.html',
                        'synthetic-user', 'synthetic-token', 'synthetic-uuid')
        self.assert_restored()
        send.assert_called_once()
        adapter, request = send.call_args.args
        self.assertIsInstance(adapter, TimeoutAdapter)
        self.assertEqual(request.method, 'GET')
        self.assertEqual(send.call_args.kwargs['timeout'], (5, 15))
        self.assertIs(send.call_args.kwargs['verify'], True)

    def test_all_created_sessions_close_on_normal_exit(self):
        with ExitStack() as patches:
            with bounded_communication():
                first = clients._Communication('https://example.invalid/eleve.html', None, False)
                second = clients._Communication('https://example.invalid/parent.html', None, True)
                first_close = patches.enter_context(patch.object(first.session, 'close', wraps=first.session.close))
                second_close = patches.enter_context(patch.object(second.session, 'close', wraps=second.session.close))
            first_close.assert_called_once_with()
            second_close.assert_called_once_with()
        self.assert_restored()

    def test_unrelated_requests_sessions_are_not_modified_or_closed(self):
        external = requests.Session()
        self.addCleanup(external.close)
        existing_https = external.get_adapter('https://example.invalid')
        existing_http = external.get_adapter('http://example.invalid')
        with patch.object(external, 'close', wraps=external.close) as close:
            with bounded_communication():
                self.assertIs(requests.Session, self.original_session_class)
                self.assertIs(external.get_adapter('https://example.invalid'), existing_https)
                self.assertIs(external.get_adapter('http://example.invalid'), existing_http)
                another = requests.Session()
                try:
                    self.assertIs(type(another.get_adapter('https://example.invalid')), HTTPAdapter)
                    self.assertIs(type(another.get_adapter('http://example.invalid')), HTTPAdapter)
                finally:
                    another.close()
                clients._Communication('https://example.invalid/eleve.html', None, False)
            close.assert_not_called()
        self.assert_restored()

    def test_successful_post_returns_original_result_unchanged(self):
        result = {'dataSec': {'data': 'synthetic-result'}}
        with patch.object(self.original_factory, 'post', autospec=True,
                          return_value=result) as post:
            with bounded_communication():
                communication = clients._Communication(
                    'https://example.invalid/eleve.html', None, False)
                received = communication.post('Identification', {})
        self.assertIs(received, result)
        self.assertEqual(received, {'dataSec': {'data': 'synthetic-result'}})
        post.assert_called_once_with(communication, 'Identification', {})
        self.assert_restored()

    def test_parent_constructor_failure_after_session_creation_still_closes(self):
        real_init = self.original_factory.__init__
        created = []

        def fail_after_session(communication, *args, **kwargs):
            real_init(communication, *args, **kwargs)
            communication.session.close = MagicMock(wraps=communication.session.close)
            created.append(communication.session)
            raise RuntimeError('synthetic constructor failure')

        with patch.object(self.original_factory, '__init__', new=fail_after_session):
            with self.assertRaises(RuntimeError):
                with bounded_communication():
                    clients._Communication('https://example.invalid/eleve.html', None, False)
        self.assert_restored()
        self.assertEqual(len(created), 1)
        created[0].close.assert_called_once_with()

    def test_cleanup_error_does_not_mask_original_failure_or_skip_other_sessions(self):
        with ExitStack() as patches:
            with self.assertLogs('ippon.pronote_transport', level='WARNING') as logs:
                with self.assertRaisesRegex(ValueError, 'original failure'):
                    with bounded_communication():
                        first = clients._Communication('https://example.invalid/eleve.html', None, False)
                        second = clients._Communication('https://example.invalid/parent.html', None, True)
                        first_close = patches.enter_context(patch.object(first.session, 'close', wraps=first.session.close))
                        # Close real resources before making the cleanup hook fail.
                        second.session.close()
                        second_close = patches.enter_context(patch.object(
                            second.session, 'close', side_effect=OSError('synthetic-private-detail')))
                        raise ValueError('original failure')
            first_close.assert_called_once_with()
            second_close.assert_called_once_with()
            self.assertNotIn('synthetic-private-detail', ' '.join(logs.output))
        self.assert_restored()


if __name__ == '__main__':
    unittest.main()
