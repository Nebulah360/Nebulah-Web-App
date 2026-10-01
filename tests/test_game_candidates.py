"""Candidate exports are measurements, never catalog edits or trust grants."""
import copy
import http.client
import json
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bridge'))
from game_catalog import candidate_from_inspection, load_games, verify_game
from server import Bridge, Handler, HTTPServer, MAX_GAME_INSPECTIONS, validate_xex
from test_bridge import fixture
from test_game_catalog import game_fixture


class Candidates(unittest.TestCase):
    def setUp(self):
        self.v = validate_xex(game_fixture())
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.catalog = Path(self.tmp.name) / 'games.json'

    def candidate(self, **kwargs):
        return candidate_from_inspection(kwargs.get('v', self.v), kwargs.get('filename', 'default_mp.xex'),
                                         kwargs.get('title', 'Test game'), kwargs.get('provenance', 'Synthetic test bytes'))

    def write(self, candidate):
        self.catalog.write_text(json.dumps({'schema_version': 1, 'builds': [candidate]}))

    def test_exact_measurement_schema_and_deterministic_id(self):
        before = copy.deepcopy(self.v)
        c = self.candidate(title=' Test game ', provenance=' Synthetic test bytes ')
        for k in ('title_id', 'media_id', 'version', 'base_version'):
            self.assertEqual(c[k], self.v['metadata'][k])
        self.assertEqual((c['filename'], c['sha256'], c['size']), ('default_mp.xex', self.v['hash'], len(game_fixture())))
        self.assertEqual((c['title'], c['provenance']), ('Test game', 'Synthetic test bytes'))
        self.assertEqual(c, self.candidate())
        self.assertEqual(self.v, before)
        self.assertNotEqual(c['id'], self.candidate(filename='default.xex')['id'])
        self.write(c)
        self.assertEqual(load_games(self.catalog)[0], [c])

    def test_unknown_file_is_exportable_but_never_trusted(self):
        c = self.candidate(filename='unknown-mode.xex')
        self.assertEqual(c['state'], 'candidate')
        self.assertIs(c['unmodified'], False)
        self.assertNotIn('review', c)
        self.write(c)
        result = verify_game(self.v, c['filename'], self.catalog)
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['references'], [])
        c['state'] = 'reviewed'
        self.write(c)
        with self.assertRaises(ValueError):
            load_games(self.catalog)
        # Only a separate review with explicit evidence changes verification.
        c.update(unmodified=True, review={'reviewer': 'test', 'date': '2026-10-01',
                                         'evidence': 'Synthetic unit test only', 'hardware_test': 'Not hardware evidence; test fixture'})
        self.write(c)
        self.assertEqual(verify_game(self.v, c['filename'], self.catalog)['status'], 'verified')

    def test_injected_trust_and_private_metadata_are_not_copied(self):
        self.v.update(state='reviewed', unmodified=True, review={'evidence': 'fake'}, trusted=True)
        self.v['metadata'].update(self.v)
        self.v['metadata']['cpu_key'] = 'must not export'
        c = self.candidate()
        self.assertEqual(set(c), {'id', 'title', 'provenance', 'filename', 'title_id', 'media_id',
                                 'version', 'base_version', 'sha256', 'size', 'state', 'unmodified'})
        self.assertEqual(c['state'], 'candidate')
        self.assertIs(c['unmodified'], False)

    def test_malformed_or_missing_execution_metadata(self):
        for metadata in (None, {}, [], 'bad'):
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                self.candidate(v={**self.v, 'metadata': metadata})
        for key in ('title_id', 'media_id', 'version', 'base_version'):
            for value in (None, True, 1, '', '1234', '123456789', 'abcdefgh', '1234567G'):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.candidate(v={**self.v, 'metadata': {**self.v['metadata'], key: value}})

    def test_malformed_hash_size_filename_and_uninspected_files(self):
        for key, values in {'hash': [None, 'a'*63, 'A'*64, 1], 'size': [None, True, 23, 64*1024*1024+1, 600.0],
                            'valid': [False, None, 1], 'plugin': [True, None, 0]}.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.candidate(v={**self.v, key: value})
        for filename in (None, '', 'file.txt', '../default.xex', 'Test:\\default.xex', 'bad\n.xex'):
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                self.candidate(filename=filename)

    def test_title_and_provenance_are_required_not_inferred(self):
        for key in ('title', 'provenance'):
            for value in (None, '', '   ', '\t', 'bad\ntext', 'x'*1025, 123):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.candidate(**{key: value})

    def test_cli_uses_same_generator_and_validates_user_fields(self):
        path = Path(self.tmp.name) / 'default_mp.xex'
        path.write_bytes(game_fixture())
        cmd = [sys.executable, str(ROOT / 'tools/game_baselines.py'), 'propose', str(path),
               '--id', 'test-cli', '--title', 'Test game', '--provenance', 'Synthetic test bytes']
        p = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout), {**self.candidate(), 'id': 'test-cli'})
        for flag, value in (('--id', 'bad id'), ('--title', ' '), ('--provenance', '')):
            invalid = cmd.copy()
            invalid[invalid.index(flag)+1] = value
            p = subprocess.run(invalid, capture_output=True, text=True)
            self.assertEqual(p.returncode, 2)
            self.assertEqual(p.stdout, '')


class Console(Bridge):
    """Use real bounded inspection with a synthetic read-only console adapter."""
    def __init__(self):
        super().__init__('unused')
        self.target = 'test-console'
        self.drives = ['Test:\\']
        self.files = {'Test:\\unknown.xex': game_fixture()}
        self.calls = []

    def adapter(self, action, **kwargs):
        self.calls.append(action)
        if action == 'receive':
            if kwargs['path'] not in self.files:
                raise ValueError('File not found')
            Path(kwargs['local']).write_bytes(self.files[kwargs['path']])
            return {}
        if action == 'status':
            return {'drives': self.drives}
        raise AssertionError('Unexpected console operation: ' + action)


class CandidateAPI(unittest.TestCase):
    def setUp(self):
        self.bridge = Console()

    def inspect(self):
        return self.bridge.dispatch('games/inspect', {'path': 'Test:\\unknown.xex'})

    def propose(self, inspection, **extra):
        return self.bridge.dispatch('games/propose', {'inspection_id': inspection,
                                    'title': 'Test title', 'provenance': 'Synthetic test bytes', **extra})

    def test_export_only_measured_snapshot_no_catalog_or_console_writes(self):
        before = (ROOT / 'registry/games.json').read_bytes()
        with patch('server.GamePaths', side_effect=AssertionError('No local shortcut DB needed')):
            inspected = self.inspect()
            self.assertEqual(inspected['verification']['status'], 'unknown')
            result = self.propose(inspected['inspection_id'])
        self.assertEqual(result['candidate']['sha256'], inspected['verification']['actual_sha256'])
        self.assertEqual(result['candidate']['filename'], 'unknown.xex')
        self.assertEqual(self.bridge.calls, ['receive'])
        self.assertEqual(self.bridge.tickets, {})
        self.assertEqual((ROOT / 'registry/games.json').read_bytes(), before)

    def test_client_cannot_override_measurements_or_review(self):
        inspection = self.inspect()['inspection_id']
        for key, value in {'sha256': '0'*64, 'metadata': {}, 'filename': 'other.xex', 'size': 1,
                           'state': 'reviewed', 'unmodified': True, 'review': {}, 'trusted': True, 'path': 'Test:\\other.xex'}.items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.propose(inspection, **{key: value})
        for key in ('title', 'provenance'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.propose(inspection, **{key: ''})

    def test_missing_expired_disconnected_and_reconnected_inspections(self):
        for inspection in (None, 'unknown', [], {}):
            with self.subTest(inspection=inspection), self.assertRaises(ValueError):
                self.propose(inspection)
        inspection = self.inspect()['inspection_id']
        self.bridge.game_inspections[inspection]['expires'] = 0
        with self.assertRaises(ValueError):
            self.propose(inspection)
        inspection = self.inspect()['inspection_id']
        self.bridge.target = None
        with self.assertRaises(ValueError):
            self.propose(inspection)
        self.bridge.dispatch('connect', {'target': 'different-console'})
        with self.assertRaises(ValueError):
            self.propose(inspection)

    def test_snapshot_bounds_and_changed_file_require_new_inspection(self):
        old = self.inspect()['inspection_id']
        old_hash = self.propose(old)['candidate']['sha256']
        self.bridge.files['Test:\\unknown.xex'] = game_fixture()[:-1] + b'X'
        # Export documents the bytes read, not an unsupported freshness claim.
        self.assertEqual(self.propose(old)['candidate']['sha256'], old_hash)
        fresh = self.inspect()['inspection_id']
        self.assertNotEqual(self.propose(fresh)['candidate']['sha256'], old_hash)
        for _ in range(MAX_GAME_INSPECTIONS):
            self.inspect()
        self.assertEqual(len(self.bridge.game_inspections), MAX_GAME_INSPECTIONS)
        with self.assertRaises(ValueError):
            self.propose(old)

    def test_unknown_catalog_is_ok_missing_file_plugin_and_missing_metadata_are_not(self):
        self.assertIn('inspection_id', self.inspect())
        for path in ('Unknown:\\unknown.xex', 'Test:\\missing.xex', 'Test:\\file.txt'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.bridge.dispatch('games/inspect', {'path': path})
        for data in (fixture(), fixture(9)):
            self.bridge.files['Test:\\unknown.xex'] = data
            inspected = self.inspect()
            self.assertNotIn('inspection_id', inspected)
            self.assertIn('candidate_unavailable', inspected)
        bad = bytearray(game_fixture())
        struct.pack_into('>I', bad, 28, 510)
        self.bridge.files['Test:\\unknown.xex'] = bad
        with self.assertRaises(ValueError):
            self.inspect()


class CandidateHTTP(unittest.TestCase):
    def test_paired_same_origin_required_and_response_does_not_grant_trust(self):
        bridge = Console()
        inspection = bridge.dispatch('games/inspect', {'path': 'Test:\\unknown.xex'})['inspection_id']
        server = HTTPServer(('127.0.0.1', 0), Handler)
        host = '127.0.0.1:' + str(server.server_port)
        server.allowed_hosts = {host}
        server.token = 'test-token'
        server.bridge = bridge
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for token, origin, expected in [('bad', 'http://'+host, 401), ('test-token', 'http://invalid.test', 403), ('test-token', 'http://'+host, 200)]:
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
                conn.request('POST', '/api/games/propose', json.dumps({'inspection_id': inspection, 'title': 'Fixture', 'provenance': 'Test bytes'}),
                             {'Host': host, 'Origin': origin, 'Authorization': 'Bearer '+token, 'Content-Type': 'application/json'})
                response = conn.getresponse()
                body = json.loads(response.read())
                self.assertEqual(response.status, expected)
                self.assertEqual(response.getheader('Cache-Control'), 'no-store')
                if expected == 200:
                    self.assertEqual(body['candidate']['state'], 'candidate')
                    self.assertIs(body['candidate']['unmodified'], False)
                    self.assertNotIn('review', body['candidate'])
                    self.assertNotIn('ticket', body)
                conn.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
