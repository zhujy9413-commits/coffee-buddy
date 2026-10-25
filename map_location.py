"""Optional JS-location configuration and a narrow server-side security-code proxy."""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from web_core import AppError

LOCATION_PATHS = {
    '/_AMapService/v4/ip': 'v4/ip',
    '/_AMapService/v3/ip': 'v3/ip',
    '/_AMapService/v3/geocode/regeo': 'v3/geocode/regeo',
    '/_AMapService/v3/assistant/coordinate/convert': 'v3/assistant/coordinate/convert',
}


def location_config():
    # The JS API key is a browser identifier. Its paired security code and the
    # separate Web-service key must never be returned to the browser.
    key = os.getenv('AMAP_JS_API_KEY', '').strip()
    code = os.getenv('AMAP_JS_SECURITY_CODE', '').strip()
    return {'provider': 'amap', 'key': key} if key and code else {'provider': 'browser'}


def allow_sdk_eval():
    # Opt-in compatibility for the vendor SDK; never enable from key presence alone.
    return location_config()['provider'] == 'amap' and os.getenv('AMAP_JS_ALLOW_EVAL', '') == '1'


def proxy_location_request(path, query):
    endpoint = LOCATION_PATHS.get(path)
    if not endpoint:
        raise AppError('不支持的定位服务', 404)
    config = location_config()
    if config['provider'] != 'amap':
        raise AppError('增强定位尚未配置', 503)
    if len(query) > 4096:
        raise AppError('定位请求过长')
    try:
        params = urllib.parse.parse_qs(query, keep_blank_values=True, max_num_fields=30)
    except ValueError:
        raise AppError('定位请求格式无效')
    callbacks = params.get('callback', [])
    if callbacks and (len(callbacks) != 1 or not re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*', callbacks[0]) or len(callbacks[0]) > 160):
        raise AppError('定位回调格式无效')
    code = os.environ['AMAP_JS_SECURITY_CODE'].strip()
    params['key'], params['jscode'] = [config['key']], [code]
    url = 'https://restapi.amap.com/' + endpoint + '?' + urllib.parse.urlencode(params, doseq=True)
    try:
        request = urllib.request.Request(url, headers={'Accept': 'application/json, text/javascript'})
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read(1024 * 1024 + 1)
        if len(body) > 1024 * 1024:
            raise ValueError()
        # Do not reflect the security code even if an upstream diagnostic does.
        body = body.replace(code.encode(), b'[redacted]')
        if not callbacks:
            json.loads(body)
    except (OSError, ValueError):
        raise AppError('高德定位服务暂时不可用，请手动选择地点。', 502)
    return body, 'application/javascript; charset=utf-8' if callbacks else 'application/json; charset=utf-8'
