"""Cloud app with personal login and bounded external services. No .env is loaded."""
import os
import re
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from web_app import INSTALL_ASSETS, make_handler
from web_core import AppError
from cloud_storage import open_cloud_store


NOTICE = '云端测试版：使用独立测试数据；休眠、重启或重新部署后记录可能清空。重要记录请及时导出备份。'
PERSISTENT_NOTICE = '云端个人版：记录保存在持久磁盘，重启和重新部署后保留。每天自动生成数据库备份；仍请定期导出到自己的设备。'
POSTGRES_NOTICE = '云端持久保存：记录保存在独立数据库，网页休眠、重启和更新后保留。免费额度有限；仍请定期导出备份。'


def cloud_settings(env):
    hostname = env.get('RENDER_EXTERNAL_HOSTNAME', '').strip().lower()
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.onrender\.com', hostname):
        raise ValueError('需要 Render 自动提供的 HTTPS 服务域名')
    if not env.get('AMAP_API_KEY', '').strip():
        raise ValueError('请在云端配置高德 Web 服务 Key')
    if any(env.get(key, '').strip() for key in ('AMAP_JS_API_KEY', 'AMAP_JS_SECURITY_CODE', 'AMAP_JS_ALLOW_EVAL')):
        raise ValueError('云端测试使用设备定位，请勿配置本机 JS SDK 密钥或兼容开关')
    try:
        port = int(env.get('PORT', '10000'))
        if not 1024 <= port <= 65535:
            raise ValueError()
    except ValueError:
        raise ValueError('云端端口配置无效') from None
    return hostname, port


def make_cloud_handler(store, hostname, backups=None):
    # Revalidate the security settings even when this factory is used directly.
    cloud_settings({'RENDER_EXTERNAL_HOSTNAME': hostname, 'AMAP_API_KEY': 'configured'})
    parent = make_handler(store, allowed_hosts={hostname}, require_account=True)
    origin = 'https://' + hostname

    class Handler(parent):
        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def prepare(self, mutation=False):
            if mutation and self.headers.get('Origin') != origin:
                raise AppError('请求来源无效', 403)
            super().prepare(mutation)

        def do_GET(self):
            # Render health checks reveal no records or credentials and create no sessions.
            if self.path == '/healthz':
                self.reply({'ok': True})
            elif self.path in INSTALL_ASSETS:
                # iOS can fetch installation artwork outside the signed-in tab.
                # Fixed installation assets carry no personal data.
                self.install_asset(self.path)
            else:
                super().do_GET()

        def reply(self, data, status=200, content_type='application/json; charset=utf-8'):
            if status == 200 and urlsplit(self.path).path == '/api/state' and isinstance(data, dict):
                deployment = {'mode': 'cloud-preview', 'ephemeral': True, 'notice': NOTICE}
                if getattr(store, 'storage_backend', None) == 'postgres':
                    deployment = {'mode': 'cloud-personal', 'backend': 'postgres', 'ephemeral': False,
                                  'notice': POSTGRES_NOTICE}
                if backups is not None:
                    deployment = {'mode': 'cloud-personal', 'ephemeral': False, 'notice': PERSISTENT_NOTICE,
                                  'backup': backups.status()}
                data = dict(data, deployment=dict(deployment, login_required=True))
            super().reply(data, status, content_type)

        def send_header(self, keyword, value):
            if keyword.lower() == 'set-cookie':
                value += '; Secure'
            super().send_header(keyword, value)

        def end_headers(self):
            self.send_header('X-Robots-Tag', 'noindex, nofollow, noarchive')
            super().end_headers()

    return Handler


def main():
    # Never load .env or open data/web. Runtime secrets are provided by the host.
    hostname, port = cloud_settings(os.environ)
    os.umask(0o077)
    store, backups = open_cloud_store(os.environ)
    server = ThreadingHTTPServer(('0.0.0.0', port), make_cloud_handler(store, hostname, backups))
    print('Coffee Buddy 云端服务已启动；使用个人账号登录。', flush=True)
    try:
        if backups:
            backups.start()
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if backups:
            backups.close()


if __name__ == '__main__':
    main()
