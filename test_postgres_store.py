"""Storage contract tests. Integration cases use an isolated PostgreSQL schema."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

import psycopg

from cloud_storage import open_cloud_store
from postgres_store import PostgresStore, UNAVAILABLE, validate_database_url
from web_core import AppError, DEFAULT_PREFS


EXAMPLE_URL = 'postgresql://test:fictional-secret@ep-example.ap-southeast-1.aws.neon.tech/coffee?sslmode=require'
TEST_DSN = os.environ.get('COFFEE_TEST_POSTGRES_DSN')


def menu(**values):
    return dict({'id': str(uuid.uuid4()), 'kind': 'menu', 'product': '测试产品', 'brew': '手冲',
                 'cafe': '虚构测试店', 'address': '虚构地址', 'source_note': '自动测试资料'}, **values)


class PostgresConfigurationTests(unittest.TestCase):
    def test_invalid_urls_and_extra_connection_options_never_reach_driver(self):
        for value in ['', None, 'https://console.neon.tech', 'postgres://user:secret@localhost/db',
                      'postgres://user:secret@fake.neon.tech.evil.test/db',
                      'postgres://user@ep-test.neon.tech/db', EXAMPLE_URL+'&options=unsafe',
                      EXAMPLE_URL+'&sslmode=disable', EXAMPLE_URL+'#fragment']:
            with self.subTest(value=type(value).__name__), self.assertRaises(ValueError) as error:
                validate_database_url(value)
            self.assertNotIn('fictional-secret', str(error.exception))
        self.assertEqual(validate_database_url(EXAMPLE_URL), EXAMPLE_URL)

    def test_unavailable_remote_never_creates_local_database_or_exposes_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('cloud_storage.EPHEMERAL_ROOT', Path(folder)), \
                 patch('psycopg.connect', side_effect=psycopg.OperationalError(EXAMPLE_URL)):
                with self.assertRaises(AppError) as error:
                    open_cloud_store({'COFFEE_STORAGE_MODE': 'postgres', 'DATABASE_URL': EXAMPLE_URL})
            self.assertEqual(error.exception.status, 503)
            self.assertEqual(str(error.exception), UNAVAILABLE)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_tls_and_timeouts_cannot_be_disabled_by_url(self):
        def failed_connector(dsn, **options):
            self.assertEqual(dsn, EXAMPLE_URL)
            self.assertEqual(options['sslmode'], 'verify-full')
            self.assertEqual(options['sslrootcert'], 'system')
            self.assertEqual(options['channel_binding'], 'require')
            self.assertEqual(options['connect_timeout'], 10)
            self.assertIn('statement_timeout=15000', options['options'])
            raise psycopg.OperationalError('private connection detail')
        with self.assertRaisesRegex(AppError, '云端数据库'):
            PostgresStore(EXAMPLE_URL, connector=failed_connector)

    def test_partial_remote_configuration_cannot_silently_use_temporary_storage(self):
        with tempfile.TemporaryDirectory() as folder, patch('cloud_storage.EPHEMERAL_ROOT', Path(folder)):
            with self.assertRaises(ValueError):
                open_cloud_store({'DATABASE_URL': EXAMPLE_URL})
            with self.assertRaises(ValueError):
                open_cloud_store({'COFFEE_STORAGE_MODE': 'postgres'})
            self.assertEqual(list(Path(folder).iterdir()), [])


@unittest.skipUnless(TEST_DSN, 'COFFEE_TEST_POSTGRES_DSN is required for real PostgreSQL tests')
class PostgresIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.schema = 'qa_' + uuid.uuid4().hex
        with psycopg.connect(TEST_DSN, autocommit=True) as con:
            con.execute('CREATE SCHEMA ' + self.schema)
        self.store = self.new_store()
        self.owner, _ = self.store.session(None)
        self.other, _ = self.store.session(None)

    def tearDown(self):
        # Only this test's randomly named schema is removed, never public data.
        with psycopg.connect(TEST_DSN, autocommit=True) as con:
            con.execute('DROP SCHEMA ' + self.schema + ' CASCADE')

    def connector(self, ignored_url, **options):
        return psycopg.connect(TEST_DSN, autocommit=True,
            options='-c search_path=' + self.schema + ' -c statement_timeout=15000 -c lock_timeout=10000')

    def new_store(self):
        return PostgresStore(EXAMPLE_URL, connector=self.connector)

    def test_records_preferences_and_cookie_identity_survive_independent_process(self):
        self.store.preferences(self.owner, dict(DEFAULT_PREFS, coffee_preference='milk', brews=['拿铁']))
        row = self.store.save(self.owner, {'product': '跨进程测试记录', 'brew': '拿铁', 'reaction': 'like'})
        before = self.store.state(self.owner)
        script = '''
import json,os,psycopg
from postgres_store import PostgresStore
def connect(ignored, **options):
 return psycopg.connect(os.environ['COFFEE_TEST_POSTGRES_DSN'],autocommit=True,options='-c search_path='+os.environ['COFFEE_TEST_SCHEMA'])
store=PostgresStore(os.environ['COFFEE_TEST_EXAMPLE_URL'],connector=connect)
owner=os.environ['COFFEE_TEST_OWNER']
print(json.dumps([store.session(owner),store.state(owner)]))
'''
        result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, check=True,
            env={**os.environ, 'COFFEE_TEST_SCHEMA': self.schema, 'COFFEE_TEST_OWNER': self.owner,
                 'COFFEE_TEST_EXAMPLE_URL': EXAMPLE_URL})
        identity, state = json.loads(result.stdout)
        self.assertEqual(identity, [self.owner, False])
        self.assertEqual(state, before)
        self.assertEqual(state['records'][0]['id'], row['id'])

    def test_updating_record_and_preferences_preserves_owner_isolation(self):
        row = self.store.save(self.owner, {'product': '旧测试名称', 'bean': '测试豆'})
        self.store.save(self.owner, dict(row, product='新测试名称', reaction='dislike'))
        self.store.save(self.other, dict(row, product='另一身份的同编号'))
        self.assertEqual(self.store.state(self.owner)['records'][0]['product'], '新测试名称')
        self.assertEqual(self.store.state(self.other)['records'][0]['product'], '另一身份的同编号')
        self.store.delete(self.other, row['id'])
        self.assertEqual(len(self.store.state(self.owner)['records']), 1)
        self.assertEqual(self.store.state(self.other)['records'], [])
        with self.assertRaises(AppError) as error:
            self.store.delete(self.other, row['id'])
        self.assertEqual(error.exception.status, 404)

    def test_bulk_retry_conflict_and_validation_are_atomic(self):
        rows = [menu(product='测试 A'), menu(product='测试 B')]
        self.assertEqual(self.store.save_menu_batch(self.owner, {'items': rows})['created'], 2)
        before = self.store.state(self.owner)
        self.assertEqual(self.store.save_menu_batch(self.owner, {'items': rows})['created'], 0)
        for invalid in [dict(rows[0], product='冲突修改'), menu(source_note='')]:
            with self.assertRaises(AppError):
                self.store.save_menu_batch(self.owner, {'items': [menu(product='不得部分写入'), invalid]})
            self.assertEqual(self.store.state(self.owner), before)

    def test_database_failure_mid_import_rolls_back_records_and_preferences(self):
        before = self.store.state(self.owner)
        with closing(self.store.connect()) as con, con:
            con.execute("ALTER TABLE entries ADD CONSTRAINT qa_reject CHECK (strpos(data, '拒绝测试') = 0)")
        backup = {'format': 'coffee-buddy-web-v1', 'preferences': dict(DEFAULT_PREFS, city='不得部分修改'),
                  'records': [{'product': '不得部分保存'}, {'product': '拒绝测试'}]}
        with self.assertRaises(AppError) as error:
            self.store.import_records(self.owner, backup)
        self.assertEqual(error.exception.status, 503)
        self.assertEqual(self.store.state(self.owner), before)

    def test_export_import_roundtrip_preserves_preferences_and_deduplicates(self):
        self.store.preferences(self.owner, dict(DEFAULT_PREFS, brews=['测试特调'],
            brew_categories={'测试特调': 'unknown'}, coffee_preference='any'))
        row = self.store.save(self.owner, {'product': '导入测试', 'brew': '测试特调'})
        backup = dict(format='coffee-buddy-web-v1', **self.store.state(self.owner))
        self.store.import_records(self.other, backup)
        self.store.import_records(self.other, backup)
        state = self.store.state(self.other)
        self.assertEqual(len(state['records']), 1)
        self.assertEqual(state['records'][0]['id'], row['id'])
        self.assertEqual(state['preferences'], backup['preferences'])

    def test_concurrent_identical_batches_create_only_one_record(self):
        row = menu()
        def save(_):
            return self.store.save_menu_batch(self.owner, {'items': [row]})['created']
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, range(2)))
        self.assertEqual(sorted(results), [0, 1])
        self.assertEqual(len(self.store.state(self.owner)['records']), 1)

    def test_concurrent_conflicting_batches_do_not_overwrite(self):
        row = menu()
        def save(name):
            try:
                return self.store.save_menu_batch(self.owner, {'items': [dict(row, product=name)]})['created']
            except AppError as error:
                return error.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, ['并发测试 A', '并发测试 B']))
        self.assertEqual(sorted(results), [1, 409])
        self.assertEqual(len(self.store.state(self.owner)['records']), 1)
