"""Real account lifecycle, ownership, revocation and HTTP protections."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import http.client
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

from accounts import Accounts, SESSION_SECONDS, password_hash, token_hash
from cloud_preview import make_cloud_handler
from web_core import AppError, Store

SECRET = 'QaPass-2026-Abc!'
NEXT_SECRET = 'NextPass-2026-Xy!'


class AccountContract:
    def setUp(self):
        self.make_store()
        self.now = [1900000000]
        self.auth = Accounts(self.store, clock=lambda: self.now[0])
        self.owner, _ = self.store.session(None)
        self.other, _ = self.store.session(None)

    def register(self, name='tester'):
        return self.auth.register(self.owner, {'username': name, 'password': SECRET})

    def test_registration_claims_existing_owner_and_rotates_legacy_cookie(self):
        self.store.save(self.owner, {'product': '访客已保存记录'})
        self.store.preferences(self.owner, {'city': '虚构测试城市'})
        before = self.store.state(self.owner)
        result, owner, raw = self.register('TesTer')
        self.assertEqual(owner, self.owner)
        self.assertEqual(result['username'], 'TesTer')
        self.assertEqual(self.store.state(owner), before)
        self.assertNotEqual(raw, self.owner)
        self.assertEqual(self.auth.resolve(raw), (owner, raw, False))
        self.assertNotEqual(self.auth.resolve(self.owner)[0], owner)
        self.assertEqual(self.auth.public_state(owner), {'username': 'TesTer'})
        with closing(self.store.connect()) as con:
            password_stored, recovery_stored = con.execute('SELECT password_hash,recovery_hash FROM accounts WHERE owner=?', (owner,)).fetchone()
            tokens = con.execute('SELECT token_hash FROM account_sessions WHERE owner=?', (owner,)).fetchall()
        self.assertNotIn(SECRET, password_stored)
        self.assertNotIn(result['recovery_code'], recovery_stored)
        self.assertEqual(tokens, [(token_hash(raw),)])
        self.assertNotIn('account', self.store.state(owner))

    def test_another_browser_and_new_service_find_same_records_without_leaking_other_owner(self):
        self.register()
        row = self.store.save(self.owner, {'product': '跨设备测试记录'})
        reopened = Accounts(self.store, clock=lambda: self.now[0])
        _, owner, raw = reopened.login(self.other, {'username': 'tester', 'password': SECRET})
        self.assertEqual(owner, self.owner)
        self.assertEqual(reopened.resolve(raw)[0], self.owner)
        self.assertEqual(self.store.state(owner)['records'][0]['id'], row['id'])
        self.assertEqual(self.store.state(self.other)['records'], [])

    def test_username_case_is_preserved_distinct_and_required_for_login_and_recovery(self):
        upper, _, _ = self.register('CoffeeFan')
        lower, _, _ = self.auth.register(self.other, {'username': 'coffeefan', 'password': NEXT_SECRET})
        for name, secret, owner in [('CoffeeFan', SECRET, self.owner), ('coffeefan', NEXT_SECRET, self.other)]:
            self.assertEqual(self.auth.login(self.store.session(None)[0], {'username': name, 'password': secret})[1], owner)
        with self.assertRaises(AppError):
            self.auth.login(self.other, {'username': 'coffeefan', 'password': SECRET})
        with self.assertRaises(AppError):
            self.auth.recover({'username': 'coffeefan', 'recovery_code': upper['recovery_code'], 'password': SECRET})
        self.assertEqual(self.auth.public_state(self.owner), {'username': 'CoffeeFan'})
        self.assertEqual(self.auth.public_state(self.other), {'username': 'coffeefan'})

    def test_new_and_reset_password_boundaries_are_eight_through_twenty(self):
        for secret in ['1'*7, '1'*21]:
            with self.assertRaises(AppError):
                self.auth.register(self.owner, {'username': 'boundary', 'password': secret})
        result, _, _ = self.auth.register(self.owner, {'username': 'boundary', 'password': 'aB12!xyz'})
        self.assertEqual(self.auth.login(self.other, {'username': 'boundary', 'password': 'aB12!xyz'})[1], self.owner)
        for secret in ['1'*7, '1'*21]:
            with self.assertRaises(AppError):
                self.auth.recover({'username': 'boundary', 'recovery_code': result['recovery_code'], 'password': secret})
        self.auth.recover({'username': 'boundary', 'recovery_code': result['recovery_code'], 'password': 'aB12!xyz'*2+'abcd'})
        self.assertEqual(self.auth.login(self.other, {'username': 'boundary', 'password': 'aB12!xyz'*2+'abcd'})[1], self.owner)

    def test_preexisting_lowercase_account_and_long_password_still_work(self):
        legacy = 'Former-test-password-more-than-20!'
        with closing(self.store.connect()) as con, con:
            con.execute('INSERT INTO accounts VALUES (?,?,?,?,?)',
                        (self.owner, 'legacy_user', password_hash(legacy), 'old-recovery-placeholder', int(self.now[0])))
        row = self.store.save(self.owner, {'product': '升级前已有记录'})
        self.assertEqual(self.auth.login(self.other, {'username': 'legacy_user', 'password': legacy})[1], self.owner)
        code, _, _ = self.auth.rotate_recovery(self.owner, {'password': legacy})
        self.auth.recover({'username': 'legacy_user', 'recovery_code': code['recovery_code'], 'password': SECRET})
        self.assertEqual(self.auth.login(self.other, {'username': 'legacy_user', 'password': SECRET})[1], self.owner)
        self.assertEqual(self.store.state(self.owner)['records'][0]['id'], row['id'])

    def test_wrong_password_is_generic_and_limit_survives_new_service(self):
        self.register()
        for _ in range(8):
            with self.assertRaises(AppError) as e:
                self.auth.login(self.other, {'username': 'tester', 'password': 'wrong'})
            self.assertEqual((e.exception.status, str(e.exception)), (401, '用户名或密码不正确'))
        with self.assertRaises(AppError) as e:
            Accounts(self.store, clock=lambda: self.now[0]).login(self.other, {'username': 'tester', 'password': SECRET})
        self.assertEqual(e.exception.status, 429)
        self.now[0] += 901
        self.assertEqual(self.auth.login(self.other, {'username': 'tester', 'password': SECRET})[1], self.owner)
        with self.assertRaisesRegex(AppError, '用户名或密码不正确'):
            self.auth.login(self.other, {'username': 'missing', 'password': SECRET})

    def test_recovery_is_single_use_revokes_every_session_and_requires_fresh_login(self):
        result, _, first = self.register()
        _, _, second = self.auth.login(self.other, {'username': 'tester', 'password': SECRET})
        row = self.store.save(self.owner, {'product': '恢复后保留的记录'})
        code = result['recovery_code']
        reset = self.auth.recover({'username': 'tester', 'recovery_code': code.lower(), 'password': NEXT_SECRET})
        self.assertTrue(reset['login_required'])
        self.assertNotIn('token', reset)
        self.assertNotEqual(reset['recovery_code'], code)
        for token in [first, second]:
            self.assertNotEqual(self.auth.resolve(token)[0], self.owner)
        with self.assertRaises(AppError):
            self.auth.login(self.other, {'username': 'tester', 'password': SECRET})
        with self.assertRaises(AppError):
            self.auth.recover({'username': 'tester', 'recovery_code': code, 'password': SECRET})
        self.assertEqual(self.auth.login(self.other, {'username': 'tester', 'password': NEXT_SECRET})[1], self.owner)
        self.assertEqual(self.store.state(self.owner)['records'][0]['id'], row['id'])

    def test_logout_and_expiry_invalidate_cookie_without_deleting_records(self):
        _, _, first = self.register()
        _, _, second = self.auth.login(self.other, {'username': 'tester', 'password': SECRET})
        row = self.store.save(self.owner, {'product': '退出后保留'})
        self.auth.logout(first)
        self.assertNotEqual(self.auth.resolve(first)[0], self.owner)
        self.assertEqual(self.auth.resolve(second)[0], self.owner)
        self.now[0] += SESSION_SECONDS + 1
        self.assertNotEqual(self.auth.resolve(second)[0], self.owner)
        self.assertEqual(self.store.state(self.owner)['records'][0]['id'], row['id'])

    def test_switch_requires_confirmation_and_does_not_merge_or_delete_guest_records(self):
        self.register()
        self.store.save(self.other, {'product': '另一位访客记录'})
        before = self.store.state(self.other)
        with self.assertRaises(AppError) as e:
            self.auth.login(self.other, {'username': 'tester', 'password': SECRET})
        self.assertEqual(e.exception.status, 409)
        self.assertEqual(self.auth.login(self.other, {'username': 'tester', 'password': SECRET, 'switch_confirmed': True})[1], self.owner)
        self.assertEqual(self.store.state(self.other), before)
        self.assertEqual(self.store.state(self.owner)['records'], [])

    def test_concurrent_username_claim_has_one_winner_and_no_orphan_login(self):
        def claim(owner):
            try:
                return self.auth.register(owner, {'username': 'same_name', 'password': SECRET})[1]
            except AppError as e:
                return e.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, [self.owner, self.other]))
        self.assertEqual(results.count(409), 1)
        winner = next(x for x in results if x != 409)
        self.assertEqual(self.auth.login(self.store.session(None)[0], {'username': 'same_name', 'password': SECRET})[1], winner)

    def test_password_reset_racing_login_cannot_issue_old_password_session(self):
        self.register()
        def change_during_hash(*args):
            with closing(self.store.connect()) as con, con:
                con.execute('UPDATE accounts SET password_hash=? WHERE owner=?', (password_hash(NEXT_SECRET), self.owner))
            return True
        with patch('accounts.password_matches', side_effect=change_during_hash), self.assertRaises(AppError):
            self.auth.login(self.other, {'username': 'tester', 'password': SECRET})

    def test_regenerate_recovery_requires_password_and_revokes_old_code_and_sessions(self):
        result, _, old = self.register()
        with self.assertRaises(AppError):
            self.auth.rotate_recovery(self.owner, {'password': 'wrong'})
        with self.assertRaises(AppError):
            self.auth.rotate_recovery(self.other, {'password': SECRET})
        new, owner, raw = self.auth.rotate_recovery(self.owner, {'password': SECRET})
        self.assertEqual(owner, self.owner)
        self.assertEqual(self.auth.resolve(raw)[0], owner)
        self.assertNotEqual(self.auth.resolve(old)[0], owner)
        with self.assertRaises(AppError):
            self.auth.recover({'username': 'tester', 'recovery_code': result['recovery_code'], 'password': NEXT_SECRET})
        self.assertTrue(self.auth.recover({'username': 'tester', 'recovery_code': new['recovery_code'], 'password': NEXT_SECRET})['login_required'])


class SQLiteAccountTests(AccountContract, unittest.TestCase):
    def make_store(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.folder.name) / 'account.sqlite3')

    def tearDown(self):
        self.folder.cleanup()

    def test_session_insert_failure_rolls_back_claim_and_keeps_guest_identity(self):
        with closing(self.store.connect()) as con:
            con.executescript("CREATE TRIGGER qa_fail_session BEFORE INSERT ON account_sessions BEGIN SELECT RAISE(ABORT,'test fault'); END;")
        with self.assertRaises(Exception):
            self.register()
        self.assertEqual(self.auth.public_state(self.owner), {'username': None})
        self.assertEqual(self.auth.resolve(self.owner)[0], self.owner)


@unittest.skipUnless(os.environ.get('COFFEE_TEST_POSTGRES_DSN'), 'isolated PostgreSQL required')
class PostgresAccountTests(AccountContract, unittest.TestCase):
    def make_store(self):
        import psycopg
        from postgres_store import PostgresStore
        self.schema = 'qa_account_' + uuid.uuid4().hex
        self.dsn = os.environ['COFFEE_TEST_POSTGRES_DSN']
        with psycopg.connect(self.dsn, autocommit=True) as con:
            con.execute('CREATE SCHEMA ' + self.schema)
        def connector(ignored, **options):
            return psycopg.connect(self.dsn, autocommit=True, options='-c search_path=' + self.schema)
        self.store = PostgresStore('postgresql://test:fictional@ep-example.neon.tech/test', connector=connector)

    def tearDown(self):
        import psycopg
        with psycopg.connect(self.dsn, autocommit=True) as con:
            con.execute('DROP SCHEMA ' + self.schema + ' CASCADE')

    def test_session_insert_failure_rolls_back_claim(self):
        with closing(self.store.connect()) as con, con:
            con.execute('ALTER TABLE account_sessions ADD CONSTRAINT qa_fault CHECK (length(token_hash)>100)')
        with self.assertRaises(AppError):
            self.register()
        self.assertEqual(self.auth.public_state(self.owner), {'username': None})
        self.assertEqual(self.auth.resolve(self.owner)[0], self.owner)


class AccountHttpTests(unittest.TestCase):
    def setUp(self):
        import base64
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.folder.name) / 'http.sqlite3')
        self.host = 'coffee-test.onrender.com'
        self.access = 'Basic ' + base64.b64encode(b'coffee:test-only-password-01234567890123456789').decode()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_cloud_handler(self.store, self.host, 'test-only-password-01234567890123456789'))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True);self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.folder.cleanup()

    def call(self, path, cookie=None, data=None, origin=None):
        headers = {'Host': self.host, 'Authorization': self.access}
        if cookie: headers['Cookie'] = cookie
        if data is not None: headers.update({'Content-Type':'application/json','X-Coffee-Client':'web-v1','Origin':origin or 'https://'+self.host})
        con = http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        con.request('GET' if data is None else 'POST',path,None if data is None else json.dumps(data),headers)
        r=con.getresponse();body=r.read();result=r.status,dict(r.getheaders()),json.loads(body) if 'application/json' in r.getheader('Content-Type','') else body
        con.close();return result

    @staticmethod
    def cookie(headers):
        return headers['Set-Cookie'].split(';')[0]

    def test_http_claim_login_logout_cookie_rotation_export_and_isolation(self):
        _, h, _ = self.call('/api/state');guest=self.cookie(h)
        self.assertEqual(self.call('/api/records',guest,{'product':'HTTP 访客记录'})[0],200)
        status,h,result=self.call('/api/account/register',guest,{'username':'http_test','password':SECRET})
        self.assertEqual(status,200);account=self.cookie(h)
        self.assertNotEqual(account,guest)
        self.assertTrue(all(x in h['Set-Cookie'] for x in ['Secure','HttpOnly','SameSite=Strict']))
        self.assertEqual(self.call('/api/state',account)[2]['account'],{'username':'http_test'})
        self.assertEqual(len(self.call('/api/state',guest)[2]['records']),0)
        exported=self.call('/api/export',account)[2]
        self.assertNotIn('account',exported);self.assertNotIn('password_hash',json.dumps(exported))
        _,_,other=self.call('/api/account/login',data={'username':'http_test','password':'bad'})
        self.assertEqual(other['error'],'用户名或密码不正确')
        status,h,_=self.call('/api/account/login',data={'username':'http_test','password':SECRET})
        second=self.cookie(h);self.assertEqual(status,200)
        self.assertEqual(self.call('/api/state',second)[2]['records'],exported['records'])
        _,h,_=self.call('/api/account/logout',account,{})
        self.assertEqual(self.call('/api/state',self.cookie(h))[2]['records'],[])
        self.assertEqual(self.call('/api/state',account)[2]['records'],[])
        self.assertEqual(len(self.call('/api/state',second)[2]['records']),1)
        self.assertEqual(self.call('/accounts.js')[0],200)
        self.assertEqual(self.call('/accounts.py')[0],404)
        self.assertNotIn('WWW-Authenticate',self.call('/api/account/login',data={'username':'http_test','password':'bad'})[1])

    def test_cross_origin_register_rejected_and_expired_account_write_never_becomes_guest_write(self):
        _,h,_=self.call('/api/state');guest=self.cookie(h)
        self.assertEqual(self.call('/api/account/register',guest,{'username':'http_test','password':SECRET},origin='https://evil.example')[0],403)
        _,h,_=self.call('/api/account/register',guest,{'username':'http_test','password':SECRET});cookie=self.cookie(h)
        with closing(self.store.connect()) as con, con:con.execute('UPDATE account_sessions SET expires_at=0')
        status,h,result=self.call('/api/records',cookie,{'product':'不应误存为访客'})
        self.assertEqual(status,401);self.assertNotIn('Set-Cookie',h);self.assertIn('尚未保存',result['error'])
        self.assertNotIn('WWW-Authenticate',h)
        with closing(self.store.connect()) as con:self.assertEqual(con.execute('SELECT COUNT(*) FROM entries').fetchone()[0],0)


if __name__ == '__main__':unittest.main()
