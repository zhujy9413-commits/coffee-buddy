import io
import json
import os
import unittest
import urllib.error
import urllib.parse
from unittest.mock import patch

from map_location import location_config, proxy_location_request
from web_core import AppError

CONFIG={'AMAP_JS_API_KEY':'public-js-key', 'AMAP_JS_SECURITY_CODE':'private-js-code', 'AMAP_API_KEY':'private-web-key'}


class MapLocationTests(unittest.TestCase):
    def test_config_exposes_only_js_identifier_and_requires_complete_pair(self):
        with patch.dict(os.environ, CONFIG, clear=True):
            self.assertEqual(location_config(), {'provider':'amap','key':'public-js-key'})
            self.assertNotIn('private', json.dumps(location_config()))
        for config in ({}, {'AMAP_JS_API_KEY':'public-js-key'}, {'AMAP_JS_SECURITY_CODE':'private'}):
            with patch.dict(os.environ, config, clear=True):
                self.assertEqual(location_config(), {'provider':'browser'})

    @patch.dict(os.environ, CONFIG, clear=True)
    def test_proxy_fixes_host_and_credentials_and_preserves_callback(self):
        calls=[]
        def fetch(request, timeout):
            calls.append(request.full_url)
            return io.BytesIO(b'coffee_cb({"status":"1"})')
        with patch('map_location.urllib.request.urlopen', side_effect=fetch):
            body,mime=proxy_location_request('/_AMapService/v4/ip','key=attacker&jscode=attacker&callback=coffee_cb')
        parsed=urllib.parse.urlsplit(calls[0]);query=urllib.parse.parse_qs(parsed.query)
        self.assertEqual((parsed.scheme,parsed.hostname,parsed.path),('https','restapi.amap.com','/v4/ip'))
        self.assertEqual(query['key'],['public-js-key'])
        self.assertEqual(query['jscode'],['private-js-code'])
        self.assertEqual(body,b'coffee_cb({"status":"1"})')
        self.assertTrue(mime.startswith('application/javascript'))

    @patch.dict(os.environ, CONFIG, clear=True)
    def test_invalid_routes_callback_injection_and_large_queries_do_not_make_requests(self):
        with patch('map_location.urllib.request.urlopen') as fetch:
            for path,query in [('/_AMapService/v4/map/styles',''),('/_AMapService/https://evil.example',''),
                               ('/_AMapService/v4/ip','callback=alert(1)'),('/_AMapService/v4/ip','callback=a&callback=b'),
                               ('/_AMapService/v4/ip','x='+'a'*4100)]:
                with self.assertRaises(AppError): proxy_location_request(path,query)
            fetch.assert_not_called()

    @patch.dict(os.environ, CONFIG, clear=True)
    def test_security_code_is_never_reflected_and_upstream_errors_are_generic(self):
        with patch('map_location.urllib.request.urlopen', return_value=io.BytesIO(b'{"diagnostic":"private-js-code"}')):
            body,mime=proxy_location_request('/_AMapService/v4/ip','')
        self.assertNotIn(b'private-js-code',body)
        self.assertEqual(json.loads(body)['diagnostic'],'[redacted]')
        with patch('map_location.urllib.request.urlopen', side_effect=urllib.error.URLError('private-js-code')):
            with self.assertRaises(AppError) as ctx: proxy_location_request('/_AMapService/v4/ip','')
        self.assertNotIn('private-js-code',str(ctx.exception))


if __name__=='__main__': unittest.main()
