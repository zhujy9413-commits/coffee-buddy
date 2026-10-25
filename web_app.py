#!/usr/bin/env python3
"""Run the local Coffee Buddy web app: python3 web_app.py."""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import time
from collections import defaultdict
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from web_core import AppError, BREW_CATEGORIES, Store, extract_photo, search_cafes
from map_location import location_config, proxy_location_request, allow_sdk_eval

ROOT = Path(__file__).resolve().parent


def load_env():
    path = ROOT / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def make_handler(store, allowed_hosts=None, session_cookie='coffee_session'):
    limits = defaultdict(list)
    accepted_hosts = frozenset({"localhost", "127.0.0.1", "::1"} if allowed_hosts is None else allowed_hosts)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # Request paths only; request bodies, coordinates and provider keys are never logged.
            pass

        def reply(self, data, status=200, content_type="application/json; charset=utf-8"):
            body = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, (dict, list)) else data
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Permissions-Policy", "geolocation=(self), camera=(), microphone=()")
            sdk_sources = " https://webapi.amap.com" if location_config()['provider'] == 'amap' else ""
            sdk_execution = " 'unsafe-eval'" if allow_sdk_eval() else ""
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'" + sdk_sources + sdk_execution + "; connect-src 'self'" + sdk_sources + "; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if getattr(self, "new_session", False):
                self.send_header("Set-Cookie", session_cookie + "=" + self.owner + "; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000")
            self.end_headers()
            self.wfile.write(body)

        def prepare(self, mutation=False):
            host = urlparse("http://" + self.headers.get("Host", "")).hostname
            if host not in accepted_hosts:
                raise AppError("此版本仅供本机使用", 403)
            if mutation:
                if self.headers.get("X-Coffee-Client") != "web-v1":
                    raise AppError("请求来源无效", 403)
                origin = self.headers.get("Origin")
                if origin and urlparse(origin).netloc != self.headers.get("Host"):
                    raise AppError("请求来源无效", 403)
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
            except Exception:
                cookie = SimpleCookie()
            token = cookie.get(session_cookie)
            self.owner, self.new_session = store.session(token.value if token else None)

        def body(self):
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                raise AppError("请求需要 JSON 格式", 415)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 6 * 1024 * 1024:
                    raise AppError("请求为空或内容过大", 413)
                result = json.loads(self.rfile.read(length))
                if not isinstance(result, dict):
                    raise ValueError()
                return result
            except (ValueError, UnicodeError):
                raise AppError("请求内容格式不正确")

        def do_GET(self):
            try:
                self.prepare()
                path = urlparse(self.path).path
                if path == "/api/state":
                    data = store.state(self.owner)
                    data["brew_catalog"] = BREW_CATEGORIES
                    data["services"] = {"maps": bool(os.getenv("AMAP_API_KEY")), "vision": all(os.getenv(k) for k in ("VISION_ENDPOINT", "VISION_API_KEY", "VISION_MODEL"))}
                    data['map_location'] = location_config()
                    self.reply(data)
                elif path.startswith('/_AMapService/'):
                    if self.new_session or self.headers.get('Sec-Fetch-Site') != 'same-origin':
                        raise AppError('定位请求来源无效', 403)
                    now = time.monotonic()
                    key = 'location:' + self.owner
                    limits[key] = [t for t in limits[key] if now-t < 60]
                    if len(limits[key]) >= 20:
                        raise AppError('定位请求较频繁，请稍后再试', 429)
                    limits[key].append(now)
                    body, content_type = proxy_location_request(path, urlparse(self.path).query)
                    self.reply(body, content_type=content_type)
                elif path == "/api/export":
                    self.reply(dict(format="coffee-buddy-web-v1", **store.state(self.owner)))
                elif path in {"/", "/app.js", "/style.css", "/location.js", "/amap-location.js", "/journal.js", "/menu-drafts.js", "/menu-batch.js"}:
                    file = ROOT / "web" / ("index.html" if path == "/" else path[1:])
                    self.reply(file.read_bytes(), content_type=mimetypes.guess_type(file.name)[0] + "; charset=utf-8")
                else:
                    raise AppError("页面不存在", 404)
            except AppError as exc:
                self.reply({"error": str(exc)}, exc.status)

        def do_POST(self):
            try:
                self.prepare(mutation=True)
                data, path = self.body(), urlparse(self.path).path
                if path == "/api/records":
                    self.reply({"record": store.save(self.owner, data)})
                elif path == '/api/menu-batch':
                    self.reply(store.save_menu_batch(self.owner, data))
                elif path == "/api/delete":
                    store.delete(self.owner, data.get("id", ""))
                    self.reply({"ok": True})
                elif path == "/api/preferences":
                    self.reply({"preferences": store.preferences(self.owner, data)})
                elif path == "/api/import":
                    self.reply({"count": store.import_records(self.owner, data)})
                elif path == "/api/nearby":
                    self.reply(search_cafes(data, store.state(self.owner)))
                elif path == "/api/extract":
                    now = time.monotonic()
                    limits[self.owner] = [t for t in limits[self.owner] if now - t < 60]
                    if len(limits[self.owner]) >= 5:
                        raise AppError("识别请求较频繁，请稍后再试", 429)
                    limits[self.owner].append(now)
                    self.reply(extract_photo(data))
                else:
                    raise AppError("接口不存在", 404)
            except AppError as exc:
                self.reply({"error": str(exc)}, exc.status)
            except Exception:
                self.reply({"error": "操作未完成，请稍后重试"}, 500)

    return Handler


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Coffee Buddy 本机开发版")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "web")
    args = parser.parse_args()
    load_env()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(Store(args.data_dir / "coffee.sqlite3")))
    print(f"Coffee Buddy: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
