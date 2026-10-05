import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dap.config import ProviderConfig, load_config


class ConfigTests(unittest.TestCase):
    def test_defaults_are_official_openai(self):
        config = ProviderConfig.from_mapping({'OPENAI_API_KEY': 'test-key'})
        self.assertEqual(config.base_url, 'https://api.openai.com/v1')
        self.assertEqual(config.endpoint, 'https://api.openai.com/v1/responses')
        self.assertEqual(config.model, 'gpt-4o-mini')
        self.assertEqual(config.thinking, 'default')
        self.assertNotIn('test-key', repr(config))

    def test_gateway_is_selected_entirely_by_configuration(self):
        config = ProviderConfig.from_mapping({'API_KEY': 'test-key',
            'BASE_URL': 'https://yeysai.com/v1/', 'MODEL': 'deepseek-v4.1-flash',
            'API_STYLE': 'chat_completions', 'REASONING_FORMAT': 'thinking', 'THINKING': 'off'})
        self.assertEqual(config.endpoint, 'https://yeysai.com/v1/chat/completions')
        self.assertEqual(config.thinking, 'disabled')

    def test_reasoning_formats_on_and_off(self):
        cases = [
            ('responses', 'auto', 'on', {'reasoning': {'effort': 'high'}}),
            ('responses', 'auto', 'off', {'reasoning': {'effort': 'none'}}),
            ('chat_completions', 'auto', 'on', {'reasoning_effort': 'high'}),
            ('chat_completions', 'auto', 'off', {'reasoning_effort': 'none'}),
            ('chat_completions', 'thinking', 'on', {'thinking': {'type': 'enabled'}, 'reasoning_effort': 'high'}),
            ('chat_completions', 'thinking', 'off', {'thinking': {'type': 'disabled'}}),
        ]
        for style, format_, mode, expected in cases:
            with self.subTest(style=style, format=format_, mode=mode):
                config = ProviderConfig.from_mapping({'API_KEY': 'test', 'API_STYLE': style,
                    'REASONING_FORMAT': format_, 'THINKING': mode, 'REASONING_EFFORT': 'high'})
                self.assertEqual(config.reasoning_parameters(), expected)

    def test_default_does_not_guess_from_model_name(self):
        for model in ('deepseek-r1', 'deepseek-v4.1-flash', 'gpt-5', 'gpt-6-astra'):
            config = ProviderConfig.from_mapping({'API_KEY': 'test', 'MODEL': model})
            self.assertEqual(config.reasoning_parameters(), {})

    def test_unsupported_off_is_rejected_before_call(self):
        with self.assertRaisesRegex(ValueError, 'does not support'):
            ProviderConfig.from_mapping({'API_KEY': 'test', 'THINKING': 'off',
                                        'THINKING_OFF_SUPPORTED': 'false'})
        with self.assertRaisesRegex(ValueError, 'does not support'):
            ProviderConfig.from_mapping({'API_KEY': 'test', 'THINKING': 'off',
                                        'REASONING_FORMAT': 'always_on'})

    def test_always_on_does_not_send_unsupported_parameters(self):
        config = ProviderConfig.from_mapping({'API_KEY': 'test', 'THINKING': 'on',
                                             'REASONING_FORMAT': 'always_on'})
        self.assertEqual(config.reasoning_parameters(), {})

    def test_token_budget_and_field_are_configurable(self):
        config = ProviderConfig.from_mapping({'API_KEY': 'test', 'MAX_OUTPUT_TOKENS': '8192',
                                             'API_STYLE': 'chat_completions'})
        self.assertEqual(config.max_output_tokens, 8192)
        self.assertEqual(config.chat_token_limit_field, 'max_completion_tokens')
        with self.assertRaisesRegex(ValueError, 'MAX_OUTPUT_TOKENS'):
            ProviderConfig.from_mapping({'API_KEY': 'test', 'MAX_OUTPUT_TOKENS': 'invalid'})

    def test_legacy_aliases_and_model_override(self):
        config = ProviderConfig.from_mapping({'OPENAI_API_KEY': 'test-key',
            'OPENAI_BASE_URL': 'https://gateway.example/v1', 'OPENAI_MODEL': 'from-config'},
            model='from-cli')
        self.assertEqual(config.base_url, 'https://gateway.example/v1')
        self.assertEqual(config.model, 'from-cli')

    def test_file_values_and_environment_override_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('# Settings\nAPI_KEY="file-key"\nBASE_URL=https://gateway.example/v1\nMODEL=file-model\nAPI_STYLE=chat_completions\n')
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'environment-key',
                                         'OPENAI_BASE_URL': 'https://api.openai.com/v1',
                                         'OPENAI_MODEL': 'environment-model',
                                         'API_STYLE': 'responses'}, clear=True):
                config = ProviderConfig.from_mapping(load_config(path))
        self.assertEqual(config.api_key, 'environment-key')
        self.assertEqual(config.model, 'environment-model')
        self.assertEqual(config.endpoint, 'https://api.openai.com/v1/responses')

    def test_complete_url_is_not_duplicated(self):
        config = ProviderConfig.from_mapping({'OPENAI_API_KEY': 'test-key',
            'BASE_URL': 'https://gateway.example/v1/chat/completions/',
            'API_STYLE': 'chat_completions'})
        self.assertEqual(config.endpoint, 'https://gateway.example/v1/chat/completions')

    def test_conflicting_protocol_is_reported_locally(self):
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            ProviderConfig.from_mapping({'OPENAI_API_KEY': 'test-key',
                'BASE_URL': 'https://gateway.example/v1/chat/completions', 'API_STYLE': 'responses'})

    def test_invalid_url_is_rejected_without_echoing_credentials(self):
        for base in ('http://gateway.example/v1', 'https://user:secret@gateway.example/v1',
                     'https://gateway.example/v1?key=secret'):
            with self.assertRaises(ValueError) as caught:
                ProviderConfig.from_mapping({'OPENAI_API_KEY': 'test-key', 'BASE_URL': base})
            self.assertNotIn('secret', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
