from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cloud_storage import DailyBackups, open_cloud_store
from storage_backup import restore_snapshot
from web_core import AppError, Store, DEFAULT_PREFS
from docker_entrypoint import prepare_runtime


class CloudStorageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.store = Store(self.root / 'active.sqlite3')
        self.owner, _ = self.store.session(None)
        self.other, _ = self.store.session(None)

    def tearDown(self):
        self.folder.cleanup()

    def test_persistent_mode_refuses_missing_mount_and_never_falls_back(self):
        for mode in ['invalid', '', 'Persistent']:
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                open_cloud_store({'COFFEE_STORAGE_MODE': mode})
        with patch('cloud_storage.DISK_MOUNT', self.root), patch('cloud_storage.os.path.ismount', return_value=False):
            with self.assertRaisesRegex(ValueError, '未挂载'):
                open_cloud_store({'COFFEE_STORAGE_MODE': 'persistent'})
        self.assertFalse((self.root / 'coffee-buddy').exists())

    def test_default_stays_disposable_and_isolated(self):
        with patch('cloud_storage.EPHEMERAL_ROOT', self.root / 'preview'):
            disposable, manager = open_cloud_store({})
        self.assertIsNone(manager)
        self.assertNotEqual(disposable.path, self.store.path)

    def test_mounted_database_survives_new_process_with_identity_and_preferences(self):
        with patch('cloud_storage.DISK_MOUNT', self.root), patch('cloud_storage.os.path.ismount', return_value=True):
            store, backups = open_cloud_store({'COFFEE_STORAGE_MODE': 'persistent'})
        owner, _ = store.session(None)
        store.preferences(owner, dict(DEFAULT_PREFS, coffee_preference='milk', brews=['拿铁']))
        entry = store.save(owner, {'product': '重启后应保留的测试记录', 'brew': '拿铁'})
        code = 'import json,sys;from web_core import Store;s=Store(sys.argv[1]);print(json.dumps([s.session(sys.argv[2])[1],s.state(sys.argv[2])]))'
        result = subprocess.run([sys.executable, '-c', code, str(store.path), owner], cwd=Path(__file__).parent,
                                capture_output=True, text=True, check=True)
        new_session, state = json.loads(result.stdout)
        self.assertFalse(new_session)
        self.assertEqual(state['records'][0]['id'], entry['id'])
        self.assertEqual(state['preferences']['brews'], ['拿铁'])
        self.assertEqual(store.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(backups.folder.stat().st_mode & 0o777, 0o700)

    def test_snapshot_restore_recovers_all_users_and_preserves_isolation(self):
        self.store.preferences(self.owner, dict(DEFAULT_PREFS, brews=['我的奶咖'],
            brew_categories={'我的奶咖': 'milk'}, coffee_preference='milk'))
        self.store.save(self.owner, {'product': '备份前记录'})
        self.store.save(self.other, {'product': '其他人的记录'})
        before = [self.store.state(owner) for owner in (self.owner, self.other)]
        manager = DailyBackups(self.store.path, self.root / 'snapshots')
        snapshot = manager.snapshot()
        self.assertEqual(snapshot.stat().st_mode & 0o777, 0o600)
        self.store.save(self.owner, {'product': '备份后记录'})
        destination = restore_snapshot(snapshot, self.root / 'recovered.sqlite3')
        recovered = Store(destination)
        self.assertEqual([recovered.state(owner) for owner in (self.owner, self.other)], before)
        self.assertEqual(recovered.session(self.owner), (self.owner, False))
        self.assertEqual(len(self.store.state(self.owner)['records']), 2)
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)

    def test_backup_retention_daily_idempotence_and_unrelated_files(self):
        manager = DailyBackups(self.store.path, self.root / 'snapshots')
        other = manager.folder / 'keep-me.sqlite3'
        other.write_text('unrelated')
        day = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(16):
            manager.snapshot(day + timedelta(days=i))
        files = sorted(manager.folder.glob('coffee-*.sqlite3'))
        self.assertEqual(len(files), 14)
        self.assertEqual(files[0].name, 'coffee-2026-01-03.sqlite3')
        self.assertEqual(manager.snapshot(day + timedelta(days=15)), files[-1])
        self.assertEqual(len(list(manager.folder.glob('coffee-*.sqlite3'))), 14)
        self.assertTrue(other.exists())

    def test_failed_backup_does_not_delete_good_snapshot_and_leaves_no_partial_file(self):
        manager = DailyBackups(self.store.path, self.root / 'snapshots', keep=1)
        first = manager.snapshot(datetime(2026, 1, 1, tzinfo=timezone.utc))
        with patch('cloud_storage.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                manager.snapshot(datetime(2026, 1, 2, tzinfo=timezone.utc))
        self.assertTrue(first.exists())
        self.assertEqual(list(manager.folder.glob('.snapshot-*')), [])
        self.assertEqual(len(list(manager.folder.glob('coffee-*.sqlite3'))), 1)

    def test_restore_rejects_existing_target_corrupt_and_missing_source(self):
        manager = DailyBackups(self.store.path, self.root / 'snapshots')
        good = manager.snapshot()
        before = self.store.path.read_bytes()
        with self.assertRaises(ValueError):
            restore_snapshot(good, self.store.path)
        self.assertEqual(self.store.path.read_bytes(), before)
        bad = self.root / 'corrupt.sqlite3'
        bad.write_text('not a database')
        for source in [bad, self.root / 'missing.sqlite3']:
            with self.subTest(source=source.name), self.assertRaises(sqlite3.Error):
                restore_snapshot(source, self.root / 'new.sqlite3')
            self.assertFalse((self.root / 'new.sqlite3').exists())
        self.assertFalse((self.root / 'missing.sqlite3').exists())

    def test_runtime_drops_root_before_serving_and_refuses_unmounted_disk(self):
        calls = []
        with patch('docker_entrypoint.os.geteuid', return_value=0), \
             patch('docker_entrypoint.os.setgroups', side_effect=lambda groups: calls.append('groups')), \
             patch('docker_entrypoint.os.setgid', side_effect=lambda gid: calls.append(('gid', gid))), \
             patch('docker_entrypoint.os.setuid', side_effect=lambda uid: calls.append(('uid', uid))):
            prepare_runtime({})
            self.assertEqual(calls, ['groups', ('gid', 10001), ('uid', 10001)])
            with patch('docker_entrypoint.os.path.ismount', return_value=False), self.assertRaises(ValueError):
                prepare_runtime({'COFFEE_STORAGE_MODE': 'persistent'})

    def test_empty_sqlite_file_is_not_accepted_as_an_existing_daily_backup(self):
        manager = DailyBackups(self.store.path, self.root / 'snapshots')
        day = datetime(2026, 1, 1, tzinfo=timezone.utc)
        (manager.folder / 'coffee-2026-01-01.sqlite3').touch()
        with self.assertRaises(ValueError):
            manager.snapshot(day)

    def test_full_json_restore_includes_preferences_and_repeating_does_not_duplicate(self):
        preferences = self.store.preferences(self.owner, dict(DEFAULT_PREFS, brews=['我的奶咖'],
            coffee_preference='milk', brew_categories={'我的奶咖': 'milk'}))
        item = self.store.save(self.owner, {'product': '个人奶咖', 'brew': '我的奶咖', 'brew_category': 'milk'})
        self.store.save(self.other, {'product': '原有记录保留'})
        backup = dict(format='coffee-buddy-web-v1', **self.store.state(self.owner))
        for _ in range(2):
            self.assertEqual(self.store.import_records(self.other, backup), 1)
        self.assertEqual(self.store.state(self.other)['preferences'], preferences)
        self.assertEqual(len(self.store.state(self.other)['records']), 2)
        self.assertIn(item['id'], [r['id'] for r in self.store.state(self.other)['records']])

    def test_json_restore_validation_failure_does_not_partially_change_records_or_preferences(self):
        baseline = self.store.state(self.other)
        prefs = dict(DEFAULT_PREFS, city='不应被部分导入')
        valid = {'product': '不应被部分导入'}
        for data in [dict(preferences=prefs, records=[valid, {'product': ''}]),
                     dict(preferences=dict(prefs, coffee_preference='invalid'), records=[valid]),
                     dict(preferences=None, records=[valid])]:
            with self.subTest(data=data), self.assertRaises(AppError):
                self.store.import_records(self.other, dict(format='coffee-buddy-web-v1', **data))
            self.assertEqual(self.store.state(self.other), baseline)


if __name__ == '__main__':
    unittest.main()
