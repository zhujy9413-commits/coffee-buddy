"""Remote PostgreSQL storage; local SQLite remains the default for local use.

Only the application's fixed SQL is adapted, never user-supplied statements.
All mutations take a transaction-scoped advisory lock. This preserves the
SQLite writer serialization relied on by bulk draft conflict detection.
"""
from contextlib import closing
from urllib.parse import parse_qsl, urlsplit

from web_core import AppError, Store


UNAVAILABLE = '云端数据库暂时不可用，尚未确认保存。请保留当前页面，稍后重试。'
WRITE_LOCK = 74857109261


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
        except ImportError:
            raise ValueError('云端数据库驱动未安装，已停止启动；不会改用临时数据库') from None
        self._connector = connector or psycopg.connect
        self._error_type = psycopg.Error
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
        try:
            connection = self._connector(self._database_url, autocommit=True,
                sslmode='verify-full', sslrootcert='system', channel_binding='require',
                connect_timeout=10, application_name='coffee-buddy',
                options='-c statement_timeout=15000 -c lock_timeout=10000 -c idle_in_transaction_session_timeout=20000')
        except self._error_type:
            raise AppError(UNAVAILABLE, 503) from None
        return PostgresConnection(connection, self._error_type)
