"""Run real Chrome/Edge on Windows against disposable, offline app data.

No .env, production credentials, production records, provider calls, or UA spoofing.
"""
from __future__ import annotations

from http.server import ThreadingHTTPServer
from pathlib import Path
import hashlib
import json
import os
import platform
import secrets
import struct
import sys
import tempfile
import threading
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from web_app import make_handler
from web_core import Store
from playwright.sync_api import sync_playwright, expect

ASSETS = ['index.html', 'app.js', 'style.css', 'accounts.js', 'journal.js',
          'menu-batch.js', 'menu-drafts.js', 'location.js', 'amap-location.js']
OUT = Path(os.environ.get('OUTPUT_DIR', 'qa-artifacts/windows'))
OUT.mkdir(parents=True, exist_ok=True)
REPORT = {'os': platform.platform(), 'python': platform.python_version(),
          'real_windows': os.name == 'nt', 'production_modified': False,
          'external_services_called': False, 'browsers': [],
          'source_sha256': {name: hashlib.sha256((ROOT/'web'/name).read_bytes()).hexdigest()
                            for name in ASSETS}}


def png_bytes():
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind+data))
    raw = (b'\x00' + bytes([235, 240, 225])*64)*64
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 64, 64, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def fixture_handler(store):
    parent = make_handler(store, session_cookie='coffee_windows_qa', require_account=True)

    class Handler(parent):
        def reply(self, data, status=200, content_type='application/json; charset=utf-8'):
            if self.path == '/api/state' and status == 200:
                data = dict(data, deployment={'login_required': True, 'ephemeral': True,
                            'notice': 'Windows 兼容验收 · 虚构资料 · 临时隔离数据库'})
            super().reply(data, status, content_type)

    return Handler


def run_browser(browser, channel, origin):
    result = {'channel': channel, 'version': browser.version, 'checks': [], 'screenshots': []}
    REPORT['browsers'].append(result)
    context = browser.new_context(viewport={'width': 1366, 'height': 768}, locale='zh-CN')
    page = context.new_page()
    page.set_default_timeout(15000)
    errors, external = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))

    def restrict_network(route):
        if route.request.url.startswith(origin + '/'):
            route.continue_()
        else:
            external.append(route.request.url.split('?')[0])
            route.abort()

    context.route('http://**/*', restrict_network)
    context.route('https://**/*', restrict_network)

    def check(value, name):
        result['checks'].append({'name': name, 'passed': bool(value)})
        assert value, name

    def layout(name):
        metrics = page.evaluate('''() => ({width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
          dialogs: [...document.querySelectorAll('dialog[open]')].map(e => ({
            left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right,
            client:e.clientWidth,scroll:e.scrollWidth}))})''')
        check(metrics['scrollWidth'] <= metrics['width']+1, name + ': no page overflow')
        check(all(d['left'] >= -1 and d['right'] <= metrics['width']+1 and d['scroll'] <= d['client']+1
                  for d in metrics['dialogs']), name + ': dialogs fit viewport')

    def shot(name):
        filename = f'{channel}-{name}.png'
        page.screenshot(path=str(OUT/filename), full_page=False,
                        mask=[page.locator('#account-code'), page.locator('#account-password'),
                              page.locator('#account-confirm')])
        result['screenshots'].append(filename)

    def tab(name):
        page.locator(f'[data-tab="{name}"]').click()
        expect(page.locator('#'+name)).to_be_visible()

    username = 'Win_' + channel + '_' + secrets.token_hex(3)
    password = secrets.token_urlsafe(12)
    product = '【测试】柑橘冰美式'
    cafe = '【虚构】Windows 兼容验收店'
    try:
        page.goto(origin, wait_until='networkidle')
        expect(page.locator('#account-dialog')).to_be_visible()
        check(page.locator('#account-mode').input_value() == 'login', 'initial personal login')
        layout('login 1366x768')
        page.locator('#account-mode').select_option('register')
        page.locator('#account-username').fill(username)
        page.locator('#account-password').fill(password)
        page.locator('#account-confirm').fill(password)
        page.locator('#account-submit').click()
        expect(page.locator('#account-receipt')).to_be_visible()
        check(bool(page.locator('#account-code').input_value()), 'registration recovery code generated')
        check(page.locator('#account-done').is_disabled(), 'recovery acknowledgement required')
        page.locator('#account-code-saved').check()
        page.locator('#account-done').click()
        expect(page.locator('#account-open')).to_contain_text(username)
        check(True, 'registration completes in Windows browser')

        page.locator('#prefs-open').click()
        page.locator('#pref-flavors').fill('柑橘、茉莉')
        page.locator('#pref-city').fill('测试城市')
        page.locator('#pref-area').fill('兼容验收区')
        page.locator('#prefs-form [name="coffee_preference"][value="any"]').check()
        page.locator('#prefs-form [name="roasts"][value="浅烘"]').check()
        page.get_by_role('button', name='保存偏好', exact=True).click()
        expect(page.locator('#prefs-dialog')).not_to_be_visible()
        check(True, 'preferences saved')

        tab('record')
        page.locator('#photo').set_input_files({'name': 'fixture.png', 'mimeType': 'image/png', 'buffer': png_bytes()})
        expect(page.locator('#photo-preview')).to_be_visible()
        check(page.locator('#extract').is_disabled(), 'image upload/preview works; no model configured or called')
        page.locator('#product').fill(product)
        page.locator('#brew').select_option('冰美式')
        page.locator('#cafe').fill(cafe)
        page.locator('#address').fill('虚构地址，仅用于自动验收')
        page.locator('#roast').select_option('浅烘')
        page.locator('#label_flavors').fill('柑橘、茉莉')
        page.locator('#tasted_flavors').fill('柑橘、微酸')
        page.locator('#record-form [name="reaction"][value="like"]').check()
        page.locator('#save-record').click()
        expect(page.locator('#history')).to_be_visible()
        expect(page.locator('#record-count')).to_have_text('1')
        expect(page.locator('#history-results')).to_contain_text('实际喝到：柑橘、微酸')
        check(True, 'Chinese tasting record saved')

        tab('record')
        page.locator('#batch-open').click()
        page.locator('#batch-cafe').fill(cafe)
        page.locator('#batch-address').fill('虚构地址，仅用于自动验收')
        page.locator('#batch-source').fill('Windows 自动验收，全部为虚构测试产品')
        page.locator('#batch-brew').select_option('冰美式')
        page.locator('#batch-text').fill(product + ' | 测试豆 A | 浅烘 | 柑橘、茉莉\n【测试】可可冰美式 | 测试豆 B | 中烘 | 可可')
        page.locator('#batch-parse').click()
        expect(page.locator('.menu-draft')).to_have_count(2)
        check(page.locator('#batch-save').is_disabled(), 'batch requires human confirmation')
        for item in page.locator('[data-menu-reviewed]').all():
            item.check()
        expect(page.locator('#batch-save')).to_be_enabled()
        layout('batch review 1366x768')
        shot('batch-review')
        page.locator('#batch-save').click()
        expect(page.locator('#menu-batch-dialog')).not_to_be_visible()
        expect(page.locator('#record-count')).to_have_text('3')
        check(True, 'two-item batch saves atomically through UI')

        tab('nearby')
        page.locator('#search-mode').select_option('taste')
        page.locator('#taste-search').click()
        expect(page.locator('#nearby-results')).to_contain_text(product)
        expect(page.locator('#nearby-results')).to_contain_text('喜欢过这款')
        check(True, 'saved feedback appears in history-based recommendation')
        shot('recommendation')

        tab('history')
        page.locator('#filter-text').fill('可可')
        expect(page.locator('.journal-card')).to_have_count(1)
        page.locator('#filter-text').fill('')
        expect(page.locator('.journal-card')).to_have_count(3)
        check(True, 'Chinese history filtering')
        with page.expect_download() as download_info:
            page.locator('#export').click()
        download = download_info.value
        export_path = OUT/f'{channel}-fixture-export.json'
        download.save_as(export_path)
        exported = json.loads(export_path.read_text(encoding='utf-8'))
        check(len(exported['records']) == 3, 'Windows backup download contains all records')
        export_path.unlink()

        for width, height in [(1366, 768), (1920, 1080), (1280, 720)]:
            page.set_viewport_size({'width': width, 'height': height})
            for name in ['nearby', 'record', 'history']:
                tab(name)
                layout(f'{name} {width}x{height}')
            page.locator('#prefs-open').click()
            layout(f'preferences {width}x{height}')
            page.locator('#prefs-close').click()
            page.evaluate('scrollTo(0,0)')
            shot(f'history-{width}')

        page.locator('#account-open').click()
        page.once('dialog', lambda dialog: dialog.accept())
        page.locator('#account-logout').click()
        expect(page.locator('#account-dialog')).to_be_visible()
        expect(page.locator('#record-count')).to_have_text('0')
        check(True, 'logout hides account records')
        page.locator('#account-username').fill(username.lower())
        page.locator('#account-password').fill(password)
        page.locator('#account-submit').click()
        expect(page.locator('#account-status')).to_contain_text('用户名或密码不正确')
        check(True, 'username case is enforced')
        page.locator('#account-username').fill(username)
        page.locator('#account-password').fill(password)
        page.locator('#account-submit').click()
        expect(page.locator('#account-dialog')).not_to_be_visible()
        expect(page.locator('#record-count')).to_have_text('3')
        page.reload(wait_until='networkidle')
        expect(page.locator('#record-count')).to_have_text('3')
        page.locator('#prefs-open').click()
        expect(page.locator('#pref-flavors')).to_have_value('柑橘、茉莉')
        expect(page.locator('#pref-city')).to_have_value('测试城市')
        page.locator('#prefs-close').click()
        check(True, 'records/preferences survive logout, login and refresh')
        second = browser.new_context(viewport={'width': 1366, 'height': 768}, locale='zh-CN')
        try:
            guest = second.new_page()
            guest.goto(origin, wait_until='networkidle')
            expect(guest.locator('#record-count')).to_have_text('0')
            check(True, 'separate browser identity cannot see account records')
            guest.locator('#account-username').fill(username)
            guest.locator('#account-password').fill(password)
            guest.locator('#account-submit').click()
            expect(guest.locator('#record-count')).to_have_text('3')
            check(True, 'fresh browser context finds records after personal login')
        finally:
            second.close()
        check(not errors, 'no uncaught browser JavaScript errors')
        check(not external, 'no external service requests')
        result['passed'] = True
    except Exception:
        result['passed'] = False
        shot('failure')
        raise
    finally:
        context.close()


def main():
    assert os.name == 'nt', 'This check requires actual Windows; a Windows user agent is insufficient.'
    for key in list(os.environ):
        if key.startswith(('AMAP_', 'VISION_')):
            os.environ.pop(key)
    with tempfile.TemporaryDirectory(prefix='coffee-windows-qa-') as directory:
        server = ThreadingHTTPServer(('127.0.0.1', 0), fixture_handler(Store(Path(directory)/'fixture.sqlite3')))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with sync_playwright() as playwright:
                for channel in ['chrome', 'msedge']:
                    browser = playwright.chromium.launch(channel=channel, headless=True)
                    try:
                        run_browser(browser, channel, f'http://127.0.0.1:{server.server_port}')
                    finally:
                        browser.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
            (OUT/'report.json').write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'os': REPORT['os'], 'browsers': [
        {'channel': b['channel'], 'version': b['version'], 'checks': len(b['checks']), 'passed': b.get('passed', False)}
        for b in REPORT['browsers']]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
