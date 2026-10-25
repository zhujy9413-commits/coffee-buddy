import base64
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from cloud_preview import NOTICE, cloud_settings, make_cloud_handler
from web_core import Store
from cloud_storage import DailyBackups


class CloudSettingsTests(unittest.TestCase):
    def test_fails_closed_without_required_cloud_settings(self):
        settings = {'RENDER_EXTERNAL_HOSTNAME': 'coffee-test.onrender.com',
                    'PREVIEW_PASSWORD': 'test-only-password-01234567890123456789', 'AMAP_API_KEY': 'test-key'}
        self.assertEqual(cloud_settings(settings)[2], 10000)
        for field in settings:
            with self.subTest(field=field), self.assertRaises(ValueError):
                cloud_settings({**settings, field: ''})
        for host in ['localhost', 'other.example', 'coffee-test.onrender.com.evil.example',
                     'https://coffee-test.onrender.com', 'coffee-test.onrender.com/']:
            with self.subTest(host=host), self.assertRaises(ValueError):
                cloud_settings({**settings, 'RENDER_EXTERNAL_HOSTNAME': host})
        for field, value in [('PREVIEW_PASSWORD', 'short'), ('PREVIEW_PASSWORD', 'a'*32+'\n'),
                             ('PORT', '0'), ('PORT', 'not-a-port'), ('AMAP_JS_ALLOW_EVAL', '1'),
                             ('AMAP_JS_SECURITY_CODE', 'local-secret')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                cloud_settings({**settings, field: value})


class CloudPreviewTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict('os.environ', {'AMAP_API_KEY': 'test-private-web-key'}, clear=True)
        self.env.start()
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.folder.name) / 'cloud.sqlite3')
        self.main_store = Store(Path(self.folder.name) / 'main.sqlite3')
        self.main_owner, _ = self.main_store.session(None)
        self.main_store.preferences(self.main_owner, {'city': '深圳市', 'area': '南山区'})
        self.main_before = self.main_store.path.read_bytes()
        self.host = 'coffee-test.onrender.com'
        self.password = 'test-only-password-01234567890123456789'
        self.auth = 'Basic ' + base64.b64encode(('coffee:'+self.password).encode()).decode()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_cloud_handler(self.store, self.host, self.password))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.folder.cleanup()
        self.env.stop()

    def request(self, path, auth=None, method='GET', host=None, origin=None, cookie=None, data=None):
        con = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        headers = {'Host': host or self.host}
        if auth is not None:
            headers['Authorization'] = auth
        if origin:
            headers['Origin'] = origin
        if cookie:
            headers['Cookie'] = cookie
        if method == 'POST':
            headers.update({'X-Coffee-Client': 'web-v1', 'Content-Type': 'application/json'})
        con.request(method, path, json.dumps(data) if data is not None else None, headers)
        response = con.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        con.close()
        return result

    def test_health_check_is_public_without_session_or_data(self):
        status, headers, body = self.request('/healthz')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {'ok': True})
        self.assertNotIn('Set-Cookie', headers)
        self.assertEqual(headers['X-Robots-Tag'], 'noindex, nofollow, noarchive')
        with self.store.connect() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM users').fetchone()[0], 0)

    def test_all_other_routes_require_password_and_do_not_leak_secrets(self):
        for route in ['/', '/app.js', '/style.css', '/location.js', '/amap-location.js',
                      '/api/state', '/api/export', '/_AMapService/v4/ip', '/.env', '/healthz/']:
            with self.subTest(route=route):
                status, headers, body = self.request(route)
                self.assertEqual(status, 401)
                self.assertIn('Basic realm=', headers['WWW-Authenticate'])
                self.assertNotIn('Set-Cookie', headers)
                self.assertNotIn(self.password.encode(), body)
                self.assertNotIn(b'test-private-web-key', body)
        self.assertEqual(self.request('/api/preferences', method='POST', data={})[0], 401)
        self.assertEqual(self.request('/api/state', auth='Basic invalid')[0], 401)

    def test_valid_access_has_empty_isolated_data_secure_cookie_and_visible_notice(self):
        status, headers, body = self.request('/api/state', auth=self.auth)
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(data['records'], [])
        self.assertEqual(data['deployment']['notice'], NOTICE)
        self.assertTrue(data['deployment']['ephemeral'])
        self.assertEqual(data['map_location']['provider'], 'browser')
        self.assertNotIn(b'test-private-web-key', body)
        self.assertNotIn(b'unsafe-eval', headers['Content-Security-Policy'].encode())
        for flag in ['Secure', 'HttpOnly', 'SameSite=Strict']:
            self.assertIn(flag, headers['Set-Cookie'])
        cookie = headers['Set-Cookie'].split(';')[0]
        status, _, body = self.request('/api/preferences', auth=self.auth, method='POST',
            origin='https://'+self.host, cookie=cookie, data={'city': '测试城市'})
        self.assertEqual(status, 200)
        self.assertEqual(self.main_store.path.read_bytes(), self.main_before)
        page = self.request('/', auth=self.auth)[2].decode()
        self.assertIn('id="deployment-notice"', page)
        self.assertIn('id="storage-hint"', page)

    def test_host_and_https_same_origin_required_for_writes(self):
        self.assertEqual(self.request('/api/state', auth=self.auth, host='evil.example')[0], 403)
        for origin in [None, 'http://'+self.host, 'https://evil.example']:
            with self.subTest(origin=origin):
                self.assertEqual(self.request('/api/preferences', auth=self.auth, method='POST',
                    origin=origin, data={'city': '测试城市'})[0], 403)
        for route in ['/.env', '/data/web/coffee.sqlite3', '/cloud_preview.py']:
            self.assertEqual(self.request(route, auth=self.auth)[0], 404)

    def test_persistent_state_reports_verified_storage_and_private_backups_are_not_downloadable(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        backups = DailyBackups(self.store.path, Path(self.folder.name) / 'backups')
        backups.snapshot()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_cloud_handler(self.store, self.host, self.password, backups))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        status, headers, body = self.request('/api/state', auth=self.auth)
        deployment = json.loads(body)['deployment']
        self.assertEqual(status, 200)
        self.assertEqual(deployment['mode'], 'cloud-personal')
        self.assertFalse(deployment['ephemeral'])
        self.assertEqual(deployment['backup']['status'], 'ok')
        self.assertFalse(deployment['backup']['offsite'])
        self.assertNotIn(self.folder.name.encode(), body)
        self.assertIn('Secure', headers['Set-Cookie'])
        backups.failed = True
        self.assertEqual(json.loads(self.request('/api/state', auth=self.auth)[2])['deployment']['backup']['status'], 'error')
        for route in ['/cloud_storage.py', '/storage_backup.py', '/var/data/coffee-buddy/coffee.sqlite3', '/backups/coffee.sqlite3']:
            self.assertEqual(self.request(route, auth=self.auth)[0], 404)

    def test_remote_database_notice_does_not_claim_disk_or_daily_backups(self):
        # The HTTP deployment metadata must describe external storage accurately.
        self.store.storage_backend = 'postgres'
        status, _, body = self.request('/api/state', auth=self.auth)
        deployment = json.loads(body)['deployment']
        self.assertEqual(status, 200)
        self.assertFalse(deployment['ephemeral'])
        self.assertEqual(deployment['backend'], 'postgres')
        self.assertIn('独立数据库', deployment['notice'])
        self.assertNotIn('backup', deployment)
        self.assertNotIn('DATABASE_URL', body.decode())
        for route in ['/postgres_store.py', '/requirements-cloud.txt']:
            self.assertEqual(self.request(route, auth=self.auth)[0], 404)


if __name__ == '__main__':
    unittest.main()
