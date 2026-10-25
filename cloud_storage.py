"""Verified disk storage and consistent SQLite snapshots for the cloud app."""
from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import tempfile
import threading

from web_core import Store
from storage_backup import verify_database


DISK_MOUNT = Path('/var/data')
EPHEMERAL_ROOT = Path('/tmp/coffee-buddy-cloud-preview')


def open_cloud_store(env):
    mode = env.get('COFFEE_STORAGE_MODE', 'ephemeral')
    if mode not in ('ephemeral', 'persistent'):
        raise ValueError('云端存储模式无效')
    if mode == 'ephemeral':
        return Store(EPHEMERAL_ROOT / 'coffee.sqlite3'), None
    # Never silently create a normal directory and label it persistent.
    if DISK_MOUNT.is_symlink() or not os.path.ismount(DISK_MOUNT):
        raise ValueError('持久磁盘尚未挂载，已停止启动以免记录写入临时目录')
    root = DISK_MOUNT / 'coffee-buddy'
    if root.is_symlink():
        raise ValueError('持久存储目录不能是符号链接')
    root.mkdir(mode=0o700, exist_ok=True)
    os.chmod(root, 0o700)
    store = Store(root / 'coffee.sqlite3')
    os.chmod(store.path, 0o600)
    backups = DailyBackups(store.path, root / 'backups')
    # Unwritable/full/corrupt storage fails before serving requests.
    backups.snapshot()
    return store, backups


class DailyBackups:
    """One complete online database snapshot per UTC day, retaining 14 copies.

    Copies include browser identities and preferences, never SDK/API keys.
    They share the disk with the database: users still need off-disk exports.
    """
    def __init__(self, database, folder, keep=14):
        self.database = Path(database)
        self.folder = Path(folder)
        if self.folder.is_symlink():
            raise ValueError('备份目录不能是符号链接')
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.folder, 0o700)
        self.keep = keep
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.last_success = None
        self.failed = False

    def snapshot(self, now=None):
        now = now or datetime.now(timezone.utc)
        destination = self.folder / ('coffee-' + now.astimezone(timezone.utc).strftime('%Y-%m-%d') + '.sqlite3')
        with self.lock:
            if destination.exists():
                with closing(sqlite3.connect(destination.as_uri() + '?mode=ro', uri=True)) as check:
                    verify_database(check)
                self.last_success = datetime.fromtimestamp(destination.stat().st_mtime, timezone.utc).isoformat()
                self.failed = False
                return destination
            fd, temporary = tempfile.mkstemp(prefix='.snapshot-', dir=self.folder)
            os.close(fd)
            try:
                with closing(sqlite3.connect(self.database.as_uri() + '?mode=ro', uri=True)) as source, closing(sqlite3.connect(temporary)) as target:
                    source.backup(target)
                    verify_database(target)
                with open(temporary, 'rb') as file:
                    os.fsync(file.fileno())
                os.replace(temporary, destination)
                # Delete only this application's dated snapshots, after success.
                snapshots = sorted(self.folder.glob('coffee-????-??-??.sqlite3'))
                for old in snapshots[:-self.keep]:
                    old.unlink()
                self.last_success = now.isoformat()
                self.failed = False
                return destination
            finally:
                Path(temporary).unlink(missing_ok=True)

    def start(self):
        def run():
            while not self.stop_event.wait(3600):
                try:
                    self.snapshot()
                except Exception:
                    with self.lock:
                        self.failed = True
                    print('自动备份未完成，请检查云端存储并导出备份。', flush=True)
        self.thread = threading.Thread(target=run, name='coffee-daily-backup', daemon=True)
        self.thread.start()

    def status(self):
        with self.lock:
            return {'status': 'error' if self.failed else 'ok', 'last_success_at': self.last_success,
                    'retained_copies': self.keep, 'offsite': False}

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
