"""Remote PostgreSQL storage; local SQLite remains the default for local use.

Only the application's fixed SQL is adapted, never user-supplied statements.
All mutations take a transaction-scoped advisory lock. This preserves the
SQLite writer serialization relied on by bulk draft conflict detection.
"""
from contextlib import closing
import os
import socket
from urllib.parse import parse_qsl, urlsplit

from web_core import AppError, Store


UNAVAILABLE = '云端数据库暂时不可用，尚未确认保存。请保留当前页面，稍后重试。'
WRITE_LOCK = 74857109261


def connection_error_code(error):
    """Fixed diagnostic labels only: never expose a provider message or DSN."""
    message = str(error).lower()
    if ('permission denied' in message and 'certificate file' in message
            or 'could not get home directory' in message):
        return 'DB_CLIENT_CERT_PATH'
    if any(value in message for value in ('certificate verify', 'root certificate', 'unable to get local issuer')):
        return 'DB_TLS_CERTIFICATE'
    if 'channel binding' in message:
        return 'DB_TLS_CHANNEL_BINDING'
    if getattr(error, 'sqlstate', None) in ('28P01', '28000') or 'password authentication failed' in message:
        return 'DB_AUTH'
    if any(value in message for value in ('could not translate host', 'name or service not known', 'could not resolve')):
        return 'DB_DNS'
    if any(value in message for value in ('unsupported startup parameter', 'unrecognized configuration parameter')):
        return 'DB_OPTIONS'
    if any(value in message for value in ('too many connections', 'quota exceeded', 'compute time quota')):
        return 'DB_LIMIT'
    if 'timeout' in message or 'timed out' in message:
        return 'DB_CONNECT_TIMEOUT'
    if 'network is unreachable' in message:
        return 'DB_NETWORK_UNREACHABLE'
    if 'connection refused' in message:
        return 'DB_CONNECTION_REFUSED'
    if 'server closed the connection' in message:
        return 'DB_SERVER_CLOSED'
    return 'DB_CONNECT'


def validate_database_url(value):
    try:
        url = urlsplit(value)
        query = parse_qsl(url.query, strict_parsing=True)
        if (url.scheme not in ('postgres', 'postgresql') or not url.hostname
                or not url.hostname.endswith('.neon.tech') or not url.username or not url.password
                or url.port not in (None, 5432) or not url.path.strip('/') or url.fragment
                or len({k for k, _ in query}) != len(query)
                or any(k not in ('sslmode', 'channel_binding') for k, _ in query)):
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError('请配置 Neon 提供的有效数据库连接地址，不要填写网页地址或 API Key') from None
    return value


def render_ipv4_address(database_url):
    """Resolve at connection time; retain the original hostname for TLS/SNI."""
    if not os.getenv('RENDER_EXTERNAL_HOSTNAME'):
        return None
    try:
        addresses = socket.getaddrinfo(urlsplit(database_url).hostname, 5432,
                                       socket.AF_INET, socket.SOCK_STREAM)
        return addresses[0][4][0]
    except (OSError, IndexError):
        print('云端数据库连接失败，诊断代码：DB_IPV4_UNAVAILABLE', flush=True)
        raise AppError(UNAVAILABLE, 503) from None


class PostgresConnection:
    def __init__(self, connection, error_type):
        self.connection = connection
        self.error_type = error_type
        self.transaction = None

    def execute(self, statement, params=()):
        if statement == 'BEGIN IMMEDIATE':
            if self.transaction is None:
                raise RuntimeError('批量写入必须在事务内')
            return None  # __enter__ already began and locked this transaction.
        try:
            return self.connection.execute(statement.replace('?', '%s'), params)
        except self.error_type:
            raise AppError(UNAVAILABLE, 503) from None

    def executescript(self, script):
        # Store's schema consists solely of fixed CREATE TABLE statements.
        with self:
            for statement in script.split(';'):
                if statement.strip():
                    self.execute(statement)

    def __enter__(self):
        if self.transaction is not None:
            raise RuntimeError('不支持嵌套存储事务')
        manager = self.connection.transaction()
        try:
            manager.__enter__()
            self.connection.execute('SELECT pg_advisory_xact_lock(%s)', (WRITE_LOCK,))
        except self.error_type:
            # Closing a connection aborts any uncommitted transaction, including
            # one whose lock acquisition failed. Never retry an unknown write.
            self.connection.close()
            raise AppError(UNAVAILABLE, 503) from None
        self.transaction = manager
        return self

    def __exit__(self, exc_type, exc, traceback):
        manager, self.transaction = self.transaction, None
        try:
            return manager.__exit__(exc_type, exc, traceback)
        except self.error_type:
            raise AppError(UNAVAILABLE, 503) from None

    def close(self):
        self.connection.close()


class PostgresStore(Store):
    storage_backend = 'postgres'

    def __init__(self, database_url, *, connector=None):
        self._database_url = validate_database_url(database_url)
        try:
            import psycopg
            import certifi
        except ImportError:
            raise ValueError('云端数据库驱动或证书包未安装，已停止启动；不会改用临时数据库') from None
        self._connector = connector or psycopg.connect
        self._error_type = psycopg.Error
        self._root_cert = certifi.where()
        # Reuse the same schema and all domain validation/save/import behavior;
        # initializing through the remote connector does not create a local DB.
        with closing(self.connect()) as con:
            con.executescript('''
                CREATE TABLE IF NOT EXISTS users (token TEXT PRIMARY KEY, prefs TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS cafes (owner TEXT, id TEXT, data TEXT NOT NULL, PRIMARY KEY(owner,id));
                CREATE TABLE IF NOT EXISTS beans (owner TEXT, id TEXT, data TEXT NOT NULL, PRIMARY KEY(owner,id));
                CREATE TABLE IF NOT EXISTS entries (owner TEXT, id TEXT, cafe_id TEXT, bean_id TEXT, data TEXT NOT NULL, PRIMARY KEY(owner,id));
            ''')

    def connect(self):
        address = render_ipv4_address(self._database_url)
        routing = {'hostaddr': address} if address else {}
        try:
            connection = self._connector(self._database_url, autocommit=True,
                sslmode='verify-full', sslrootcert=self._root_cert, channel_binding='require',
                # Neon uses SCRAM, not client certificates. Avoid probing the
                # container's root home after privileges have been dropped;
                # server certificate and hostname verification stay required.
                sslcertmode='disable',
                connect_timeout=10, application_name='coffee-buddy',
                options='-c statement_timeout=15000 -c lock_timeout=10000 -c idle_in_transaction_session_timeout=20000',
                **routing)
        except self._error_type as error:
            print('云端数据库连接失败，诊断代码：' + connection_error_code(error), flush=True)
            raise AppError(UNAVAILABLE, 503) from None
        return PostgresConnection(connection, self._error_type)
