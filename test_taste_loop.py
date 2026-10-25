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


if __name__ == '__main__':
    unittest.main()
