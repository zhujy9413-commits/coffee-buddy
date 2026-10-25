"""Isolated local demonstration with explicitly fictional coffee products."""
import argparse
from datetime import date
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
from urllib.parse import urlsplit
import uuid

from web_app import make_handler
from web_core import DEFAULT_PREFS, Store


DEMO_NOTICE = '独立演示版：咖啡极物社产品为用户授权编写的虚构测试资料，不代表店铺真实菜单或在售情况。不会修改个人记录。'
DEMO_PRODUCTS = [
    ('桶香冰美式', '冰美式', 'black', '中浅烘', ['威士忌酒香', '焦糖']),
    ('柑橘花香手冲', '手冲', 'black', '浅烘', ['柑橘', '茉莉', '果酸']),
    ('青苹果轻辣特调', '特调咖啡', 'black', '未知', ['青苹果', '轻辣']),
    ('坚果可可冰美式', '冰美式', 'black', '中深烘', ['坚果', '可可']),
    ('榛果燕麦拿铁', '拿铁', 'milk', '中烘', ['榛果', '巧克力']),
]


class DemoStore(Store):
    def session(self, token):
        owner, created = super().session(token)
        if created:
            prefs = dict(DEFAULT_PREFS, brews=['冰美式', '手冲', '特调咖啡', '拿铁'],
                         brew_categories={'特调咖啡': 'black'})
            # These recipes/classifications are fictional test inputs, never
            # inferred attributes of the real café's products.
            self.preferences(owner, prefs)
            items = []
            for index, (name, brew, category, roast, flavors) in enumerate(DEMO_PRODUCTS):
                items.append({'id': str(uuid.uuid5(uuid.NAMESPACE_URL, owner + ':demo:' + str(index))),
                    'kind': 'menu', 'product': '【测试】' + name, 'brew': brew, 'brew_category': category,
                    'roast': roast, 'bean': '【虚构】测试豆 ' + str(index + 1), 'batch': '虚构测试批次',
                    'cafe': '咖啡极物社（高碑店）', 'address': '演示地址（不用于导航）',
                    'observed_on': date.today().isoformat(), 'label_flavors': flavors,
                    'source_note': '用户授权编写的虚构测试豆单，不代表真实产品或在售情况',
                    'note': '仅用于验证录入、筛选、推荐和反馈，不作为店铺真实资料。'})
            self.save_menu_batch(owner, {'items': items})
        return owner, created


def make_demo_handler(store):
    parent = make_handler(store, session_cookie='coffee_demo_session')

    class Handler(parent):
        def reply(self, data, status=200, content_type='application/json; charset=utf-8'):
            if status == 200 and urlsplit(self.path).path == '/api/state' and isinstance(data, dict):
                data = dict(data, demo={'enabled': True, 'notice': DEMO_NOTICE})
            super().reply(data, status, content_type)

    return Handler


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='本机独立演示；不读取个人库或 .env')
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--data-dir', type=Path, default=Path(__file__).parent / 'data' / 'demo')
    args = parser.parse_args()
    # No .env loading or real external calls for fictional recommendations.
    for key in list(os.environ):
        if key.startswith(('AMAP_', 'VISION_')):
            os.environ.pop(key)
    os.umask(0o077)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_demo_handler(DemoStore(args.data_dir / 'demo.sqlite3')))
    print(f'Coffee Buddy 独立演示版：http://localhost:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
