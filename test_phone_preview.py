import base64
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

from phone_preview import make_preview_handler, preview_origin, write_access_file
from web_core import Store


class PhonePreviewTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.folder.name) / 'phone.sqlite3')
        self.main_store = Store(Path(self.folder.name) / 'main.sqlite3')
        self.main_owner, _ = self.main_store.session(None)
        self.main_store.preferences(self.main_owner, {'city':'深圳市','area':'南山区'})
        self.password = 'test-only-random-access-password-012345'
        self.origin = 'https://coffee-test.trycloudflare.com'
        self.auth = 'Basic ' + base64.b64encode(('coffee:' + self.password).encode()).decode()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_preview_handler(
            self.store, self.password, self.origin, time.monotonic() + 60))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.folder.cleanup()

    def request(self, path, auth=None, method='GET', origin=None, host='coffee-test.trycloudflare.com', body=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        headers = {'Host':host}
        if auth is not None:
            headers['Authorization'] = auth
        if origin:
            headers.update({'Origin':origin, 'X-Coffee-Client':'web-v1', 'Content-Type':'application/json'})
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        status, values, data = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return status, values, data

    def test_every_data_and_script_route_is_gated_before_creating_sessions(self):
        for route in ['/', '/app.js', '/api/state', '/api/export', '/_AMapService/v4/ip']:
            status, headers, data = self.request(route)
            self.assertEqual(status, 401)
            self.assertIn('Basic realm=', headers['WWW-Authenticate'])
            self.assertNotIn('Set-Cookie', headers)
            self.assertNotIn(self.password.encode(), data)
        self.assertEqual(self.request('/api/preferences', method='POST', body='{}')[0], 401)
        self.assertEqual(self.request('/api/state', auth='Basic incorrect')[0], 401)
        with self.store.connect() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM users').fetchone()[0], 0)

    def test_authorized_preview_uses_separate_data_and_secure_cookie(self):
        status, headers, data = self.request('/api/state', auth=self.auth)
        self.assertEqual(status, 200)
        self.assertIn('; Secure', headers['Set-Cookie'])
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertEqual(json.loads(data)['records'], [])
        self.assertEqual(json.loads(data)['preferences']['city'], '北京')
        self.assertEqual(self.main_store.state(self.main_owner)['preferences']['city'], '深圳市')

    def test_only_declared_host_and_same_origin_mutations_are_accepted(self):
        self.assertEqual(self.request('/api/state', auth=self.auth, host='other.example')[0], 403)
        self.assertEqual(self.request('/api/preferences', auth=self.auth, method='POST',
            origin='https://other.example', body='{}')[0], 403)
        status, _, data = self.request('/api/preferences', auth=self.auth, method='POST',
            origin=self.origin, body=json.dumps({'city':'测试城市','area':'测试区域'}))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)['preferences']['city'], '测试城市')

    def test_expired_preview_refuses_data_even_with_valid_password(self):
        handler = make_preview_handler(self.store, self.password, self.origin, time.monotonic() - 1)
        expired = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=expired.handle_request, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection('127.0.0.1', expired.server_port, timeout=5)
            connection.request('GET', '/api/state', headers={'Authorization':self.auth})
            response = connection.getresponse()
            self.assertEqual(response.status, 410)
            self.assertNotIn(b'preferences', response.read())
            connection.close()
        finally:
            expired.server_close()
            thread.join()

    def test_credentials_stay_in_private_local_file_and_origin_requires_https(self):
        target = write_access_file(Path(self.folder.name), self.origin, self.password)
        self.assertEqual(os.stat(target).st_mode & 0o777, 0o600)
        self.assertIn(self.password, target.read_text())
        for origin in ['http://coffee-test.trycloudflare.com', 'https://evil.example',
                       self.origin + '/other', self.origin + '?key=secret',
                       'https://user:pass@coffee-test.trycloudflare.com']:
            with self.assertRaises(ValueError):
                preview_origin(origin)


if __name__ == '__main__':
    unittest.main()
