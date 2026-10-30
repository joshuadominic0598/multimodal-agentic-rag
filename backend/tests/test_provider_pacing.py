import httpx
import pytest

from app.core import store as s
from app.integrations import rate_limits as limits

def profile(provider="gemini", **extra):
    return {
        "id": s.uid(),
        "provider": provider,
        "account_tier": "free",
        "quota_group": s.uid(),
        **extra,
    }

def reserve(connection, run="pacing-test", tokens=100):
    id = s.uid()
    s.put("calls", id, {"run_id": run, "status": "waiting"})
    limits.reserve(connection, run, tokens, id)
    return s.get("calls", id)

def test_free_profiles_share_spacing_and_persist_allowance(provider_pacing_clock):
    connection = profile()
    started = provider_pacing_clock[0]
    reserve(connection)
    second = reserve({**connection, "id": s.uid()})
    assert provider_pacing_clock[0] - started >= 30
    assert second["pacing_wait_seconds"] >= 30
    bucket = s.get("rate_buckets", limits.policy(connection)["id"])
    assert len(bucket["history"]) == 2
    assert bucket["history"][1]["time"] - bucket["history"][0]["time"] >= 30

def test_token_window_waits_and_rejects_oversized_request(provider_pacing_clock):
    connection = profile("groq", requests_per_minute=60, tokens_per_minute=6000)
    started = provider_pacing_clock[0]
    reserve(connection, tokens=5000)
    reserve(connection, tokens=5000)
    assert provider_pacing_clock[0] - started >= 60
    with pytest.raises(ValueError, match="token-per-minute"):
        reserve(connection, tokens=6001)

def test_retry_after_and_exhausted_headers_delay_future_calls(provider_pacing_clock):
    connection = profile("groq")
    limits.observe(connection, httpx.Response(429, headers={"retry-after": "90"}))
    started = provider_pacing_clock[0]
    reserve(connection)
    assert provider_pacing_clock[0] - started >= 90
    limits.observe(
        connection,
        httpx.Response(
            200, headers={"x-ratelimit-remaining-tokens": "0", "x-ratelimit-reset-tokens": "1m2s"}
        ),
    )
    started = provider_pacing_clock[0]
    reserve(connection)
    assert provider_pacing_clock[0] - started >= 62

def test_cancel_during_wait_sends_nothing(monkeypatch, provider_pacing_clock):
    connection = profile()
    reserve(connection)
    run = s.uid()
    s.put("jobs", run, {"kind": "extraction", "status": "running", "cancel": False})

    def cancel_on_wait(seconds):
        provider_pacing_clock[0] += seconds
        s.patch("jobs", run, cancel=True)

    monkeypatch.setattr(limits, "sleep", cancel_on_wait)
    with pytest.raises(ValueError, match="Cancelled"):
        reserve(connection, run)
    assert len(s.get("rate_buckets", limits.policy(connection)["id"])["history"]) == 1
    s.patch("jobs", run, status="cancelled")

def test_daily_cap_and_separate_account_groups():
    connection = profile(requests_per_day=1)
    reserve(connection)
    with pytest.raises(ValueError, match="daily request allowance"):
        reserve(connection)
    reserve({**connection, "quota_group": s.uid()})
    assert limits.policy({**connection, "account_tier": "paid", "requests_per_day": None}) is None
    assert limits.policy({"provider": "ollama"}) is None
