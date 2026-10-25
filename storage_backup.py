"""Offline SQLite recovery. Never overwrite an existing database.

Use on a stopped service: python storage_backup.py BACKUP NEW_DATABASE
"""
import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile


def verify_database(connection):
    if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
        raise ValueError('数据库完整性校验失败')
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'users', 'cafes', 'beans', 'entries'} <= tables:
        raise ValueError('不是 Coffee Buddy 数据库备份')


def restore_snapshot(source, destination):
    source, destination = Path(source).resolve(), Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('目标数据库已存在；请先停止服务，并将原库另存保留')
    # Read-only input: a typo must not create a new empty SQLite file.
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original:
        verify_database(original)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.restore-', dir=destination.parent)
        os.close(fd)
        try:
            with closing(sqlite3.connect(temporary)) as restored:
                original.backup(restored)
                verify_database(restored)
            with open(temporary, 'rb') as file:
                os.fsync(file.fileno())
            # Exclusive installation protects an original created concurrently.
            os.link(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='恢复完整数据库到一个不存在的新文件；保留浏览器身份和偏好')
    parser.add_argument('backup', type=Path)
    parser.add_argument('new_database', type=Path)
    args = parser.parse_args()
    restore_snapshot(args.backup, args.new_database)
    print('完整备份已校验并恢复到新文件；原库未覆盖。')
