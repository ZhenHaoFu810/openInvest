"""主 LLM 计费/额度失败 → 回落 DEEPSEEK_*（不回落 = 委员会静默全 HOLD）。

跑：uv run pytest tests/test_llm_billing_fallback.py -q
"""
from __future__ import annotations

from types import SimpleNamespace

import openai
import pytest

import openinvest.capabilities.sdk_agent as sdk_agent_mod
from openinvest.capabilities.sdk_agent import SDKAgent
from openinvest.utils.llm import (
    create_chat_completion,
    get_fallback_llm_config,
    is_billing_error,
)

# Anthropic 额度耗尽时 OpenAI 兼容层返回的原文（platform.claude.com api-credits 文档）
CREDIT_ERR = Exception(
    "Error code: 400 - {'error': {'code': 'invalid_request_error', 'message': "
    "'Your credit balance is too low to access the Anthropic API. Please go to "
    "Plans & Billing to upgrade or purchase credits.', 'type': 'invalid_request_error'}}"
)


def _resp(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=None))],
                           usage=None)


class _Client:
    def __init__(self, raises=None, text="ok"):
        self.calls = []
        self.raises, self.text = raises, text
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        if self.raises:
            raise self.raises
        return _resp(self.text)


@pytest.fixture
def claude_primary(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-ant-primary")
    monkeypatch.setenv("LLM_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-fallback")
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    fb = _Client(text="from-deepseek")
    inits = []
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: inits.append(kw) or fb)
    return fb, inits


@pytest.mark.parametrize("exc,expected", [
    (CREDIT_ERR, True),
    (SimpleNamespace(status_code=402), True),
    (Exception("insufficient_quota"), True),
    (Exception("Error code: 429 - rate limit exceeded"), False),
    (Exception("response_format.type: Input should be 'json_schema'"), False),
    (TimeoutError("read timed out"), False),
])
def test_is_billing_error(exc, expected):
    assert is_billing_error(exc) is expected


def test_fallback_config_only_when_primary_is_not_deepseek(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "sk-ant")
    assert get_fallback_llm_config() == ("sk-ds", "https://api.deepseek.com", "deepseek-v4-flash")
    monkeypatch.setenv("LLM_API_KEY", "")          # 舰队 cron 的置空写法 → 主 LLM 就是 DeepSeek
    assert get_fallback_llm_config() is None
    monkeypatch.delenv("LLM_API_KEY")
    assert get_fallback_llm_config() is None
    monkeypatch.setenv("LLM_API_KEY", "sk-ant")
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    assert get_fallback_llm_config() is None


def test_billing_error_falls_back_with_deepseek_params(claude_primary):
    fb, inits = claude_primary
    primary = _Client(raises=CREDIT_ERR)
    resp, used = create_chat_completion(
        primary, model="claude-sonnet-5-5", messages=[{"role": "user", "content": "hi"}],
        temperature=0.2, response_format={"type": "json_object"},
    )
    assert used == "deepseek-v4-flash" and resp.choices[0].message.content == "from-deepseek"
    assert inits == [{"api_key": "sk-ds-fallback", "base_url": "https://api.deepseek.com"}]
    sent_primary, sent_fb = primary.calls[0], fb.calls[0]
    assert "temperature" not in sent_primary and "response_format" not in sent_primary
    assert sent_fb["model"] == "deepseek-v4-flash" and sent_fb["temperature"] == 0.2
    assert sent_fb["response_format"] == {"type": "json_object"}
    assert sent_fb["extra_body"] == {"thinking": {"type": "disabled"}}


def test_other_errors_do_not_fall_back(claude_primary):
    fb, inits = claude_primary
    with pytest.raises(Exception, match="rate limit"):
        create_chat_completion(_Client(raises=Exception("rate limit exceeded")),
                               model="claude-sonnet-5-5", messages=[], temperature=0.2)
    assert inits == [] and fb.calls == []


def test_no_fallback_configured_reraises(claude_primary, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    with pytest.raises(Exception, match="credit balance"):
        create_chat_completion(_Client(raises=CREDIT_ERR),
                               model="claude-sonnet-5-5", messages=[], temperature=0.2)


def test_sdk_agent_falls_back_and_records_served_model(claude_primary, monkeypatch):
    recorded = []
    monkeypatch.setattr(sdk_agent_mod, "record_llm_call",
                        lambda meta, **kw: recorded.append((meta.model, kw.get("ok"))))
    agent = SDKAgent(system_prompt="t", model="claude-sonnet-5-5", api_key="sk-ant-primary",
                     base_url="https://example.invalid/v1", enable_tools=False)
    agent.client = _Client(raises=CREDIT_ERR)
    assert agent.run("hi") == "from-deepseek"
    assert agent.models_used == {"deepseek-v4-flash"}
    assert recorded == [("deepseek-v4-flash", True)]
