"""CS2 Sections 5/7/11: scoped caches, replay without network and budget accounting."""

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml
from pydantic import BaseModel, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.llm.client import BudgetExceeded, CacheMiss, Client


class Answer(BaseModel):
    value: float


MESSAGES = [{"role": "user", "content": "Read the number from this test fixture."}]


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.delenv("LANTERN_LLM_MODE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    value = {"llm": {"mode": "record", "provider": "openai", "models": {"large": "test-model"},
                     "embed": {"hosted": "test-embed", "open": "test-open", "open_revision": "fixture-rev"},
                     "prices": {"test-model": [1, 1], "test-embed": [1, 0]}},
             "budget": {"usd_cap_total": 1, "usd_cap_per_task": 1}}
    path = tmp_path / "params.yaml"
    path.write_text(yaml.safe_dump(value))
    return path, value


def client(config, **updates):
    path, value = config
    value["llm"].update(updates)
    path.write_text(yaml.safe_dump(value))
    return Client(path)


def call(c, **kwargs):
    return c.structured(Answer, MESSAGES, scope="deal_a", task_id="extraction-1", **kwargs)


def provider(c, monkeypatch, value=42):
    calls = []
    def run(*args):
        calls.append(args)
        return {"value": value}, SimpleNamespace(prompt_tokens=100, completion_tokens=20)
    monkeypatch.setattr(c, "_structured", run)
    return calls


def test_import_has_no_config_or_filesystem_side_effects(tmp_path):
    root = str(Path(__file__).resolve().parents[1])
    result = subprocess.run([sys.executable, "-c", "import src.llm.client"], cwd=tmp_path,
                            env={**os.environ, "PYTHONPATH": root}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


def test_record_then_replay_without_key_or_provider(config, monkeypatch):
    c = client(config)
    calls = provider(c, monkeypatch)
    assert call(c).value == 42
    monkeypatch.setenv("LANTERN_LLM_MODE", "replay")
    replay = Client(config[0])
    monkeypatch.setattr(replay, "_structured", lambda *a: pytest.fail("Provider called in replay"))
    before = replay.ledger_path.read_bytes()
    assert call(replay).value == 42
    assert replay.ledger_path.read_bytes() == before
    assert len(calls) == 1
    assert replay.usage_summary()["usd"] == pytest.approx(0.00012)


def test_replay_miss_and_unknown_scope_do_not_connect_or_write(config, monkeypatch):
    c = client(config, mode="replay")
    monkeypatch.setattr(c, "_openai", lambda: pytest.fail("Provider initialized"))
    with pytest.raises(CacheMiss): call(c)
    with pytest.raises(ValueError, match="scope"):
        c.structured(Answer, MESSAGES, scope="unknown", task_id="x")
    assert not c.ledger_path.exists()
    assert not (config[0].parent / "data").exists()


def test_cache_does_not_cross_deals_and_prompt_changes_miss(config, monkeypatch):
    c = client(config)
    provider(c, monkeypatch)
    call(c)
    c = client(config, mode="replay")
    with pytest.raises(CacheMiss):
        c.structured(Answer, MESSAGES, scope="deal_b", task_id="extraction-1")
    with pytest.raises(CacheMiss):
        c.structured(Answer, [{"role": "user", "content": "different input"}], scope="deal_a", task_id="x")
    with pytest.raises(CacheMiss): call(c, max_tokens=10)


def test_live_ignores_recorded_cache_and_does_not_replace_it(config, monkeypatch):
    record = client(config)
    provider(record, monkeypatch)
    call(record)
    live = client(config, mode="live")
    calls = provider(live, monkeypatch, value=99)
    assert call(live).value == 99
    assert len(calls) == 1
    assert call(client(config, mode="replay")).value == 42


def test_corrupt_cache_never_falls_back_to_paid_call(config, monkeypatch):
    c = client(config)
    calls = provider(c, monkeypatch)
    call(c)
    path = next((config[0].parent / "data/llm_cache/deal_a").glob("*.json"))
    path.write_text('{"key": "wrong", "data": {"value": 999}}')
    with pytest.raises(ValueError, match="identity mismatch"): call(c)
    assert len(calls) == 1


@pytest.mark.parametrize("field", ["usd_cap_total", "usd_cap_per_task"])
def test_zero_budget_rejects_before_provider(config, monkeypatch, field):
    config[1]["budget"][field] = 0
    c = client(config)
    calls = provider(c, monkeypatch)
    with pytest.raises(BudgetExceeded): call(c)
    assert calls == []


def test_missing_prices_reject_before_provider(config, monkeypatch):
    c = client(config, prices={})
    calls = provider(c, monkeypatch)
    with pytest.raises(ValueError, match="verified"): call(c)
    assert calls == []


def test_task_budget_accumulates_across_calls(config, monkeypatch):
    config[1]["budget"]["usd_cap_per_task"] = 0.00015
    c = client(config)
    calls = provider(c, monkeypatch)
    call(c, input_token_bound=100, max_tokens=20)
    with pytest.raises(BudgetExceeded): call(c, input_token_bound=100, max_tokens=21)
    assert len(calls) == 1
    assert c.usage_summary(scope="deal_a", task_id="extraction-1")["requests"] == 1


def test_invalid_response_is_charged_but_not_cached(config, monkeypatch):
    c = client(config)
    monkeypatch.setattr(c, "_structured", lambda *a: ({"bad": "schema"}, SimpleNamespace(prompt_tokens=7, completion_tokens=3)))
    with pytest.raises(ValidationError): call(c)
    summary = c.usage_summary()
    assert summary["usd"] == pytest.approx(0.00001)
    assert summary["estimated_requests"] == 0
    assert not (config[0].parent / "data/llm_cache").exists()


def test_network_error_retains_reservation_and_no_prompt_in_ledger(config, monkeypatch):
    c = client(config)
    def fail(*a): raise TimeoutError("SECRET prompt and API key must not be logged")
    monkeypatch.setattr(c, "_structured", fail)
    with pytest.raises(TimeoutError): call(c, input_token_bound=100, max_tokens=20)
    assert c.usage_summary()["usd"] == pytest.approx(0.00012)
    assert c.usage_summary()["estimated_requests"] == 1
    assert "SECRET" not in c.ledger_path.read_text()
    assert MESSAGES[0]["content"] not in c.ledger_path.read_text()


def test_missing_key_is_clear_and_has_no_billed_usage(config):
    c = client(config)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"): call(c)
    assert c.usage_summary()["usd"] == 0


def test_parallel_workers_share_budget_reservations(config, monkeypatch):
    config[1]["budget"]["usd_cap_total"] = 0.00003
    c1 = client(config, mode="live")
    c2 = Client(config[0])
    def run(*a):
        time.sleep(0.02)
        return {"value": 1}, SimpleNamespace(prompt_tokens=10, completion_tokens=10)
    for c in (c1, c2): monkeypatch.setattr(c, "_structured", run)
    def attempt(c):
        try:
            call(c, input_token_bound=10, max_tokens=10)
            return "ok"
        except BudgetExceeded: return "blocked"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, [c1, c2])) == ["blocked", "ok"]
    assert c1.usage_summary()["usd"] == pytest.approx(0.00002)


def test_open_embeddings_record_replay_and_revision_isolation(config, monkeypatch):
    c = client(config)
    count = []
    def encode(texts):
        count.extend(texts)
        return [[1, 2, 3] for text in texts]
    out = c.embed(["alpha", "beta"], "test-open", encode, scope="public", task_id="index")
    assert out.shape == (2, 3)
    assert count == ["alpha", "beta"]
    replay = client(config, mode="replay")
    monkeypatch.setattr(replay, "_open_embeddings", lambda *a: pytest.fail("Weights loaded in replay"))
    assert np.array_equal(out, replay.embed(["alpha", "beta"], "test-open", scope="public", task_id="index"))
    with pytest.raises(CacheMiss):
        replay.embed(["alpha"], "test-open", scope="deal_a", task_id="index")
    config[1]["llm"]["embed"]["open_revision"] = "different-revision"
    with pytest.raises(CacheMiss):
        client(config).embed(["alpha"], "test-open", scope="public", task_id="index")
    assert c.usage_summary()["usd"] == 0


def test_hosted_embeddings_are_cached_validated_and_costed(config, monkeypatch):
    c = client(config)
    calls = []
    def encode(texts, model):
        calls.append(texts)
        return [[0.25, 0.75]], SimpleNamespace(prompt_tokens=4)
    monkeypatch.setattr(c, "_hosted_embeddings", encode)
    a = c.embed(["alpha", "alpha"], scope="public", task_id="embed")
    assert a.shape == (2, 2)
    assert calls == [["alpha"]]
    assert c.usage_summary()["usd"] == pytest.approx(0.000004)
    assert c.usage_summary()["output_tokens"] == 0


@pytest.mark.parametrize("vector", [[[float("nan")]], [[]], [1, 2]])
def test_invalid_embedding_not_cached(config, vector):
    c = client(config)
    with pytest.raises(ValueError, match="finite vector"):
        c.embed(["alpha"], "test-open", lambda texts: vector, scope="public", task_id="index")
    assert not (config[0].parent / "data/embed_cache").exists()


def test_invalid_mode_models_and_images_fail_explicitly(config, monkeypatch):
    monkeypatch.setenv("LANTERN_LLM_MODE", "typo")
    with pytest.raises(ValueError, match="mode"): Client(config[0])
    monkeypatch.delenv("LANTERN_LLM_MODE")
    c = client(config, models={})
    with pytest.raises(ValueError, match="pinned model"): call(c)
    with pytest.raises(ValueError, match="input_token_bound"):
        c.structured(Answer, [{"role": "user", "content": []}], model="test-model", scope="public", task_id="vision")


def transport_client(c, responder):
    from openai import OpenAI
    import httpx2
    c._sdk = OpenAI(api_key="offline-test-key", max_retries=0,
                    http_client=httpx2.Client(transport=httpx2.MockTransport(responder)))


def chat_response(request, content):
    import httpx2
    return httpx2.Response(200, request=request, json={
        "id": "offline-completion", "object": "chat.completion", "created": 0,
        "model": "test-model", "choices": [{"index": 0, "finish_reason": "stop",
        "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}})


def test_real_sdk_and_instructor_use_mock_transport_once(config):
    c = client(config)
    requests = []
    def respond(request):
        payload = json.loads(request.content)
        assert payload["model"] == "test-model"
        assert payload["max_completion_tokens"] == 1024
        assert payload["response_format"]["type"] == "json_schema"
        requests.append(request)
        return chat_response(request, '{"value": 42}')
    transport_client(c, respond)
    assert call(c).value == 42
    assert len(requests) == 1
    assert c.usage_summary()["input_tokens"] == 100
    c._sdk.close()


def test_invalid_sdk_response_has_one_attempt_and_usage_is_retained(config):
    c = client(config)
    requests = []
    def respond(request):
        requests.append(request)
        return chat_response(request, '{"value": "not a number"}')
    transport_client(c, respond)
    with pytest.raises(Exception): call(c)
    assert len(requests) == 1
    assert c.usage_summary()["input_tokens"] == 100
    assert c.usage_summary()["usd"] == pytest.approx(0.00012)
    c._sdk.close()


def test_hosted_embedding_sdk_transport_sorts_by_index(config):
    import httpx2
    c = client(config)
    def respond(request):
        assert request.url.path.endswith('/embeddings')
        return httpx2.Response(200, request=request, json={"object": "list", "model": "test-embed",
            "data": [{"object": "embedding", "index": 0, "embedding": [0.2, 0.8]}],
            "usage": {"prompt_tokens": 4, "total_tokens": 4}})
    transport_client(c, respond)
    result = c.embed(["fixture"], scope="public", task_id="index")
    assert np.allclose(result, [[0.2, 0.8]])
    assert c.usage_summary()["usd"] == pytest.approx(0.000004)
    c._sdk.close()



def test_long_context_rates_use_full_request_usage(config):
    c = client(config, long_context={"test-model": {"above_input_tokens": 1000, "prices": [2, 3]}})
    assert c._usd("test-model", 1000, 10) == pytest.approx(0.00101)
    assert c._usd("test-model", 1001, 10) == pytest.approx(0.002032)


def test_reasoning_setting_is_forwarded_and_changes_cache_identity(config):
    c = client(config, temperature=None, reasoning_effort="none")
    requests = []
    def respond(request):
        payload = json.loads(request.content)
        assert "temperature" not in payload
        assert payload["reasoning_effort"] == "none"
        requests.append(request)
        return chat_response(request, '{"value": 42}')
    transport_client(c, respond)
    assert call(c).value == 42
    c._sdk.close()
    changed = client(config, mode="replay", reasoning_effort="low")
    with pytest.raises(CacheMiss): call(changed)
