from contextlib import closing
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

from demo_app import DemoStore, make_demo_handler
from web_app import make_handler
from web_core import Store, AppError


def menu(**changes):
    return dict({'id': str(uuid.uuid4()), 'product': '测试产品', 'kind': 'menu', 'brew': '手冲',
                 'cafe': '测试分店', 'address': '测试地址', 'source_note': '明确标记的测试豆单'}, **changes)


class MenuBatchTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.folder.name) / 'batch.sqlite3')
        self.owner, _ = self.store.session(None)
        self.other, _ = self.store.session(None)
        self.original = self.store.save(self.owner, {'product': '原个人体验', 'reaction': 'like'})

    def tearDown(self):
        self.folder.cleanup()

    def test_save_is_atomic_if_any_product_is_invalid(self):
        before = self.store.state(self.owner)
        with self.assertRaisesRegex(AppError, '第 2 款'):
            self.store.save_menu_batch(self.owner, {'items': [menu(), menu(source_note='')]})
        self.assertEqual(self.store.state(self.owner), before)

    def test_identical_retry_does_not_duplicate_or_update_evidence_timestamp(self):
        items = [menu(product='A'), menu(product='B')]
        first = self.store.save_menu_batch(self.owner, {'items': items})
        before = self.store.state(self.owner)
        second = self.store.save_menu_batch(self.owner, {'items': items})
        self.assertEqual(first, {'count': 2, 'created': 2, 'unchanged': 0})
        self.assertEqual(second, {'count': 2, 'created': 0, 'unchanged': 2})
        self.assertEqual(self.store.state(self.owner), before)

    def test_conflicting_retry_never_overwrites_an_existing_record_or_inserts_partial_batch(self):
        saved = menu()
        self.store.save_menu_batch(self.owner, {'items': [saved]})
        before = self.store.state(self.owner)
        for conflict in [dict(saved, product='意外覆盖'), menu(id=self.original['id'])]:
            with self.subTest(conflict=conflict['id']), self.assertRaises(AppError) as ctx:
                self.store.save_menu_batch(self.owner, {'items': [menu(product='不应部分保存'), conflict]})
            self.assertEqual(ctx.exception.status, 409)
            self.assertEqual(self.store.state(self.owner), before)

    def test_duplicate_ids_and_limits_are_rejected(self):
        row = menu()
        for items in [[], [row, row], [menu() for _ in range(21)], [dict(row, id='bad')], [dict(row, kind='tasting')]]:
            with self.subTest(size=len(items)), self.assertRaises(AppError):
                self.store.save_menu_batch(self.owner, {'items': items})
        self.assertEqual(len(self.store.state(self.owner)['records']), 1)

    def test_batch_has_no_personal_judgment_and_owner_cannot_be_spoofed(self):
        row = menu(reaction='like', tasted_flavors=['伪造实际体验'], owner=self.owner, id=self.original['id'])
        self.store.save_menu_batch(self.other, {'items': [row]})
        record = self.store.state(self.other)['records'][0]
        self.assertEqual(record['kind'], 'menu')
        self.assertEqual(record['reaction'], 'neutral')
        self.assertEqual(record['tasted_flavors'], [])
        self.assertEqual(self.store.state(self.owner)['records'], [self.original])


class MenuHttpTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict('os.environ', {}, clear=True)
        self.env.start()
        self.folder = tempfile.TemporaryDirectory()
        self.personal = Store(Path(self.folder.name) / 'personal.sqlite3')
        self.owner, _ = self.personal.session(None)
        self.personal.save(self.owner, {'product': '原有个人记录'})
        self.before = self.personal.path.read_bytes()
        self.demo = DemoStore(Path(self.folder.name) / 'demo.sqlite3')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_demo_handler(self.demo))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.folder.cleanup();self.env.stop()

    def request(self, path, data=None, cookie=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        h = {'Content-Type': 'application/json', 'X-Coffee-Client': 'web-v1', **(headers or {})}
        if cookie:
            h['Cookie'] = cookie
        connection.request('POST' if data is not None else 'GET', path, json.dumps(data) if data is not None else None, h)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_demo_has_separate_cookie_and_fictional_data_without_touching_personal_store(self):
        personal_cookie = 'coffee_session=' + self.owner
        status, headers, raw = self.request('/api/state', cookie=personal_cookie)
        data = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertTrue(headers['Set-Cookie'].startswith('coffee_demo_session='))
        self.assertNotIn('coffee_session=', headers['Set-Cookie'])
        self.assertTrue(data['demo']['enabled'])
        self.assertIn('虚构', data['demo']['notice'])
        self.assertEqual(len(data['records']), 5)
        self.assertTrue(all(r['product'].startswith('【测试】') and r['reaction'] == 'neutral' for r in data['records']))
        self.assertFalse(data['services']['maps'])
        self.assertFalse(data['services']['vision'])
        demo_cookie = headers['Set-Cookie'].split(';')[0]
        status, again, raw2 = self.request('/api/state', cookie=personal_cookie+'; '+demo_cookie)
        self.assertNotIn('Set-Cookie', again)
        self.assertEqual(json.loads(raw2)['records'], data['records'])
        self.assertEqual(self.personal.path.read_bytes(), self.before)

    def test_batch_http_roundtrip_retry_and_same_origin_protection(self):
        _, headers, _ = self.request('/api/state')
        cookie = headers['Set-Cookie'].split(';')[0]
        payload = {'items': [menu(product='新增测试 A'), menu(product='新增测试 B')]}
        self.assertEqual(json.loads(self.request('/api/menu-batch', payload, cookie)[2])['created'], 2)
        self.assertEqual(json.loads(self.request('/api/menu-batch', payload, cookie)[2])['created'], 0)
        self.assertEqual(len(json.loads(self.request('/api/state', cookie=cookie)[2])['records']), 7)
        self.assertEqual(self.request('/api/menu-batch', payload, cookie, {'Origin': 'https://other.example'})[0], 403)
        self.assertEqual(self.personal.path.read_bytes(), self.before)

    def test_all_new_modules_are_served_with_script_security_headers(self):
        for path in ['/menu-drafts.js', '/menu-batch.js']:
            status, headers, _ = self.request(path)
            self.assertEqual(status, 200)
            self.assertIn('nosniff', headers['X-Content-Type-Options'])
