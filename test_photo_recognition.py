import base64
import io
import json
import os
import unittest
import urllib.error
from unittest.mock import patch

from web_core import AppError, extract_photo, photo_model_request


IMAGE = 'data:image/jpeg;base64,' + base64.b64encode(b'\xff\xd8\xfftest-image').decode()
ENV = {'VISION_ENDPOINT': 'https://vision.example/chat/completions',
       'VISION_API_KEY': 'test-private-key', 'VISION_MODEL': 'test-image-model'}


def response(items, **choice):
    return {'choices': [dict({'message': {'content': json.dumps({'items': items})}}, **choice)]}


class PhotoRecognitionTests(unittest.TestCase):
    def test_auth_quota_and_model_errors_are_actionable_and_never_echo_provider_body(self):
        for code, hint in [(401, '密钥'), (403, '权限'), (402, '额度'), (404, '接口'), (429, '额度'), (400, '图片'), (500, '暂时')]:
            error = urllib.error.HTTPError(ENV['VISION_ENDPOINT'], code, 'private-provider-message', {}, io.BytesIO(b'test-private-key'))
            with self.subTest(code=code), patch('urllib.request.urlopen', side_effect=error), self.assertRaises(AppError) as ctx:
                photo_model_request(ENV['VISION_ENDPOINT'], {}, ENV['VISION_API_KEY'])
            self.assertIn(hint, str(ctx.exception))
            self.assertEqual(ctx.exception.status, 502)
            self.assertNotIn('private', str(ctx.exception))
            self.assertNotIn('vision.example', str(ctx.exception))

    def test_slow_vision_uses_bounded_timeout_without_automatic_billable_retry(self):
        with patch('urllib.request.urlopen', side_effect=TimeoutError('private-error')) as call, self.assertRaises(AppError) as ctx:
            photo_model_request(ENV['VISION_ENDPOINT'], {}, ENV['VISION_API_KEY'])
        self.assertIn('超时', str(ctx.exception))
        call.assert_called_once()
        self.assertEqual(call.call_args.kwargs['timeout'], 45)

    def test_invalid_images_and_non_https_configuration_never_send_a_request(self):
        for endpoint in ['http://vision.example/api', 'https://user:pass@vision.example/api', 'https:///api']:
            with self.subTest(endpoint=endpoint), patch.dict(os.environ, dict(ENV, VISION_ENDPOINT=endpoint), clear=True), patch('web_core.photo_model_request') as call, self.assertRaises(AppError):
                extract_photo({'image': IMAGE})
            call.assert_not_called()
        for image in ['', 'file:///photo.jpg', 'data:image/jpeg;base64,bm90LWEtcGhvdG8=']:
            with self.subTest(image=image), patch.dict(os.environ, ENV, clear=True), patch('web_core.photo_model_request') as call, self.assertRaises(AppError):
                extract_photo({'image': image})
            call.assert_not_called()

    def test_products_are_facts_only_and_unknowns_remain_unknown(self):
        rows = [{'product': '测试产品', 'roast': ['浅烘'], 'brew': {'guess': '手冲'},
                 'id': 'untrusted', 'owner': 'other', 'reaction': 'like', 'tasted_flavors': ['不可当作亲历'],
                 'cafe': '模型猜测的店', 'label_flavors': ['柑橘']}, {}]
        with patch.dict(os.environ, ENV, clear=True), patch('web_core.photo_model_request', return_value=response(rows)):
            result = extract_photo({'image': IMAGE})
        self.assertEqual(len(result['items']), 1)
        row = result['items'][0]
        self.assertEqual((row['roast'], row['brew'], row['bean']), ('未知', '', ''))
        self.assertEqual(row['label_flavors'], ['柑橘'])
        for field in ['id', 'owner', 'reaction', 'tasted_flavors', 'cafe']:
            self.assertNotIn(field, row)

    def test_truncated_model_output_is_not_mistaken_for_a_complete_menu(self):
        with patch.dict(os.environ, ENV, clear=True), patch('web_core.photo_model_request', return_value=response([{'product': '半张豆单'}], finish_reason='length')), self.assertRaises(AppError) as ctx:
            extract_photo({'image': IMAGE})
        self.assertIn('分成几张', str(ctx.exception))

    def test_empty_output_and_twenty_item_limit_are_visible_to_user(self):
        for rows, expected_count, hint in [([], 0, '没有识别出'), ([{'product': '测试' + str(i)} for i in range(21)], 20, '超过 20')]:
            with self.subTest(count=len(rows)), patch.dict(os.environ, ENV, clear=True), patch('web_core.photo_model_request', return_value=response(rows)):
                result = extract_photo({'image': IMAGE})
            self.assertEqual(len(result['items']), expected_count)
            self.assertIn(hint, result['uncertain'])


if __name__ == '__main__':
    unittest.main()
