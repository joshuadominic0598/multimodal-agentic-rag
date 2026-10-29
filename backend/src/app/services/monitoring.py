"""Usage summaries and run traces without model execution."""

from app.core import store as s

def monitor():
    calls = s.rows("calls")
    cloud = s.rows("cloud_calls")
    known = [c["cost_usd"] for c in calls + cloud if c.get("cost_usd") is not None]
    return {
        "local_calls": s.rows("local_calls")[:100],
        "cloud_calls": cloud[:300],
        "cloud_summary": {
            "calls": len(cloud),
            "unpriced": sum(c.get("cost_usd") is None for c in cloud),
            "failed": sum(c.get("status") == "failed" for c in cloud),
            "known_cost": sum(c["cost_usd"] for c in cloud if c.get("cost_usd") is not None),
        },
        "jobs": s.rows("jobs")[:100],
        "events": s.rows("events")[:300],
        "calls": calls[:300],
        "answers": s.rows("answers")[:100],
        "summary": {
            "calls": len(calls),
            "input_tokens": sum(c.get("input_tokens") or 0 for c in calls),
            "output_tokens": sum(c.get("output_tokens") or 0 for c in calls),
            "estimated_known_cost": sum(known) if known else None,
            "unpriced_calls": sum(c.get("cost_usd") is None for c in calls + cloud),
            "failed_calls": sum(c.get("status") == "failed" for c in calls),
        },
    }

def trace(run: str):
    return {
        "local_calls": [e for e in s.rows("local_calls") if e["run_id"] == run],
        "cloud_calls": [e for e in s.rows("cloud_calls") if e["run_id"] == run],
        "events": [e for e in s.rows("events") if e["run_id"] == run],
        "calls": [e for e in s.rows("calls") if e["run_id"] == run],
        "answer": s.get("answers", run),
        "job": s.get("jobs", run),
    }
