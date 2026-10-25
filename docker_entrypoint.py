"""Initialize the mounted data directory, then run the app without root."""
import os
from pathlib import Path

from cloud_preview import main


def prepare_runtime(env):
    if os.geteuid() != 0:
        return
    os.umask(0o077)
    if env.get('COFFEE_STORAGE_MODE') == 'persistent':
        mount = Path('/var/data')
        if mount.is_symlink() or not os.path.ismount(mount):
            raise ValueError('持久磁盘尚未挂载')
        # Set ownership of only the application's own directory, never the disk
        # root or unrelated files. O_NOFOLLOW avoids following a symlink.
        folder = mount / 'coffee-buddy'
        folder.mkdir(mode=0o700, exist_ok=True)
        fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fchown(fd, 10001, 10001)
            os.fchmod(fd, 0o700)
        finally:
            os.close(fd)
    os.setgroups([])
    os.setgid(10001)
    os.setuid(10001)


if __name__ == '__main__':
    prepare_runtime(os.environ)
    main()
