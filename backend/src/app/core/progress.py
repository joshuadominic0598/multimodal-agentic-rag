"""Completed work checkpoints for document processing, independent of elapsed time."""

from app.core import store as s

def report(run, stage, message, percent, *, completed=None, total=None, unit="", waiting=False):
    value = {
        "percent": max(0, min(99, round(percent, 1))),
        "stage": stage,
        "message": message,
        "completed": completed,
        "total": total,
        "unit": unit,
        "waiting": waiting,
        "updated": s.now(),
    }
    with s.LOCK:
        job = s.get("jobs", run)
        if job:
            value["percent"] = max(value["percent"], job.get("progress", {}).get("percent", 0))
            s.patch("jobs", run, progress=value)
    s.event(run, stage, message, progress=value)
    return value
