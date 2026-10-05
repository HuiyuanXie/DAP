import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from dap.provider import OpenAIProvider, ProviderError, validate
from dap.simulation import VOTE


class ProviderTests(unittest.TestCase):
    def provider(self):
        with patch('dap.provider.load_config', return_value={'OPENAI_API_KEY': 'test-secret', 'OPENAI_MODEL': 'test-model'}):
            return OpenAIProvider()

    def response(self, decision):
        payload = {'status': 'completed', 'usage': {'total_tokens': 25},
                   'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(decision)}]}]}
        return io.BytesIO(json.dumps(payload).encode())

    def test_request_uses_strict_schema_and_key_only_in_header(self):
        provider = self.provider()
        with patch('dap.provider.request.urlopen', return_value=self.response({'approve': True, 'explanation': 'Agree.'})) as mock:
            result = provider.decide('vote', 'legislator-b', {'proposal': 'test'}, VOTE)
        req = mock.call_args.args[0]
        body = json.loads(req.data)
        self.assertTrue(body['text']['format']['strict'])
        self.assertFalse(body['store'])
        self.assertNotIn('test-secret', req.data.decode())
        self.assertEqual(req.get_header('Authorization'), 'Bearer test-secret')
        self.assertTrue(result['approve'])
        self.assertEqual(provider.tokens, 25)

    def test_http_error_does_not_echo_provider_body(self):
        provider = self.provider()
        failure = HTTPError('https://example.invalid', 401, 'test-secret', {}, io.BytesIO(b'test-secret'))
        with patch('dap.provider.request.urlopen', side_effect=failure):
            with self.assertRaises(ProviderError) as raised:
                provider.decide('vote', 'legislator-b', {}, VOTE)
        self.assertNotIn('test-secret', str(raised.exception))
        self.assertIn('401', str(raised.exception))

    def test_incomplete_response_does_not_fallback(self):
        provider = self.provider()
        with patch('dap.provider.request.urlopen', return_value=io.BytesIO(b'{"status":"incomplete"}')):
            with self.assertRaises(ProviderError):
                provider.decide('vote', 'legislator-b', {}, VOTE)

    def test_schema_rejects_string_in_place_of_boolean(self):
        with self.assertRaises(ProviderError):
            validate({'approve': 'true', 'explanation': 'Agree.'}, VOTE)

    def test_missing_key_is_actionable(self):
        with patch('dap.provider.load_config', return_value={}):
            with self.assertRaisesRegex(ProviderError, '.env'):
                OpenAIProvider()


if __name__ == '__main__':
    unittest.main()
