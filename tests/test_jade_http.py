import importlib.util
import logging
from pathlib import Path
import sys
import types
import unittest
from unittest import mock


def load_jade_module(requests):
    """Load jade.py with its optional runtime dependencies stubbed out."""
    modules = {
        'cbor': types.ModuleType('cbor'),
        'requests': requests,
        'jadepy': types.ModuleType('jadepy'),
        'jadepy.jade_error': types.ModuleType('jadepy.jade_error'),
        'jadepy.jade_serial': types.ModuleType('jadepy.jade_serial'),
        'jadepy.jade_tcp': types.ModuleType('jadepy.jade_tcp'),
        'jadepy.jade_ble': types.ModuleType('jadepy.jade_ble'),
    }
    modules['jadepy'].__path__ = []
    modules['jadepy.jade_error'].JadeError = type('JadeError', (Exception,), {})
    modules['jadepy.jade_serial'].JadeSerialImpl = object
    modules['jadepy.jade_tcp'].JadeTCPImpl = object
    modules['jadepy.jade_ble'].JadeBleImpl = object

    path = Path(__file__).parents[1] / 'jadepy' / 'jade.py'
    spec = importlib.util.spec_from_file_location('jadepy.jade', path)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


class HttpRequestTests(unittest.TestCase):
    def setUp(self):
        self.requests = types.ModuleType('requests')
        self.response = mock.Mock(
            status_code=200,
            headers={},
        )
        self.response.iter_content.return_value = [b'{"ok": true}']
        self.requests.get = mock.Mock(return_value=self.response)
        self.requests.post = mock.Mock(return_value=self.response)
        self.jade = load_jade_module(self.requests)

    def test_rejects_non_https_and_credentialed_urls(self):
        invalid_urls = [
            ['http://pinserver.example'],
            ['https://user:password@pinserver.example'],
            ['http://example.onion'],
        ]
        for urls in invalid_urls:
            with self.subTest(urls=urls), self.assertRaises(ValueError):
                self.jade._get_https_url(urls)

    def test_request_is_bounded_and_does_not_follow_redirects(self):
        result = self.jade._http_request({
            'urls': ['http://example.onion', 'https://pinserver.example/api'],
            'method': 'POST',
            'accept': 'json',
            'data': {'secret': 'do-not-log'},
        })

        self.assertEqual(result, {'body': {'ok': True}})
        _, kwargs = self.requests.post.call_args
        self.assertEqual(kwargs['timeout'], self.jade.HTTP_REQUEST_TIMEOUT)
        self.assertFalse(kwargs['allow_redirects'])
        self.assertTrue(kwargs['stream'])

    def test_sensitive_bodies_are_not_logged(self):
        params = {
            'urls': ['https://pinserver.example/api'],
            'method': 'POST',
            'accept': 'json',
            'data': {'secret': 'request-secret'},
        }
        self.response.text = 'response-secret'

        with self.assertLogs('jade', logging.DEBUG) as logs:
            self.jade._http_request(params)

        output = '\n'.join(logs.output)
        self.assertNotIn('request-secret', output)
        self.assertNotIn('response-secret', output)

    def test_rejects_oversized_response(self):
        self.response.headers = {
            'Content-Length': str(self.jade.HTTP_RESPONSE_MAX_BYTES + 1),
        }
        with self.assertRaisesRegex(ValueError, 'too large'):
            self.jade._http_request({
                'urls': ['https://pinserver.example/api'],
                'method': 'GET',
                'accept': 'json',
            })

    def test_stops_reading_an_oversized_stream(self):
        chunk = b'x' * (self.jade.HTTP_RESPONSE_MAX_BYTES // 2 + 1)
        self.response.iter_content.return_value = [chunk, chunk, b'not-read']
        with self.assertRaisesRegex(ValueError, 'too large'):
            self.jade._http_request({
                'urls': ['https://pinserver.example/api'],
                'method': 'GET',
                'accept': 'json',
            })


if __name__ == '__main__':
    unittest.main()
