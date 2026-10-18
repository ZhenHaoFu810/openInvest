"""Claude 4.7+（含 Sonnet 5.5）temperature<1 直接 400，Anthropic 兼容层收
response_format=json_object 也 400 → 委员会静默全 HOLD。

守：claude-* 模型的请求里不带 temperature / response_format；DeepSeek 照旧带。
跑：uv run pytest tests/test_claude_sampling_params.py -q
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import openinvest.capabilities.sdk_agent as sdk_agent_mod
from openinvest.capabilities.sdk_agent import SDKAgent


@pytest.mark.parametrize("model,expect_temp", [
    ("claude-sonnet-5-5", False),
    ("deepseek-v4-flash", True),
])
def test_temperature_and_json_mode_only_sent_to_non_claude(monkeypatch, model, expect_temp):
    monkeypatch.setattr(sdk_agent_mod, "record_llm_call", lambda *a, **k: None)
    agent = SDKAgent(system_prompt="t", model=model, api_key="sk-fake",
                     base_url="https://example.invalid/v1", enable_tools=False,
                     response_format={"type": "json_object"})
    sent = {}

    def fake_create(**kwargs):
        sent.update(kwargs)
        msg = SimpleNamespace(content="ok", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None)

    monkeypatch.setattr(agent.client.chat.completions, "create", fake_create)
    assert agent.run("hi") == "ok"
    assert ("temperature" in sent) is expect_temp
    assert ("response_format" in sent) is expect_temp
