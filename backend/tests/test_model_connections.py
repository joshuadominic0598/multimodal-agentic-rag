import json

import httpx
import pytest

from app.core import store as s
from app.core.schemas import Connection
from app.integrations import providers as p
from app.integrations.model_catalog import defaults

def cfg(provider, **extra):
    return {
        "id": "adapter-test",
        "key": "secret-unit-key",
        **Connection(**{**defaults(provider), **extra}).model_dump(),
    }

def transport(monkeypatch, handler):
    real = httpx.Client
    monkeypatch.setattr(
        p.httpx, "Client", lambda **kwargs: real(transport=httpx.MockTransport(handler))
    )

@pytest.mark.parametrize("provider", ["gemini", "openai", "groq"])
@pytest.mark.parametrize("tier", ["free", "paid"])
def test_cloud_tiers_keep_keys_private_and_do_not_invent_prices(provider, tier):
    c = p.save(
        Connection(
            **{**defaults(provider), "api_key": "unit-private-key", "account_tier": tier}
        ).model_dump()
    )
    assert c["account_tier"] == tier and c["free_tier"] == (tier == "free")
    assert c["input_price"] is None and c["output_price"] is None
    assert c["has_key"] and "unit-private-key" not in json.dumps(c)
    assert p.resolve(c["id"])["key"] == "unit-private-key"

def test_ollama_default_is_keyless_idempotent_and_does_not_replace_active_connection():
    active = s.get("settings", "main")["active_connection"]
    p.bootstrap()
    p.bootstrap()
    profiles = [x for x in s.rows("connections") if x["provider"] == "ollama"]
    assert len(profiles) == 1 and profiles[0]["model"] == "qwen3:8b"
    assert not profiles[0]["secret"] and not p.public(profiles[0])["has_key"]
    assert s.get("settings", "main")["active_connection"] == active

@pytest.mark.parametrize(
    "url",
    [
        "https://api.ollama.com",
        "http://169.254.169.254",
        "http://localhost:11434/api/chat",
        "http://user:password@localhost:11434",
        "http://127.0.0.1:11434?redirect=evil",
    ],
)
def test_ollama_endpoint_is_private(url):
    with pytest.raises(ValueError, match="local Ollama endpoint"):
        p.save(Connection(**{**defaults("ollama"), "endpoint": url}).model_dump())

def test_keys_cannot_be_reused_across_providers_or_forwarded_to_ollama():
    c = p.save(Connection(**{**defaults("gemini"), "api_key": "gemini-secret"}).model_dump())
    with pytest.raises(ValueError, match="key for this provider"):
        p.save(Connection(**defaults("groq")).model_dump(), c["id"])
    with pytest.raises(ValueError, match="does not need an API key"):
        p.save(Connection(**{**defaults("ollama"), "api_key": "bad-forward"}).model_dump())
    local = p.save(Connection(**defaults("ollama")).model_dump(), c["id"])
    assert not local["has_key"] and p.auth_headers(p.resolve(local["id"])) == {}

def test_groq_native_chat_json_slash_model_and_usage(monkeypatch):
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append(body)
        assert str(req.url) == "https://api.groq.com/openai/v1/chat/completions"
        assert req.headers["authorization"] == "Bearer secret-unit-key"
        assert body["model"] == "openai/gpt-oss-20b" and body["response_format"] == {
            "type": "json_object"
        }
        assert body["max_completion_tokens"] == 1500 and body["stream"] is False
        assert body["messages"] == [
            {"role": "system", "content": "system JSON"},
            {"role": "user", "content": "Return JSON."},
        ]
        assert "store" not in body and "instructions" not in body
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"ready":true}', "reasoning": "private thinking"}}
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 25},
            },
            headers={"x-ratelimit-remaining-tokens": "7000"},
        )

    transport(monkeypatch, handler)
    c = cfg("groq", input_price=1, output_price=2)
    assert p.generate(
        c, p.Budget("groq-native"), "system JSON", "Return JSON.", json_mode=True
    ) == {"ready": True}
    rec = next(x for x in s.rows("calls") if x["run_id"] == "groq-native")
    assert (
        rec["cost_usd"] == pytest.approx(0.00015)
        and rec["rate_limits"]["x-ratelimit-remaining-tokens"] == "7000"
    )
    assert "private thinking" not in json.dumps(rec) and "secret-unit-key" not in json.dumps(rec)

def test_ollama_native_chat_validates_local_model_and_counts_zero_api_fees(monkeypatch):
    paths = []

    def handler(req):
        assert "authorization" not in req.headers and "x-goog-api-key" not in req.headers
        assert req.url.host == "127.0.0.1"
        body = json.loads(req.content)
        paths.append(req.url.path)
        if req.url.path == "/api/show":
            return httpx.Response(
                200,
                json={
                    "capabilities": ["completion", "thinking"],
                    "model_info": {"qwen3.context_length": 40960},
                },
            )
        assert req.url.path == "/api/chat" and body["model"] == "qwen3:8b"
        assert body["think"] is False and body["format"] == "json" and body["stream"] is False
        assert body["options"] == {"num_ctx": 16384, "num_predict": 1500}
        return httpx.Response(
            200,
            json={
                "message": {"content": '{"ready":true}', "thinking": "private thinking"},
                "prompt_eval_count": 40,
                "eval_count": 8,
                "total_duration": 500,
            },
        )

    transport(monkeypatch, handler)
    assert p.generate(
        cfg("ollama"), p.Budget("ollama-native", 2, 0), "JSON", "Return JSON.", json_mode=True
    ) == {"ready": True}
    assert paths == ["/api/show", "/api/chat"]
    rec = next(x for x in s.rows("calls") if x["run_id"] == "ollama-native")
    assert rec["input_tokens"] == 40 and rec["output_tokens"] == 8 and rec["cost_usd"] == 0
    assert rec["api_fees_only"] and rec["price_status"] == "local API fees only"
    assert "private thinking" not in json.dumps(rec)

@pytest.mark.parametrize(
    "info,message",
    [
        ({"remote_host": "https://ollama.com", "capabilities": ["completion"]}, "Cloud-backed"),
        ({"remote_model": "remote", "capabilities": ["completion"]}, "Cloud-backed"),
        ({"capabilities": ["embedding"]}, "embedding-only"),
        (
            {"capabilities": ["completion"], "model_info": {"qwen3.context_length": 4096}},
            "declares a",
        ),
    ],
)
def test_ollama_rejects_incompatible_models_before_generation(monkeypatch, info, message):
    paths = []

    def handler(req):
        paths.append(req.url.path)
        return httpx.Response(200, json=info)

    transport(monkeypatch, handler)
    with pytest.raises(ValueError, match=message):
        p.generate(cfg("ollama"), p.Budget("incompatible"), "system", "hello")
    assert paths == ["/api/show"]

def test_local_input_token_reserve_rejects_without_truncation(monkeypatch):
    paths = []

    def handler(req):
        paths.append(req.url.path)
        return httpx.Response(200, json={"capabilities": ["completion"]})

    transport(monkeypatch, handler)
    with pytest.raises(ValueError, match="silently truncated"):
        p.generate(cfg("ollama"), p.Budget("token-reserve"), "system", "日" * 6000)
    assert paths == ["/api/show"]

@pytest.mark.parametrize("provider", ["groq", "ollama"])
def test_unsupported_image_generation_and_embeddings_never_make_network_calls(
    monkeypatch, provider
):
    def forbidden(*args, **kwargs):
        pytest.fail("Unsupported request reached the network")

    monkeypatch.setattr(p.httpx, "Client", forbidden)
    with pytest.raises(ValueError, match="Image generation is not supported"):
        p.generate(cfg(provider), p.Budget("image"), "system", "draw", image_output=True)
    with pytest.raises(ValueError, match="separate embedding engine"):
        p.embed(cfg(provider), p.Budget("embed"), ["source"])

def test_ollama_inventory_filters_cloud_and_separates_embedding_models(monkeypatch):
    def handler(req):
        assert req.url.path == "/api/tags" and "authorization" not in req.headers
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "qwen3:8b", "capabilities": ["completion", "thinking"]},
                    {"name": "embeddinggemma:latest", "capabilities": ["embedding"]},
                    {"name": "remote:cloud"},
                    {"name": "remote-alias", "remote_host": "https://ollama.com"},
                ]
            },
        )

    transport(monkeypatch, handler)
    result = p.list_models(cfg("ollama"))
    assert [x["id"] for x in result["models"]] == ["embeddinggemma:latest", "qwen3:8b"]
    assert result["models"][0]["selectable"] is False and result["models"][1]["selectable"] is True

def test_gemini_model_inventory_paginates_and_marks_embedding_only(monkeypatch):
    seen = []

    def handler(req):
        seen.append(req)
        assert req.headers["x-goog-api-key"] == "secret-unit-key"
        if len(seen) == 1:
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/gemini-a",
                            "supportedGenerationMethods": ["generateContent"],
                        }
                    ],
                    "nextPageToken": "next-page",
                },
            )
        assert req.url.params["pageToken"] == "next-page"
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "models/embedding-a", "supportedGenerationMethods": ["embedContent"]}
                ]
            },
        )

    transport(monkeypatch, handler)
    result = p.list_models(cfg("gemini"))
    assert len(seen) == 2 and not result["partial"]
    assert result["models"][0]["selectable"] is False

@pytest.mark.parametrize("provider", ["openai", "groq"])
def test_cloud_model_listing_uses_fixed_provider_origin(monkeypatch, provider):
    expected = "api.openai.com" if provider == "openai" else "api.groq.com"

    def handler(req):
        assert req.url.host == expected and req.url.path.endswith("/models")
        return httpx.Response(
            200, json={"data": [{"id": "one"}, {"id": "two"}, {"id": "off", "active": False}]}
        )

    transport(monkeypatch, handler)
    assert [
        x["id"] for x in p.list_models(cfg(provider, endpoint="https://evil.invalid"))["models"]
    ] == ["one", "two"]

def test_model_discovery_reuses_encrypted_key_without_saving_or_echoing(client, monkeypatch):
    saved = client.post(
        "/api/connections", json={**defaults("groq"), "api_key": "discovery-private-key"}
    ).json()
    before = len(s.rows("connections"))

    def listing(c):
        assert c["key"] == "discovery-private-key"
        return {"models": [{"id": "openai/gpt-oss-20b", "selectable": True}], "provider": "groq"}

    monkeypatch.setattr(p, "list_models", listing)
    r = client.post("/api/model-options?connection_id=" + saved["id"], json=defaults("groq"))
    assert r.status_code == 200 and len(s.rows("connections")) == before
    assert "discovery-private-key" not in r.text and "secret" not in r.text
    clone = client.post(
        "/api/connections?copy_from=" + saved["id"],
        json={**defaults("groq"), "model": "openai/gpt-oss-120b"},
    ).json()
    assert (
        clone["id"] != saved["id"]
        and clone["has_key"]
        and p.resolve(clone["id"])["key"] == "discovery-private-key"
    )
    rejected = client.post("/api/connections?copy_from=" + saved["id"], json=defaults("openai"))
    assert rejected.status_code == 422

def test_changed_key_invalidates_capability_verification():
    body = {**defaults("gemini"), "api_key": "first-key"}
    c = p.save(Connection(**body).model_dump())
    s.patch("connections", c["id"], tested_text=True, tested_vision=True)
    changed = p.save(Connection(**{**body, "api_key": "replacement-key"}).model_dump(), c["id"])
    assert not changed["tested_text"] and not changed["tested_vision"]

def test_quota_details_are_recorded_without_credentials(monkeypatch):
    transport(
        monkeypatch,
        lambda req: httpx.Response(
            429,
            json={"error": "secret-unit-key"},
            headers={"retry-after": "30", "x-ratelimit-remaining-tokens": "0"},
        ),
    )
    with pytest.raises(ValueError, match="No retry"):
        p.generate(cfg("groq"), p.Budget("groq-quota"), "system", "hello")
    rec = next(x for x in s.rows("calls") if x["run_id"] == "groq-quota")
    assert (
        rec["status"] == "failed"
        and rec["rate_limits"]["retry-after"] == "30"
        and rec["cost_usd"] is None
    )
    assert "secret-unit-key" not in json.dumps(rec)

def test_local_context_packing_trims_unicode_by_bytes_while_preserving_json():
    from app.agents import context as cm

    payload = {
        "question": "Summarize",
        "context": {"history": [], "memory": []},
        "evidence": [{"chunk_id": "c00001", "text": "日" * 2400}],
    }
    prompt, packet, usage = cm.pack("system", "answer", payload, 12000, 3200)
    assert len(("system" + prompt).encode("utf-8")) <= 3200
    assert (
        packet["evidence"][0]["chunk_id"] == "c00001" and packet["evidence"][0]["excerpt_truncated"]
    )
    assert usage["trimmed"]["evidence_characters"] > 0 and usage["local_input_byte_cap"] == 3200
    assert json.loads(prompt.split("\n", 1)[1]) == packet

def test_local_context_policy_reserves_output_and_template_tokens():
    from app.agents import context as cm
    from app.core.schemas import Question

    question = Question(document_id="d", message="hello", context_chars=12000)
    policy = cm.limits(question, cfg("ollama", max_output=1500, ollama_context_tokens=8192))
    assert policy["local_input_byte_cap"] == 8192 - 1500 - 1024 and policy["context_chars"] == 12000

@pytest.mark.parametrize("provider", ["groq", "ollama"])
def test_vision_enabled_connections_send_actual_image_bytes(monkeypatch, tmp_path, provider):
    from PIL import Image

    asset = tmp_path / "visual.png"
    Image.new("RGB", (10, 10), "red").save(asset)
    seen = []

    def handler(req):
        body = json.loads(req.content)
        if req.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion", "vision"]})
        seen.append(body)
        if provider == "groq":
            assert body["messages"][1]["content"][1]["image_url"]["url"].startswith(
                "data:image/png;base64,"
            )
            return httpx.Response(200, json={"choices": [{"message": {"content": "red"}}]})
        assert body["messages"][1]["images"][0] and "think" not in body
        return httpx.Response(
            200, json={"message": {"content": "red"}, "prompt_eval_count": 2, "eval_count": 1}
        )

    transport(monkeypatch, handler)
    text, _ = p.generate(
        cfg(provider, vision=True),
        p.Budget("vision-" + provider),
        "system",
        "Which color?",
        [asset],
    )
    assert text == "red" and len(seen) == 1

def test_inflight_probe_cannot_verify_a_different_model(client, monkeypatch):
    saved = client.post("/api/connections", json=defaults("ollama")).json()

    def changed_during_request(c, *args, **kwargs):
        s.patch("connections", c["id"], model="qwen3:14b", tested_text=False, tested_vision=False)
        return "Connection ready.", []

    monkeypatch.setattr(p, "generate", changed_during_request)
    response = client.post("/api/connections/" + saved["id"] + "/test")
    assert response.status_code == 422 and "changed during" in response.json()["detail"]
    assert not s.get("connections", saved["id"])["tested_text"]
