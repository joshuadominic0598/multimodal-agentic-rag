"""Shared, persistent request pacing for user-declared provider allowances."""

import math
import re
import threading
from email.utils import parsedate_to_datetime
from time import sleep
from time import time as now

from app.core import store as s

LOCK = threading.RLock()
DEFAULTS = {"gemini": (2, 10000), "groq": (6, 6000)}

class RateLimitError(ValueError):
    pass

def policy(connection):
    provider = connection["provider"]
    if provider not in DEFAULTS:
        return None
    free = connection.get("account_tier") == "free" or connection.get("free_tier")
    rpm, tpm = DEFAULTS[provider] if free else (None, None)
    rpm = connection.get("requests_per_minute") or rpm
    tpm = connection.get("tokens_per_minute") or tpm
    daily = connection.get("requests_per_day")
    if not any((rpm, tpm, daily)):
        return None
    group = connection.get("quota_group", "").strip() or "workspace"
    return {"id": s.digest([provider, group]), "rpm": rpm, "tpm": tpm, "daily": daily}

def check_cancelled(run):
    job = s.get("jobs", run)
    if job and job.get("cancel"):
        raise RateLimitError("Cancelled by user while waiting for the provider allowance.")

def reserve(connection, run, tokens, call_id):
    limits = policy(connection)
    if not limits:
        return None
    if limits["tpm"] and tokens > limits["tpm"]:
        raise RateLimitError(
            "This request exceeds the configured token-per-minute allowance. Reduce context, output tokens or visual inputs, or enter your actual provider allowance in Connections."
        )
    last_notice = -math.inf
    started = now()
    while True:
        check_cancelled(run)
        with LOCK:
            current = now()
            bucket = s.get("rate_buckets", limits["id"]) or {}
            history = [item for item in bucket.get("history", []) if item["time"] > current - 86400]
            if limits["daily"] and len(history) >= limits["daily"]:
                raise RateLimitError(
                    "The configured local daily request allowance is used up. Wait for the rolling 24-hour window to clear or review the actual provider quota. No further request was sent."
                )
            minute = [item for item in history if item["time"] > current - 60]
            ready = bucket.get("cooldown_until", 0)
            if limits["rpm"] and history:
                ready = max(ready, history[-1]["time"] + 60 / limits["rpm"] + 0.1)
                if len(minute) >= limits["rpm"]:
                    ready = max(ready, minute[-limits["rpm"]]["time"] + 60.1)
            if limits["tpm"]:
                used = sum(item["tokens"] for item in minute)
                for item in minute:
                    if used + tokens <= limits["tpm"]:
                        break
                    ready = max(ready, item["time"] + 60.1)
                    used -= item["tokens"]
            delay = max(0, ready - current)
            if delay <= 0:
                history.append({"time": current, "tokens": tokens})
                s.put("rate_buckets", limits["id"], {**bucket, "history": history})
                if current - started >= 1:
                    s.event(
                        run,
                        "provider-pacing",
                        "Provider allowance available; sending the next request",
                        call_id=call_id,
                    )
                s.patch("calls", call_id, pacing_wait_seconds=round(current - started, 2))
                job = s.get("jobs", run)
                if job:
                    s.patch("jobs", run, rate_wait=None)
                return limits
        if current - last_notice >= 2:
            wait = {
                "until": ready,
                "message": f"Waiting {math.ceil(delay)}s before the next {connection['provider']} request",
                "provider": connection["provider"],
            }
            job = s.get("jobs", run)
            if job:
                s.patch("jobs", run, rate_wait=wait)
            s.patch(
                "calls", call_id, status="waiting", pacing_wait_seconds=round(current - started, 2)
            )
            if last_notice == -math.inf:
                s.event(run, "provider-pacing", wait["message"], call_id=call_id)
            last_notice = current
        sleep(min(0.5, delay))

def duration(value):
    try:
        return max(0, float(value))
    except (ValueError, TypeError):
        pass
    if not value:
        return 0
    matches = re.findall(r"([\d.]+)(ms|h|m|s)", str(value))
    if matches:
        return sum(
            float(number) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
            for number, unit in matches
        )
    try:
        return max(0, parsedate_to_datetime(value).timestamp() - now())
    except (ValueError, TypeError, OverflowError):
        return 0

def observe(connection, response):
    limits = policy(connection)
    if not limits:
        return
    headers = response.headers
    delay = duration(headers.get("retry-after"))
    for resource in ("requests", "tokens"):
        if headers.get("x-ratelimit-remaining-" + resource) == "0":
            delay = max(delay, duration(headers.get("x-ratelimit-reset-" + resource)))
    if response.status_code == 429:
        delay = max(delay, 60)
    if response.status_code == 503:
        delay = max(delay, 30)
    if delay:
        with LOCK:
            bucket = s.get("rate_buckets", limits["id"]) or {}
            s.put(
                "rate_buckets",
                limits["id"],
                {**bucket, "cooldown_until": max(bucket.get("cooldown_until", 0), now() + delay)},
            )
