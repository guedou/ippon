# SPDX-License-Identifier: GPL-2.0+
"""Keep a renewed Pronote token when a later constructor request fails.

All credentials are invented. Configuration writes are intercepted; only the
successful sync's JSON cache is allowed in a temporary directory.
"""
import configparser
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ippon import pronote


UNCHANGED = object()


def settings(page='eleve.html'):
    config = configparser.ConfigParser(interpolation=None)
    config['pronote'] = {
        'pronote_url': 'https://example.invalid/' + page,
        'username': 'synthetic-user',
        'password': 'synthetic-old-token',
        'uuid': 'synthetic-device',
    }
    return config


def fake_client(new_password=UNCHANGED, error=None, on_lessons=None):
    """Emulate token_login's cls(...) and post-renewal resource discovery."""
    exported = []

    class FakeClient:
        @classmethod
        def token_login(cls, **credentials):
            return cls(**credentials)

        def __init__(self, **credentials):
            self.credentials = dict(credentials)
            self.password = credentials['password']
            self.logged_in = False
            if new_password is not UNCHANGED:
                self.password = new_password
            if error is not None:
                raise error
            self.logged_in = True

        def export_credentials(self):
            exported.append(self.password)
            return {**self.credentials, 'password': self.password}

        def lessons(self, *args):
            if on_lessons is not None:
                on_lessons()
            return []

        def homework(self, *args):
            return []

    FakeClient.exports = exported
    return FakeClient


class TokenLoginTests(unittest.TestCase):
    def test_renewed_token_survives_constructor_resource_failure_for_both_account_types(self):
        for page in ('eleve.html', 'parent.html'):
            with self.subTest(page=page):
                config = settings(page)
                original = KeyError('ressource')
                client_class = fake_client('synthetic-new-token', original)
                written = []
                with patch.object(pronote, '_write_config',
                                  side_effect=lambda current: written.append(dict(current['pronote']))):
                    with self.assertRaises(KeyError) as failure:
                        pronote._token_login(config, client_class, pronote._credentials(config))
                self.assertIs(failure.exception, original)
                self.assertEqual(len(written), 1)
                self.assertEqual(written[0]['password'], 'synthetic-new-token')
                self.assertEqual(written[0]['pronote_url'], 'https://example.invalid/' + page)
                self.assertEqual(written[0]['username'], 'synthetic-user')
                self.assertEqual(written[0]['uuid'], 'synthetic-device')
                self.assertEqual(config['pronote']['password'], 'synthetic-new-token')

    def test_unchanged_token_does_not_rewrite_config_on_constructor_failure(self):
        config = settings()
        original = KeyError('ressource')
        client_class = fake_client(error=original)
        with patch.object(pronote, '_write_config') as write:
            with self.assertRaises(KeyError) as failure:
                pronote._token_login(config, client_class, pronote._credentials(config))
        self.assertIs(failure.exception, original)
        write.assert_not_called()
        self.assertEqual(client_class.exports, [])
        self.assertEqual(config['pronote']['password'], 'synthetic-old-token')

    def test_non_string_token_never_overwrites_valid_config_on_constructor_failure(self):
        for invalid in (None, False, 42, ['not-a-token'], {'token': 'not-a-string'}):
            with self.subTest(value=invalid):
                config = settings()
                original = KeyError('ressource')
                client_class = fake_client(invalid, original)
                with patch.object(pronote, '_write_config') as write:
                    with self.assertRaises(KeyError) as failure:
                        pronote._token_login(config, client_class, pronote._credentials(config))
                self.assertIs(failure.exception, original)
                write.assert_not_called()
                self.assertEqual(client_class.exports, [])
                self.assertEqual(config['pronote']['password'], 'synthetic-old-token')

    def test_failure_before_password_initialization_does_not_mask_original_exception(self):
        config = settings()
        original = KeyError('ressource')

        class FailingClient:
            @classmethod
            def token_login(cls, **credentials):
                return cls(**credentials)

            def __init__(self, **credentials):
                raise original

        with patch.object(pronote, '_write_config') as write:
            with self.assertRaises(KeyError) as failure:
                pronote._token_login(config, FailingClient, pronote._credentials(config))
        self.assertIs(failure.exception, original)
        write.assert_not_called()

    def test_renewed_token_storage_failure_is_reported_as_credentials_storage_error(self):
        config = settings()
        client_class = fake_client('synthetic-new-token', KeyError('ressource'))
        with patch.object(pronote, '_write_config', side_effect=OSError('synthetic-private-path')) as write:
            with self.assertRaises(pronote.PronoteSyncError) as failure:
                pronote._token_login(config, client_class, pronote._credentials(config))
        write.assert_called_once_with(config)
        self.assertEqual(failure.exception.stage, 'credentials')
        self.assertEqual(failure.exception.code, 'storage')
        self.assertNotIn('synthetic-new-token', str(failure.exception))
        self.assertNotIn('synthetic-private-path', str(failure.exception))
        self.assertNotIn('ressource', str(failure.exception))

    def test_success_returns_client_and_leaves_persistence_to_existing_success_path(self):
        config = settings()
        credentials = pronote._credentials(config)
        client_class = fake_client('synthetic-new-token')
        with patch.object(pronote, '_write_config') as write:
            client = pronote._token_login(config, client_class, credentials)
            self.assertIsInstance(client, client_class)
            self.assertTrue(client.logged_in)
            self.assertEqual(client.password, 'synthetic-new-token')
            self.assertEqual(client.credentials, credentials)
            write.assert_not_called()
            # The normal path already persists immediately after token_login.
            pronote._save_credentials(config, client)
            write.assert_called_once_with(config)
        self.assertEqual(config['pronote']['password'], 'synthetic-new-token')
        self.assertEqual(credentials['password'], 'synthetic-old-token')

    def test_successful_sync_persists_renewal_before_collecting_lessons(self):
        config = settings()
        written = []

        def check_persisted_before_lessons():
            self.assertTrue(written, 'Token must be saved before lesson retrieval')
            self.assertEqual(written[-1]['password'], 'synthetic-new-token')

        client_class = fake_client('synthetic-new-token', on_lessons=check_persisted_before_lessons)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cache.json'
            with patch.object(pronote.pronotepy, 'Client', client_class), \
                    patch.object(pronote, '_write_config',
                                 side_effect=lambda current: written.append(dict(current['pronote']))):
                result = pronote.sync_range(config, days_ahead=0, cache_path=path)
            self.assertTrue(path.is_file())
            self.assertEqual(len(result['days']), 1)
            self.assertEqual(config['pronote']['password'], 'synthetic-new-token')


if __name__ == '__main__':
    unittest.main()
