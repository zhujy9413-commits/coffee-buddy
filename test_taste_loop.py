import tempfile
from pathlib import Path
import unittest

from web_core import Store, DEFAULT_PREFS, AppError, recommend, search_cafes


class TasteLoopTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.folder.name) / 'taste.sqlite3')
        self.owner, _ = self.store.session(None)
        self.cafe = {'id': 'branch-a', 'name': '测试 A 分店', 'address': '测试地址', 'distance': 100}

    def tearDown(self):
        self.folder.cleanup()

    def save(self, **changes):
        return self.store.save(self.owner, dict({'product': '冰美式', 'bean': '测试豆 A', 'batch': '批次 A',
            'roast': '浅烘', 'provider_id': self.cafe['id'], 'cafe': self.cafe['name'], 'address': self.cafe['address']}, **changes))

    def recommendations(self, **prefs):
        return recommend([self.cafe], self.store.state(self.owner)['records'], dict(DEFAULT_PREFS, **prefs), '冰美式')[0]['products']

    def test_roast_preferences_persist_and_remain_optional_for_legacy_users(self):
        self.assertEqual(self.store.state(self.owner)['preferences']['roasts'], [])
        self.store.preferences(self.owner, dict(DEFAULT_PREFS, roasts=['浅烘', '中浅烘', '浅烘']))
        self.assertEqual(Store(self.store.path).state(self.owner)['preferences']['roasts'], ['浅烘', '中浅烘'])
        for invalid in ['浅烘', ['未知'], ['extra'], [None]]:
            with self.subTest(invalid=invalid), self.assertRaises(AppError):
                self.store.preferences(self.owner, dict(DEFAULT_PREFS, roasts=invalid))

    def test_actual_taste_is_labeled_as_personal_evidence_not_menu_text(self):
        self.save(reaction='like', label_flavors=['巧克力'], tasted_flavors=['果酸明亮'])
        product = self.recommendations(flavors=['偏酸'])[0]
        self.assertEqual(product['flavors'], ['巧克力'])
        self.assertEqual(product['tasted_flavors'], ['果酸明亮'])
        self.assertTrue(any('最近一次喝到' in reason for reason in product['reasons']))
        self.assertFalse(any('标注风味' in reason for reason in product['reasons']))

    def test_known_different_beans_and_batches_do_not_share_dislike(self):
        self.save(reaction='dislike')
        same_name_new_batch = self.save(kind='menu', batch='批次 B', source_note='测试豆单')
        same_name_new_bean = self.save(kind='menu', bean='测试豆 B', source_note='测试豆单')
        ids = {p['record_id'] for p in self.recommendations()}
        self.assertEqual(ids, {same_name_new_batch['id'], same_name_new_bean['id']})

    def test_latest_feedback_changes_recommendation_without_overwriting_menu(self):
        menu = self.save(kind='menu', source_note='测试豆单', label_flavors=['偏酸'])
        liked = self.save(reaction='like', label_flavors=['偏酸'], tasted_flavors=['果酸'])
        products = self.recommendations(flavors=['偏酸'])
        self.assertTrue(any('喜欢过' in reason for reason in products[0]['reasons']))
        self.save(reaction='dislike')
        self.assertEqual(self.recommendations(), [])
        records = self.store.state(self.owner)['records']
        self.assertEqual(len(records), 3)
        self.assertEqual(next(r for r in records if r['id'] == menu['id'])['kind'], 'menu')
        self.assertEqual(next(r for r in records if r['id'] == liked['id'])['reaction'], 'like')

    def test_negated_or_weak_taste_is_not_scored_as_detected_flavor(self):
        for tasted in ['没有酒香', '酒香不明显', '无威士忌', '酒香很弱']:
            with self.subTest(tasted=tasted):
                item = self.save(tasted_flavors=[tasted])
                product = recommend([self.cafe], [item], dict(DEFAULT_PREFS, flavors=['威士忌酒香']), '冰美式')[0]['products'][0]
                self.assertEqual(product['score'], 0)
                self.assertFalse(any('最近一次喝到' in reason for reason in product['reasons']))

    def test_roast_is_soft_ranking_and_unknown_is_not_inferred(self):
        self.save(product='未知烘焙', roast='未知')
        shallow = self.save(product='已知浅烘')
        self.save(product='已知深烘', roast='深烘')
        products = self.recommendations(roasts=['浅烘'], flavors=[])
        self.assertEqual(products[0]['record_id'], shallow['id'])
        self.assertEqual(len(products), 3)
        self.assertTrue(any('烘焙偏好' in reason for reason in products[0]['reasons']))
        self.assertEqual(next(p for p in products if p['roast'] == '未知')['score'], 0)

    def test_saved_manual_branch_can_complete_recommendation_feedback_loop_without_map(self):
        self.save(kind='menu', provider_id='', source_note='测试菜单', label_flavors=['偏酸'])
        query = {'mode': 'taste', 'brew': '冰美式'}
        before = search_cafes(query, self.store.state(self.owner))
        self.assertEqual(len(before['cafes'][0]['products']), 1)
        self.save(provider_id='', reaction='like', tasted_flavors=['酸甜'])
        after = search_cafes(query, self.store.state(self.owner))
        self.assertTrue(any('喜欢过' in reason for reason in after['cafes'][0]['products'][0]['reasons']))

    def test_average_and_legacy_undecided_survive_export_import_separately(self):
        average = self.save(product='明确一般', reaction='okay')
        undecided = self.save(product='旧版中性', reaction='neutral')
        before = self.store.state(self.owner)
        other, _ = self.store.session(None)
        backup = dict(format='coffee-buddy-web-v1', records=before['records'])
        self.store.import_records(other, backup)
        self.store.import_records(other, backup)
        imported = {r['id']: r for r in self.store.state(other)['records']}
        self.assertEqual(len(imported), 2)
        self.assertEqual(imported[average['id']]['reaction'], 'okay')
        self.assertEqual(imported[undecided['id']]['reaction'], 'neutral')
        self.assertEqual(self.store.state(self.owner), before)

    def test_average_has_no_like_bonus_and_does_not_hide_its_actual_taste(self):
        self.save(product='一般', reaction='okay', tasted_flavors=['微焦', '微苦'])
        self.save(product='喜欢', reaction='like')
        self.save(product='不喜欢', reaction='dislike')
        products = self.recommendations(flavors=[], roasts=[])
        self.assertEqual([p['product'] for p in products], ['喜欢', '一般'])
        average = products[1]
        self.assertEqual(average['score'], 0)
        self.assertEqual(average['feedback']['reaction'], 'okay')
        self.assertEqual(average['feedback']['tasted_flavors'], ['微焦', '微苦'])
        self.assertTrue(any('上次评价一般' in reason for reason in average['reasons']))
        self.assertFalse(any('喜欢过' in reason for reason in average['reasons']))

    def test_undecided_stays_undecided_and_menu_has_no_personal_feedback(self):
        row = self.save(reaction='neutral', tasted_flavors=['微苦'])
        product = self.recommendations(flavors=[])[0]
        self.assertEqual(product['feedback']['reaction'], 'neutral')
        self.assertTrue(any('还说不准' in reason for reason in product['reasons']))
        menu = self.save(product='尚未喝过', kind='menu', source_note='测试菜单')
        product = next(p for p in self.recommendations() if p['record_id'] == menu['id'])
        self.assertIsNone(product['feedback'])
        self.assertEqual(next(r for r in self.store.state(self.owner)['records'] if r['id'] == row['id'])['reaction'], 'neutral')

    def test_newer_menu_does_not_replace_last_actual_rating_and_taste(self):
        tasting = self.save(reaction='okay', tasted_flavors=['微苦'], observed_on='2020-01-01')
        self.save(kind='menu', source_note='较新的菜单', observed_on='2020-02-01')
        product = self.recommendations()[0]
        self.assertEqual(product['feedback'], {'reaction': 'okay', 'observed_on': tasting['observed_on'], 'tasted_flavors': ['微苦']})

    def test_unlocated_record_is_explained_and_can_be_linked_without_copying(self):
        row = self.save(cafe='测试店（分店待确认）', provider_id='', address='', reaction='okay', tasted_flavors=['微焦'])
        before = self.store.state(self.owner)
        result = search_cafes({'mode':'taste', 'brew':'冰美式'}, before)
        self.assertEqual(result['cafes'], [])
        self.assertEqual(result['unlinked_count'], 1)
        notice = result['unlinked_records'][0]
        self.assertEqual(notice['record_id'], row['id'])
        self.assertEqual(notice['feedback']['reaction'], 'okay')
        self.assertIn('缺少分店地址', notice['issue'])
        self.store.save(self.owner, dict(row, cafe=self.cafe['name'], address=self.cafe['address']))
        after = self.store.state(self.owner)
        linked = search_cafes({'mode':'taste', 'brew':'冰美式'}, after)
        self.assertEqual(linked['unlinked_count'], 0)
        self.assertEqual(linked['cafes'][0]['products'][0]['record_id'], row['id'])
        self.assertEqual(len(after['records']), 1)
        self.assertEqual(after['preferences'], before['preferences'])

    def test_unlinked_summary_respects_brew_category_and_limits_recent_rows(self):
        for i in range(7):
            self.save(product='待补充 %s' % i, provider_id='', address='')
        self.save(product='其他制作方式', brew='手冲', provider_id='', address='')
        result = search_cafes({'mode':'taste', 'brew':'冰美式'}, self.store.state(self.owner))
        self.assertEqual(result['unlinked_count'], 7)
        self.assertEqual(len(result['unlinked_records']), 5)
        self.assertEqual(result['unlinked_records'][0]['product'], '待补充 6')
        state = self.store.state(self.owner)
        state['preferences'] = dict(state['preferences'], coffee_preference='milk')
        self.assertEqual(search_cafes({'mode':'taste', 'brew':'冰美式'}, state)['unlinked_count'], 0)

    def test_missing_cafe_name_is_not_silently_matched_by_provider_id(self):
        row = self.save(cafe='')
        result = search_cafes({'mode':'taste', 'brew':'冰美式'}, self.store.state(self.owner))
        self.assertIn('分店名称', result['unlinked_records'][0]['issue'])
        self.assertEqual(recommend([self.cafe], [row], DEFAULT_PREFS, '冰美式')[0]['products'], [])


if __name__ == '__main__':
    unittest.main()
