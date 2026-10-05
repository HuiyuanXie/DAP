import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from dap.provider import OpenAIProvider, ProviderError, validate
from dap.simulation import VOTE


class ProviderTests(unittest.TestCase):
    def provider(self, **overrides):
        config = {'OPENAI_API_KEY': 'test-secret', 'MODEL': 'test-model',
                  'BASE_URL': 'https://api.openai.com/v1', 'API_STYLE': 'responses'}
        config.update(overrides)
        with patch('dap.provider.load_config', return_value=config):
            return OpenAIProvider()

    def response(self, decision):
        payload = {'status': 'completed', 'usage': {'total_tokens': 25},
                   'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(decision)}]}]}
        return io.BytesIO(json.dumps(payload).encode())

    def test_optional_usage_is_tolerated(self):
        for usage in (None, [], {'total_tokens': None}, {'total_tokens': -1}):
            with self.subTest(usage=usage):
                provider = self.provider()
                payload = json.loads(self.response({'approve': True, 'explanation': 'OK'}).read())
                payload['usage'] = usage
                with patch('dap.provider.request.urlopen', return_value=io.BytesIO(json.dumps(payload).encode())):
                    result = provider.decide('vote', 'legislator-b', {}, VOTE)
                self.assertTrue(result['approve'])
                self.assertEqual(provider.tokens, 0)

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

    def test_chat_completions_request_and_response(self):
        with patch('dap.provider.load_config', return_value={
                'OPENAI_API_KEY': 'test-secret', 'MODEL': 'deepseek-test',
                'BASE_URL': 'https://gateway.example/v1', 'API_STYLE': 'chat_completions',
                'THINKING': 'off', 'REASONING_FORMAT': 'thinking'}):
            provider = OpenAIProvider()
        envelope = {'choices': [{'finish_reason': 'stop', 'message': {
            'content': json.dumps({'approve': True, 'explanation': 'Agree.'}),
            'reasoning_content': 'This is not parsed or logged.'}}], 'usage': {'total_tokens': 42}}
        with patch('dap.provider.request.urlopen', return_value=io.BytesIO(json.dumps(envelope).encode())) as mock:
            result = provider.decide('vote', 'legislator-b', {}, VOTE)
        req = mock.call_args.args[0]
        body = json.loads(req.data)
        self.assertEqual(req.full_url, 'https://gateway.example/v1/chat/completions')
        self.assertEqual(body['model'], 'deepseek-test')
        self.assertEqual(body['thinking'], {'type': 'disabled'})
        self.assertEqual(body['response_format'], {'type': 'json_object'})
        self.assertIn('JSON Schema', body['messages'][0]['content'])
        self.assertNotIn('test-secret', req.data.decode())
        self.assertNotIn('input', body)
        self.assertNotIn('max_output_tokens', body)
        self.assertTrue(result['approve'])
        self.assertEqual(provider.tokens, 42)

    def test_chat_truncated_output_is_rejected(self):
        provider = self.provider(API_STYLE='chat_completions')
        payload = {'choices': [{'finish_reason': 'length', 'message': {'content': '{}'}}]}
        with patch('dap.provider.request.urlopen', return_value=io.BytesIO(json.dumps(payload).encode())):
            with self.assertRaisesRegex(ProviderError, 'incomplete'):
                provider.decide('vote', 'legislator-b', {}, VOTE)

    def test_complete_endpoint_is_not_duplicated(self):
        provider = self.provider(API_STYLE='chat_completions', BASE_URL='https://gateway.example/v1/chat/completions')
        envelope = {'choices': [{'finish_reason': 'stop', 'message': {
            'content': json.dumps({'approve': True, 'explanation': 'Agree.'})}}]}
        with patch('dap.provider.request.urlopen', return_value=io.BytesIO(json.dumps(envelope).encode())) as mock:
            provider.decide('vote', 'legislator-b', {}, VOTE)
        self.assertEqual(mock.call_args.args[0].full_url, provider.base_url)

    def test_responses_reasoning_switch_is_sent(self):
        provider = self.provider(THINKING='on', REASONING_EFFORT='high', MAX_OUTPUT_TOKENS='8192')
        with patch('dap.provider.request.urlopen', return_value=self.response({'approve': True, 'explanation': 'Agree.'})) as mock:
            provider.decide('vote', 'legislator-b', {}, VOTE)
        body = json.loads(mock.call_args.args[0].data)
        self.assertEqual(body['reasoning'], {'effort': 'high'})
        self.assertEqual(body['max_output_tokens'], 8192)
        self.assertNotIn('thinking', body)

    def test_openai_chat_off_uses_none_and_completion_token_limit(self):
        provider = self.provider(API_STYLE='chat_completions', THINKING='off')
        payload = {'choices': [{'finish_reason': 'stop', 'message': {
            'content': json.dumps({'approve': True, 'explanation': 'Agree.'})}}]}
        with patch('dap.provider.request.urlopen', return_value=io.BytesIO(json.dumps(payload).encode())) as mock:
            provider.decide('vote', 'legislator-b', {}, VOTE)
        body = json.loads(mock.call_args.args[0].data)
        self.assertEqual(body['reasoning_effort'], 'none')
        self.assertEqual(body['max_completion_tokens'], 1800)
        self.assertNotIn('max_tokens', body)
        self.assertNotIn('thinking', body)

    def test_missing_key_is_actionable(self):
        with patch('dap.provider.load_config', return_value={}):
            with self.assertRaisesRegex(ProviderError, '.env'):
                OpenAIProvider()


if __name__ == '__main__':
    unittest.main()
