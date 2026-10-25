"""Offline regression and HTTP integration tests: python3 -m unittest test_web -v."""
import copy
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from web_app import make_handler
from web_core import Amap, AppError, BREW_CATEGORIES, DEFAULT_PREFS, Store, coords, extract_photo, historical_cafes, merge_cafes, recommend, search_cafes


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "test.sqlite3")
        self.user, _ = self.store.session(None)
        self.other, _ = self.store.session(None)
        self.cafe = {"id": "POI-A", "name": "测试店（A分店）", "address": "测试地址A", "distance": 100}

    def tearDown(self):
        self.tmp.cleanup()

    def entry(self, **kwargs):
        return self.store.save(self.user, dict(product="测试酒香豆", bean="批次豆A", cafe=self.cafe["name"],
            provider_id="POI-A", brew="冰美式", kind="tasting", reaction="like", label_flavors=["威士忌酒香"], **kwargs))

    def test_user_isolation_and_cookie_resume(self):
        item = self.entry()
        self.assertEqual(len(self.store.state(self.user)["records"]), 1)
        self.assertEqual(self.store.state(self.other)["records"], [])
        with self.assertRaises(AppError):
            self.store.delete(self.other, item["id"])
        self.assertEqual(self.store.session(self.user), (self.user, False))

    def test_custom_brew_preferences_persist_and_normalize(self):
        prefs = self.store.preferences(self.user, dict(DEFAULT_PREFS, brews=[' 冷萃 ', '手冲', '冷萃', '我的 SOE 美式']))
        self.assertEqual(prefs['brews'], ['冷萃', '手冲', '我的 SOE 美式'])
        reopened = Store(self.store.path)
        self.assertEqual(reopened.state(self.user)['preferences']['brews'], prefs['brews'])
        self.assertEqual(reopened.state(self.other)['preferences']['brews'], ['冰美式', '手冲'])

    def test_nearby_and_taste_have_different_real_rankings(self):
        near = self.store.save(self.user, {'product':'近处候选','brew':'冰美式','cafe':'近店','provider_id':'NEAR'})
        far = self.store.save(self.user, {'product':'喜欢的远店','brew':'冰美式','cafe':'远店','provider_id':'FAR','reaction':'like'})
        cafes = [dict(self.cafe,id='FAR',name='远店',distance=23000),dict(self.cafe,id='NEAR',name='近店',distance=100)]
        self.assertEqual(recommend(cafes,[near,far],DEFAULT_PREFS,'冰美式','nearby')[0]['id'],'NEAR')
        self.assertEqual(recommend(cafes,[near,far],DEFAULT_PREFS,'冰美式','taste')[0]['id'],'FAR')

    def test_taste_without_location_or_map_key_uses_only_documented_products(self):
        item=self.entry()
        with patch.dict(os.environ,{},clear=True), patch('web_core.json_request',side_effect=AssertionError('不应请求外部地图')):
            result=search_cafes({'mode':'taste','brew':'冰美式'},self.store.state(self.user))
        self.assertEqual(result['cafes'][0]['products'][0]['product'],item['product'])
        self.assertIsNone(result['cafes'][0]['distance'])
        self.assertIn('未查询实时地图',result['notice'])

    def test_taste_keeps_far_history_and_never_calls_unknown_distance_zero(self):
        item=self.entry(location={'lat':22.5,'lng':114.0,'system':'gcj02'})
        result=historical_cafes([item],{'lat':39.9,'lng':116.4})
        self.assertGreater(result[0]['distance'],50000)
        self.assertEqual(len(result),1)
        self.assertIsNone(historical_cafes([item])[0]['distance'])

    def test_map_and_history_are_deduplicated_without_replacing_verified_branch(self):
        entry=self.entry()
        history=historical_cafes([entry])
        mapped=dict(self.cafe,source='高德地点查询',location={'lat':39.9,'lng':116.4,'system':'gcj02'})
        result=merge_cafes([mapped],history)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['source'],'高德地点查询')

    def test_nearby_expands_when_results_are_sparse_and_then_stops(self):
        amap=Amap('test');calls=[]
        def fake(center,radius,sort_rule='distance'):
            calls.append(radius)
            return [{'id':str(i)} for i in range(1 if radius==2000 else 5)]
        amap.nearby=fake
        self.assertEqual(len(amap.discover({'lat':39.9,'lng':116.4},'nearby')),5)
        self.assertEqual(calls,[2000,5000])

    def test_taste_queries_wider_candidates_without_claiming_map_knows_taste(self):
        amap=Amap('test');calls=[]
        amap.nearby=lambda center,radius,sort_rule='distance': calls.append((radius,sort_rule)) or []
        self.assertEqual(amap.discover({'lat':39.9,'lng':116.4},'taste'),[])
        self.assertEqual(calls,[(50000,'weight')])

    def test_destination_uses_selected_city_and_does_not_accept_current_location(self):
        state=self.store.state(self.user);amap=Amap('test');seen=[]
        amap.center=lambda data,city:(seen.append((data,city)) or (None,[{'name':'选定地标'}]))
        result=search_cafes({'mode':'destination','city':'上海','landmark':'静安寺','brew':'冰美式'},state,amap)
        self.assertEqual(seen[0][1],'上海')
        self.assertEqual(result['places'][0]['name'],'选定地标')
        with self.assertRaises(AppError):
            search_cafes({'mode':'destination','location':{'lat':39.9,'lng':116.4},'source':'current'},state,amap)
        with self.assertRaises(AppError):
            search_cafes({'mode':'invalid'},state,amap)

    def test_new_user_is_unrestricted_and_legacy_black_preference_is_preserved(self):
        self.assertEqual(self.store.state(self.user)['preferences']['coffee_preference'], 'any')
        item = self.entry()
        legacy = {'city':'北京','area':'朝阳区','flavors':['偏酸'],'brews':['冰美式','手冲'],'exclude_milk':True}
        with self.store.connect() as con:
            con.execute('UPDATE users SET prefs=? WHERE token=?', (json.dumps(legacy), self.user))
        state = self.store.state(self.user)
        self.assertEqual(state['preferences']['coffee_preference'], 'black')
        self.assertEqual(state['records'][0]['id'], item['id'])
        self.store.preferences(self.user, state['preferences'])
        self.assertEqual(self.store.state(self.user)['preferences']['coffee_preference'], 'black')

    def test_milk_preference_persists_and_does_not_leak_to_other_users(self):
        self.store.preferences(self.user, dict(DEFAULT_PREFS, coffee_preference='milk', brews=['拿铁','冰美式']))
        state = self.store.state(self.user)
        self.assertEqual(state['preferences']['coffee_preference'], 'milk')
        self.assertFalse(state['preferences']['exclude_milk'])
        self.assertEqual(state['preferences']['brew_categories']['拿铁'], 'milk')
        self.assertEqual(self.store.state(self.other)['preferences']['coffee_preference'], 'any')
        with self.assertRaises(AppError):
            self.store.preferences(self.user, dict(DEFAULT_PREFS, coffee_preference='invalid'))

    def test_black_and_milk_recommendation_filters_are_symmetric(self):
        for name, category in BREW_CATEGORIES.items():
            item = self.store.save(self.user, {'product':'测试'+name,'brew':name,'provider_id':'POI-A','cafe':self.cafe['name']})
            for preference in ('black','milk','any'):
                result = recommend([self.cafe], [item], dict(DEFAULT_PREFS,coffee_preference=preference), name)[0]['products']
                self.assertEqual(bool(result), preference=='any' or preference==category, (name,preference))
        self.assertEqual(len(self.store.state(self.user)['records']),len(BREW_CATEGORIES))

    def test_custom_milk_classification_and_unknown_types_are_not_guessed(self):
        prefs = self.store.preferences(self.user, dict(DEFAULT_PREFS, coffee_preference='milk', brews=['我的燕麦咖啡'], brew_categories={'我的燕麦咖啡':'milk'}))
        custom = self.store.save(self.user, {'product':'测试自定义奶咖','brew':'我的燕麦咖啡','provider_id':'POI-A','cafe':self.cafe['name']})
        self.assertTrue(recommend([self.cafe],[custom],prefs,'我的燕麦咖啡')[0]['products'])
        unknown = self.store.save(self.user, {'product':'未知类型','brew':'未分类咖啡','provider_id':'POI-A','cafe':self.cafe['name']})
        self.assertEqual(recommend([self.cafe],[unknown],prefs,'未分类咖啡')[0]['products'],[])
        canonical = self.store.save(self.user, {'product':'测试拿铁','brew':'拿铁','brew_category':'black'})
        self.assertEqual(canonical['brew_category'],'milk')

    def test_removed_brew_keeps_existing_records_editable_and_exportable(self):
        item = self.store.save(self.user, {'product': '自定义饮品', 'brew': '我的 SOE 美式'})
        self.store.preferences(self.user, dict(DEFAULT_PREFS, brews=[]))
        records = self.store.state(self.user)['records']
        self.assertEqual(records[0]['brew'], '我的 SOE 美式')
        self.store.save(self.user, dict(item, note='移除类型后仍能编辑'))
        self.store.import_records(self.other, {'format': 'coffee-buddy-web-v1', 'records': records})
        self.assertEqual(self.store.state(self.other)['records'][0]['brew'], '我的 SOE 美式')

    def test_invalid_custom_brew_preferences_do_not_overwrite(self):
        for invalid in ([''], ['x' * 25], '冷萃', [123], ['a\nb'], [str(i) for i in range(21)]):
            with self.assertRaises(AppError):
                self.store.preferences(self.user, dict(DEFAULT_PREFS, brews=invalid))
        self.assertEqual(self.store.state(self.user)['preferences']['brews'], ['冰美式', '手冲'])

    def test_custom_brew_recommendations_use_its_own_evidence(self):
        item = self.store.save(self.user, {'product': '测试冷萃', 'brew': '我的冷萃', 'provider_id': 'POI-A', 'cafe': self.cafe['name'], 'reaction': 'like'})
        self.assertEqual(recommend([self.cafe], [item], DEFAULT_PREFS, '我的冷萃')[0]['products'][0]['brew'], '我的冷萃')
        self.assertEqual(recommend([self.cafe], [item], DEFAULT_PREFS, '冰美式')[0]['products'], [])

    def test_label_and_actual_taste_are_separate_and_edit_id_is_stable(self):
        item = self.entry(tasted_flavors=["偏苦"])
        self.assertEqual(item["label_flavors"], ["威士忌酒香"])
        self.assertEqual(item["tasted_flavors"], ["偏苦"])
        item["reaction"] = "dislike"
        self.store.save(self.user, item)
        self.assertEqual(len(self.store.state(self.user)["records"]), 1)

    def test_import_is_atomic_and_repeatable(self):
        item = self.entry()
        backup = {"format": "coffee-buddy-web-v1", "records": [item]}
        self.store.import_records(self.other, backup)
        self.store.import_records(self.other, backup)
        self.assertEqual(len(self.store.state(self.other)["records"]), 1)
        bad = copy.deepcopy(item)
        bad["product"] = ""
        with self.assertRaises(AppError):
            self.store.import_records(self.user, dict(backup, records=[item, bad]))
        self.assertEqual(len(self.store.state(self.user)["records"]), 1)

    def test_invalid_dates_and_unknown_coordinates_are_rejected(self):
        for changes in ({"observed_on": "2099-01-01"}, {"observed_on": "not-date"}, {"location": {"lat": 39, "lng": 116, "system": "wgs84"}}):
            with self.assertRaises(AppError):
                self.entry(**changes)
        for point in ({"lat": float('nan'), "lng": 116}, {"lat": 91, "lng": 116}):
            with self.assertRaises(AppError):
                coords(point)

    def test_no_product_invention_and_branch_separation(self):
        self.entry()
        cafes = [self.cafe, dict(self.cafe, id="POI-B", name="测试店（B分店）")]
        results = recommend(cafes, self.store.state(self.user)["records"], DEFAULT_PREFS, "冰美式")
        self.assertEqual(len(results[0]["products"]), 1)
        self.assertEqual(results[1]["products"], [])
        self.assertIn("在售情况待确认", results[0]["products"][0]["availability"])

    def test_dislike_is_per_brew_and_branch(self):
        item = self.entry()
        dislike = dict(item, id=None, brew="手冲", reaction="dislike")
        self.store.save(self.user, dislike)
        entries = self.store.state(self.user)["records"]
        self.assertTrue(recommend([self.cafe], entries, DEFAULT_PREFS, "冰美式")[0]["products"])
        self.assertEqual(recommend([self.cafe], entries, DEFAULT_PREFS, "手冲")[0]["products"], [])

    def test_menu_requires_source_and_never_counts_as_personal_like(self):
        menu = dict(product="菜单豆", cafe=self.cafe["name"], provider_id="POI-A", kind="menu", brew="手冲", source_note="店内豆单照片", label_flavors=["偏酸"])
        with self.assertRaises(AppError):
            self.store.save(self.user, dict(menu, source_note=""))
        self.store.save(self.user, menu)
        product = recommend([self.cafe], self.store.state(self.user)["records"], DEFAULT_PREFS, "手冲")[0]["products"][0]
        self.assertFalse(any("喜欢过" in reason for reason in product["reasons"]))
        self.assertEqual(product["observed_on"], date.today().isoformat())

    def test_wgs84_is_converted_once_and_poi_query_has_center(self):
        calls = []
        def fake(path, **params):
            calls.append((path, params))
            if "convert" in path: return {"locations": "116.400000,39.900000"}
            return {"pois": []}
        amap = Amap("test")
        amap.call = fake
        center, _ = amap.center({"location": {"lat": 39.89, "lng": 116.39, "system": "wgs84"}}, "北京")
        amap.nearby(center, 2000)
        self.assertEqual(calls[0][1]["coordsys"], "gps")
        self.assertEqual(calls[1][1]["location"], "116.4,39.9")
        calls.clear()
        amap.center({"location": dict(center, system="gcj02")}, "北京")
        self.assertEqual(calls, [])

    def test_landmark_requires_user_choice_instead_of_first_match(self):
        amap = Amap("test")
        amap.call = lambda *args, **kwargs: {"pois": [{"id": "a", "name": "测试地标", "location": "116.4,39.9", "adname": "朝阳区", "address": "测试地址"}]}
        center, choices = amap.center({"landmark": "测试地标"}, "北京")
        self.assertIsNone(center)
        self.assertEqual(choices[0]["location"]["system"], "gcj02")

    def test_missing_services_fail_without_fabricated_results(self):
        with self.assertRaises(AppError):
            Amap("").nearby({"lat": 39.9, "lng": 116.4}, 2000)
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(AppError):
            extract_photo({"image": "irrelevant"})

    def test_photo_extraction_is_a_clean_draft_with_no_extra_fields(self):
        import base64
        image = 'data:image/jpeg;base64,' + base64.b64encode(b'\xff\xd8\xfftest').decode()
        response = {"choices": [{"message": {"content": json.dumps({"items": [{"product": "可见豆名", "roast": "不确定烘焙", "label_flavors": ["威士忌酒香"], "reaction": "like"}]})}}]}
        env = {"VISION_ENDPOINT": "https://vision.example/chat/completions", "VISION_API_KEY": "test-only", "VISION_MODEL": "test-vision"}
        with patch.dict(os.environ, env), patch('web_core.photo_model_request', return_value=response) as request:
            result = extract_photo({"image": image})
            self.assertEqual(result["items"][0]["roast"], "未知")
            self.assertNotIn("reaction", result["items"][0])
            self.assertEqual(request.call_args.args[1]["messages"][0]["content"][1]["image_url"]["url"], image)
        self.assertEqual(self.store.state(self.user)["records"], [])

    def test_photo_malformed_response_is_actionable(self):
        import base64
        image = 'data:image/jpeg;base64,' + base64.b64encode(b'\xff\xd8\xfftest').decode()
        env = {"VISION_ENDPOINT": "https://vision.example/chat/completions", "VISION_API_KEY": "test-only", "VISION_MODEL": "test-vision"}
        with patch.dict(os.environ, env), patch('web_core.photo_model_request', return_value={}), self.assertRaises(AppError) as ctx:
            extract_photo({"image": image})
        self.assertIn("手动填写", str(ctx.exception))


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Store(Path(cls.tmp.name) / "test.sqlite3")))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:" + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.tmp.cleanup()

    def request(self, path, data=None, headers=None):
        h = {"Content-Type": "application/json", "X-Coffee-Client": "web-v1", **(headers or {})}
        req = urllib.request.Request(self.base + path, data=json.dumps(data).encode() if data is not None else None, headers=h)
        return urllib.request.urlopen(req)

    def test_roundtrip_and_session_separation(self):
        with self.request('/api/state') as response:
            cookie = response.headers['Set-Cookie'].split(';')[0]
        with self.request('/api/records', {"product": "HTTP 测试杯"}, {"Cookie": cookie}) as response:
            item = json.load(response)["record"]
        with self.request('/api/state', headers={"Cookie": cookie}) as response:
            self.assertEqual(json.load(response)["records"][0]["id"], item["id"])
        with self.request('/api/state') as response:
            self.assertEqual(json.load(response)["records"], [])

    def test_cross_origin_mutations_and_rebinding_are_rejected(self):
        for headers in ({"Origin": "https://other.example"}, {"Host": "other.example"}):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.request('/api/records', {"product": "test"}, headers)
            self.assertEqual(ctx.exception.code, 403)

    def test_static_assets_and_photo_fallback(self):
        for path in ('/', '/app.js', '/style.css', '/location.js', '/amap-location.js'):
            with self.request(path) as response:
                self.assertEqual(response.status, 200)
                self.assertIn('nosniff', response.headers['X-Content-Type-Options'])
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(urllib.error.HTTPError) as ctx:
            self.request('/api/extract', {"image": "none"})
        self.assertEqual(ctx.exception.code, 503)

    def test_location_proxy_blocks_cross_site_and_config_keeps_private_keys_server_side(self):
        with patch.dict(os.environ, {'AMAP_JS_API_KEY':'public-location-key','AMAP_JS_SECURITY_CODE':'private-location-code','AMAP_API_KEY':'private-web-key'}, clear=True):
            with self.request('/api/state') as response:
                cookie=response.headers['Set-Cookie'].split(';')[0]
                state=json.load(response)
                self.assertEqual(state['map_location']['key'],'public-location-key')
                self.assertNotIn('private-location-code',json.dumps(state))
                self.assertNotIn('private-web-key',json.dumps(state))
                self.assertNotIn('unsafe-eval',response.headers['Content-Security-Policy'])
            for headers in ({'Cookie':cookie,'Sec-Fetch-Site':'cross-site'},{'Cookie':cookie}, {'Sec-Fetch-Site':'same-origin'}):
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    self.request('/_AMapService/v4/ip',headers=headers)
                self.assertEqual(ctx.exception.code,403)
            with patch('web_app.proxy_location_request',return_value=(b'{"status":"1"}','application/json')):
                with self.request('/_AMapService/v4/ip',headers={'Cookie':cookie,'Sec-Fetch-Site':'same-origin'}) as response:
                    self.assertEqual(json.load(response)['status'],'1')

    def test_sdk_dynamic_execution_requires_explicit_opt_in_and_paired_keys(self):
        pair={'AMAP_JS_API_KEY':'public-location-key','AMAP_JS_SECURITY_CODE':'private-location-code'}
        for config,expected in (({},False),({'AMAP_JS_ALLOW_EVAL':'1'},False),(pair,False),
                                ({**pair,'AMAP_JS_ALLOW_EVAL':'0'},False),({**pair,'AMAP_JS_ALLOW_EVAL':'1'},True)):
            with patch.dict(os.environ,config,clear=True):
                with self.request('/') as response:
                    policy=response.headers['Content-Security-Policy']
                    self.assertEqual("'unsafe-eval'" in policy,expected)
                    self.assertIn("frame-ancestors 'none'",policy)
                    self.assertIn("form-action 'self'",policy)
                    self.assertNotIn("'unsafe-inline'",policy)


if __name__ == '__main__':
    unittest.main()
