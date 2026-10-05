"""Provider configuration from .env, with environment overrides and OpenAI defaults."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = 'https://api.openai.com/v1'
DEFAULT_MODEL = 'gpt-4o-mini'
DEFAULT_API_STYLE = 'responses'
ENV_KEYS = ('API_KEY', 'OPENAI_API_KEY', 'MODEL', 'OPENAI_MODEL', 'BASE_URL',
            'OPENAI_BASE_URL', 'API_STYLE', 'THINKING', 'REASONING_FORMAT',
            'REASONING_EFFORT', 'THINKING_OFF_SUPPORTED', 'MAX_OUTPUT_TOKENS')


def load_config(path=None):
    config = {}
    path = Path(path or ROOT / '.env')
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            name, value = line.split('=', 1)
            config[name.strip()] = value.strip().strip('"\'')
    # An environment override also takes precedence over its file-level alias.
    for canonical, legacy in (('API_KEY', 'OPENAI_API_KEY'), ('MODEL', 'OPENAI_MODEL'),
                              ('BASE_URL', 'OPENAI_BASE_URL')):
        if canonical in os.environ or legacy in os.environ:
            config.pop(canonical, None)
            config.pop(legacy, None)
    for name in ENV_KEYS:
        if name in os.environ:
            config[name] = os.environ[name]
    return config


@dataclass(frozen=True)
class ProviderConfig:
    api_key: str = field(repr=False)
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    api_style: str = DEFAULT_API_STYLE
    thinking: str = 'default'
    reasoning_format: str = 'auto'
    reasoning_effort: str = ''
    thinking_off_supported: bool = True
    max_output_tokens: int = 1800

    @classmethod
    def from_mapping(cls, config, model=None):
        key = config.get('API_KEY') or config.get('OPENAI_API_KEY') or ''
        if not key or key.startswith('your-'):
            raise ValueError('Add API_KEY or OPENAI_API_KEY to the project .env file first.')
        selected_model = model or config.get('MODEL') or config.get('OPENAI_MODEL') or DEFAULT_MODEL
        base = (config.get('BASE_URL') or config.get('OPENAI_BASE_URL') or DEFAULT_BASE_URL).rstrip('/')
        parsed = urlsplit(base)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('BASE_URL must be an HTTPS API root or endpoint without credentials, query, or fragment.')
        style = config.get('API_STYLE') or DEFAULT_API_STYLE
        if style not in ('chat_completions', 'responses'):
            raise ValueError('API_STYLE must be chat_completions or responses.')
        for suffix, expected in (('/chat/completions', 'chat_completions'), ('/responses', 'responses')):
            if base.endswith(suffix) and style != expected:
                raise ValueError('The full BASE_URL endpoint conflicts with API_STYLE.')
        raw = config.get('THINKING', 'default').strip().lower()
        aliases = {'on': 'enabled', 'true': 'enabled', 'off': 'disabled',
                   'false': 'disabled', '': 'default'}
        thinking = aliases.get(raw, raw)
        if thinking not in ('default', 'enabled', 'disabled'):
            raise ValueError('THINKING must be on, off, or default (enabled/disabled also work).')
        reasoning_format = config.get('REASONING_FORMAT') or 'auto'
        if reasoning_format not in ('auto', 'thinking', 'reasoning', 'reasoning_effort', 'always_on'):
            raise ValueError('REASONING_FORMAT must be auto, thinking, reasoning, reasoning_effort, or always_on.')
        resolved = ('reasoning' if style == 'responses' else 'reasoning_effort') if reasoning_format == 'auto' else reasoning_format
        if style == 'responses' and resolved in ('thinking', 'reasoning_effort'):
            raise ValueError('Responses requests use REASONING_FORMAT=reasoning or auto.')
        if style == 'chat_completions' and resolved == 'reasoning':
            raise ValueError('Chat requests use REASONING_FORMAT=thinking, reasoning_effort, or auto.')
        effort = config.get('REASONING_EFFORT', '').strip().lower()
        if effort not in ('', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'):
            raise ValueError('Invalid REASONING_EFFORT; use a positive effort supported by your model.')
        off = config.get('THINKING_OFF_SUPPORTED', 'true').strip().lower()
        if off not in ('true', 'false'):
            raise ValueError('THINKING_OFF_SUPPORTED must be true or false.')
        try:
            budget = int(config.get('MAX_OUTPUT_TOKENS', '1800'))
        except (ValueError, TypeError):
            raise ValueError('MAX_OUTPUT_TOKENS must be an integer.') from None
        if not 1 <= budget <= 65536:
            raise ValueError('MAX_OUTPUT_TOKENS must be between 1 and 65536.')
        result = cls(api_key=key, model=selected_model, base_url=base, api_style=style,
                     thinking=thinking, reasoning_format=reasoning_format, reasoning_effort=effort,
                     thinking_off_supported=off == 'true', max_output_tokens=budget)
        result.reasoning_parameters()  # Fail invalid off requests before sending credentials.
        return result

    @property
    def resolved_reasoning_format(self):
        if self.reasoning_format == 'auto':
            return 'reasoning' if self.api_style == 'responses' else 'reasoning_effort'
        return self.reasoning_format

    def reasoning_parameters(self):
        if self.thinking == 'default':
            return {}
        format_ = self.resolved_reasoning_format
        if self.thinking == 'disabled' and (not self.thinking_off_supported or format_ == 'always_on'):
            raise ValueError('This model configuration does not support turning thinking off. '
                             'Use THINKING=default/on or select a switchable model; reduced effort is not off.')
        if format_ == 'always_on':
            if self.reasoning_effort:
                raise ValueError('always_on has no reasoning API controls; remove REASONING_EFFORT.')
            return {}
        if format_ == 'thinking':
            result = {'thinking': {'type': self.thinking}}
            if self.thinking == 'enabled' and self.reasoning_effort:
                result['reasoning_effort'] = self.reasoning_effort
            return result
        effort = 'none' if self.thinking == 'disabled' else self.reasoning_effort or 'low'
        return {'reasoning': {'effort': effort}} if format_ == 'reasoning' else {'reasoning_effort': effort}

    @property
    def chat_token_limit_field(self):
        return 'max_tokens' if self.resolved_reasoning_format in ('thinking', 'always_on') else 'max_completion_tokens'

    @property
    def endpoint(self):
        suffix = '/chat/completions' if self.api_style == 'chat_completions' else '/responses'
        return self.base_url if self.base_url.endswith(suffix) else self.base_url + suffix
