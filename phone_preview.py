"""Password-protected, isolated iPhone preview behind an explicitly approved HTTPS tunnel.

Preparation alone does not open a tunnel. See PHONE_TEST.md before running.
"""
import argparse
import base64
import hmac
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from web_app import ROOT, load_env, make_handler
from web_core import AppError, Store


def preview_origin(value):
    url = urlsplit(value)
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or url.port not in (None, 443) or url.path not in ('', '/') or url.query or url.fragment
            or not re.fullmatch(r'[a-z0-9-]+\.trycloudflare\.com', url.hostname)):
        raise ValueError('需要本次 Cloudflare 临时测试链接，必须使用 HTTPS')
    return 'https://' + url.hostname


def make_preview_handler(store, password, origin, deadline):
    origin = preview_origin(origin)
    if len(password) < 24:
        raise ValueError('临时访问密码长度不足')
    hostname = urlsplit(origin).hostname
    parent = make_handler(store, allowed_hosts={hostname, '127.0.0.1', 'localhost'})
    expected = b'Basic ' + base64.b64encode(('coffee:' + password).encode())

    class Handler(parent):
        def prepare(self, mutation=False):
            if time.monotonic() >= deadline:
                raise AppError('本次手机测试已结束', 410)
            supplied = self.headers.get('Authorization', '').encode('utf-8')
            if not hmac.compare_digest(supplied, expected):
                raise AppError('请输入本次手机测试的访问凭据', 401)
            super().prepare(mutation)

        def reply(self, data, status=200, content_type='application/json; charset=utf-8'):
            self.need_auth = status == 401
            super().reply(data, status, content_type)

        def send_header(self, keyword, value):
            if keyword.lower() == 'set-cookie':
                value += '; Secure'
            super().send_header(keyword, value)

        def end_headers(self):
            if getattr(self, 'need_auth', False):
                self.send_header('WWW-Authenticate', 'Basic realm="Coffee Buddy iPhone test", charset="UTF-8"')
            super().end_headers()

    return Handler


def write_access_file(folder, origin, password):
    """Credentials remain in ignored local data; never print or serve this file."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / 'access.txt'
    fd, staging = tempfile.mkstemp(dir=str(folder), prefix='.access-')
    try:
        with os.fdopen(fd, 'w') as output:
            output.write('仅用于本次一小时手机测试，结束后密码失效。\n'
                         + '链接：' + origin + '\n用户名：coffee\n访问密码：' + password + '\n')
        os.replace(staging, target)
    finally:
        if os.path.exists(staging):
            os.unlink(staging)
    return target


def main():
    parser = argparse.ArgumentParser(description='Coffee Buddy 受保护的独立手机测试版')
    parser.add_argument('--origin', required=True, type=preview_origin)
    parser.add_argument('--port', type=int, default=8770)
    args = parser.parse_args()
    load_env()
    # Intentionally never open or copy data/web/coffee.sqlite3.
    folder = ROOT / 'data' / 'phone-preview'
    password = secrets.token_urlsafe(24)
    deadline = time.monotonic() + 3600
    server = ThreadingHTTPServer(('127.0.0.1', args.port),
        make_preview_handler(Store(folder / 'coffee.sqlite3'), password, args.origin, deadline))
    access_file = write_access_file(folder, args.origin, password)
    timer = threading.Timer(3600, server.shutdown)
    timer.daemon = True
    timer.start()
    print('手机测试后端已就绪；仅监听本机，通过已批准的 HTTPS 隧道访问。', flush=True)
    print('访问凭据仅保存于本机：' + str(access_file), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        timer.cancel()
        server.server_close()


if __name__ == '__main__':
    main()
