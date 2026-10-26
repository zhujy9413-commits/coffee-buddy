"""Personal accounts over the existing owner-scoped store; no email provider.

Passwords use salted scrypt; only hashes of login tokens and recovery codes are
stored. Registration claims the current guest owner without copying records.
"""
from contextlib import closing, contextmanager
import hashlib
import hmac
import re
import secrets
import threading
import time

from web_core import AppError

AUTH_SCHEMA = '''
CREATE TABLE IF NOT EXISTS accounts (
 owner TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE,
 password_hash TEXT NOT NULL, recovery_hash TEXT NOT NULL, created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS account_sessions (
 token_hash TEXT PRIMARY KEY, owner TEXT NOT NULL, expires_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS account_attempts (
 attempt_key TEXT PRIMARY KEY, attempts INTEGER NOT NULL, window_start BIGINT NOT NULL
);
'''
SESSION_SECONDS = 30 * 24 * 60 * 60
WINDOW_SECONDS = 15 * 60
HASH_SLOTS = threading.BoundedSemaphore(2)
LOGIN_ERROR = '用户名或密码不正确'
RECOVERY_ERROR = '用户名或恢复码不正确'


def username(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_]{3,32}', value):
        raise AppError('用户名需为 3—32 位字母、数字或下划线')
    return value


def password(value):
    if not isinstance(value, str) or not 8 <= len(value) <= 20:
        raise AppError('密码需为 8—20 个字符，可以使用空格和中文')
    return value


@contextmanager
def hash_slot():
    if not HASH_SLOTS.acquire(blocking=False):
        raise AppError('当前登录请求较多，请稍后重试', 429)
    try:
        yield
    finally:
        HASH_SLOTS.release()


def password_hash(value, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(value.encode('utf8'), salt=salt, n=32768, r=8, p=3,
                            maxmem=64 * 1024 * 1024, dklen=32)
    return 'scrypt$32768$8$3$' + salt.hex() + '$' + digest.hex()


def password_matches(value, stored):
    # Fixed bounded parameters even if a stored hash is malformed.
    # Existing passwords from the former 15–128 policy remain valid at login.
    if not isinstance(value, str) or len(value) > 128:
        return False
    try:
        algorithm, n, r, p, salt, digest = stored.split('$')
        if (algorithm, n, r, p) != ('scrypt', '32768', '8', '3'):
            return False
        if len(salt) != 32 or len(digest) != 64:
            return False
        return hmac.compare_digest(password_hash(value, bytes.fromhex(salt)), stored)
    except (ValueError, TypeError):
        return False


def token_hash(value):
    return hashlib.sha256(value.encode('ascii')).hexdigest()


def new_recovery():
    raw = secrets.token_hex(24).upper()
    return '-'.join(raw[i:i+8] for i in range(0, len(raw), 8))


def recovery_hash(value):
    normalized = re.sub(r'[-\s]', '', value.upper()) if isinstance(value, str) and len(value) <= 100 else ''
    if not re.fullmatch(r'[A-F0-9]{48}', normalized):
        return ''
    return hashlib.sha256(('coffee-recovery-v1:' + normalized).encode('ascii')).hexdigest()


class Accounts:
    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock
        with closing(store.connect()) as con:
            con.executescript(AUTH_SCHEMA)

    def resolve(self, supplied):
        """Return owner, opaque cookie, changed. Claimed legacy tokens stop working."""
        if isinstance(supplied, str) and re.fullmatch(r'(?:a_)?[a-f0-9]{64}', supplied):
            with closing(self.store.connect()) as con:
                row = con.execute('SELECT owner FROM account_sessions WHERE token_hash=? AND expires_at>?',
                                  (token_hash(supplied), int(self.clock()))).fetchone()
                if row:
                    return row[0], supplied, False
                row = con.execute('SELECT token FROM users WHERE token=? AND NOT EXISTS '
                                  '(SELECT 1 FROM accounts WHERE owner=users.token)', (supplied,)).fetchone()
                if row:
                    return row[0], supplied, False
        owner, _ = self.store.session(None)
        return owner, owner, True

    def public_state(self, owner):
        with closing(self.store.connect()) as con:
            row = con.execute('SELECT username FROM accounts WHERE owner=?', (owner,)).fetchone()
        return {'username': row[0] if row else None}

    def _attempt(self, action, name):
        # Both limits survive service restarts; new guest cookies cannot bypass
        # an account's limit. Global limits bound work across invented names.
        now = int(self.clock())
        keys = [(token_hash(action + ':user:' + name), 8),
                (token_hash(action + ':global'), 80)]
        with closing(self.store.connect()) as con, con:
            con.execute('BEGIN IMMEDIATE')
            con.execute('DELETE FROM account_attempts WHERE window_start<=?', (now - WINDOW_SECONDS,))
            for key, maximum in keys:
                row = con.execute('SELECT attempts FROM account_attempts WHERE attempt_key=?', (key,)).fetchone()
                if row and row[0] >= maximum:
                    raise AppError('尝试次数较多，请 15 分钟后重试', 429)
            for key, _ in keys:
                con.execute('INSERT INTO account_attempts VALUES (?,?,?) ON CONFLICT(attempt_key) '
                            'DO UPDATE SET attempts=account_attempts.attempts+1', (key, 1, now))

    def _new_session(self, con, owner):
        raw = 'a_' + secrets.token_hex(32)
        now = int(self.clock())
        con.execute('DELETE FROM account_sessions WHERE expires_at<=?', (now,))
        con.execute('INSERT INTO account_sessions VALUES (?,?,?)', (token_hash(raw), owner, now + SESSION_SECONDS))
        return raw

    @staticmethod
    def _check_switch(con, current, target, data):
        if current != target:
            row = con.execute('SELECT 1 FROM entries WHERE owner=? LIMIT 1', (current,)).fetchone()
            if row and data.get('switch_confirmed') is not True:
                raise AppError('切换账号前，请先导出当前记录并勾选确认。登录后可导入合并。', 409)

    def register(self, owner, data):
        name, secret = username(data.get('username')), password(data.get('password'))
        self._attempt('register', name)
        with hash_slot():
            stored = password_hash(secret)
        code = new_recovery()
        with closing(self.store.connect()) as con, con:
            con.execute('BEGIN IMMEDIATE')
            if con.execute('SELECT 1 FROM accounts WHERE owner=? OR username=?', (owner, name)).fetchone():
                raise AppError('无法创建该账号，请换一个用户名或登录已有账号', 409)
            con.execute('INSERT INTO accounts VALUES (?,?,?,?,?)',
                        (owner, name, stored, recovery_hash(code), int(self.clock())))
            raw = self._new_session(con, owner)
        return {'username': name, 'recovery_code': code}, owner, raw

    def login(self, current, data, supplied=None):
        try:
            name = username(data.get('username'))
        except AppError:
            raise AppError(LOGIN_ERROR, 401) from None
        self._attempt('login', name)
        with closing(self.store.connect()) as con:
            row = con.execute('SELECT owner,password_hash FROM accounts WHERE username=?', (name,)).fetchone()
        with hash_slot():
            # Unknown usernames still perform the same expensive hash operation.
            stored = row[1] if row else 'scrypt$32768$8$3$' + '00'*16 + '$' + '00'*32
            valid = password_matches(data.get('password'), stored)
        if not row or not valid:
            raise AppError(LOGIN_ERROR, 401)
        with closing(self.store.connect()) as con, con:
            con.execute('BEGIN IMMEDIATE')
            # Recheck after hashing: recovery may have revoked this password.
            fresh = con.execute('SELECT password_hash FROM accounts WHERE owner=?', (row[0],)).fetchone()
            if not fresh or not hmac.compare_digest(fresh[0], row[1]):
                raise AppError(LOGIN_ERROR, 401)
            self._check_switch(con, current, row[0], data)
            if isinstance(supplied, str) and re.fullmatch(r'a_[a-f0-9]{64}', supplied):
                con.execute('DELETE FROM account_sessions WHERE token_hash=?', (token_hash(supplied),))
            raw = self._new_session(con, row[0])
        return {'username': name}, row[0], raw

    def logout(self, supplied):
        if isinstance(supplied, str) and re.fullmatch(r'a_[a-f0-9]{64}', supplied):
            with closing(self.store.connect()) as con, con:
                con.execute('DELETE FROM account_sessions WHERE token_hash=?', (token_hash(supplied),))
        owner, _ = self.store.session(None)
        return {'ok': True}, owner, owner

    def rotate_recovery(self, owner, data):
        name = self.public_state(owner)['username']
        if not name:
            raise AppError('请先登录个人账号', 401)
        self._attempt('recovery-code', name)
        with closing(self.store.connect()) as con:
            stored = con.execute('SELECT password_hash FROM accounts WHERE owner=?', (owner,)).fetchone()[0]
        with hash_slot():
            valid = password_matches(data.get('password'), stored)
        if not valid:
            raise AppError(LOGIN_ERROR, 401)
        code = new_recovery()
        with closing(self.store.connect()) as con, con:
            con.execute('BEGIN IMMEDIATE')
            fresh = con.execute('SELECT password_hash FROM accounts WHERE owner=?', (owner,)).fetchone()
            if not fresh or not hmac.compare_digest(fresh[0], stored):
                raise AppError(LOGIN_ERROR, 401)
            con.execute('UPDATE accounts SET recovery_hash=? WHERE owner=?', (recovery_hash(code), owner))
            con.execute('DELETE FROM account_sessions WHERE owner=?', (owner,))
            raw = self._new_session(con, owner)
        return {'username': name, 'recovery_code': code}, owner, raw

    def recover(self, data):
        try:
            name = username(data.get('username'))
        except AppError:
            raise AppError(RECOVERY_ERROR, 401) from None
        secret = password(data.get('password'))
        self._attempt('recover', name)
        candidate = recovery_hash(data.get('recovery_code'))
        with closing(self.store.connect()) as con:
            row = con.execute('SELECT owner,recovery_hash FROM accounts WHERE username=?', (name,)).fetchone()
        if not candidate or not hmac.compare_digest(candidate, row[1] if row else '0'*64) or not row:
            raise AppError(RECOVERY_ERROR, 401)
        with hash_slot():
            stored = password_hash(secret)
        code = new_recovery()
        with closing(self.store.connect()) as con, con:
            con.execute('BEGIN IMMEDIATE')
            fresh = con.execute('SELECT recovery_hash FROM accounts WHERE owner=?', (row[0],)).fetchone()
            if not fresh or not hmac.compare_digest(candidate, fresh[0]):
                raise AppError(RECOVERY_ERROR, 401)
            con.execute('UPDATE accounts SET password_hash=?,recovery_hash=? WHERE owner=?',
                        (stored, recovery_hash(code), row[0]))
            con.execute('DELETE FROM account_sessions WHERE owner=?', (row[0],))
        # A reset never silently signs into an account or moves guest records.
        return {'username': name, 'recovery_code': code, 'login_required': True}
