"""Bounded background execution and restart/cancellation state."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from app.core import store as s
from app.integrations import providers as p

POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="agentic-rag-job")
JOB_LOCK = threading.RLock()

@asynccontextmanager
async def lifespan(app):
    for job in s.rows("jobs"):
        if job["status"] in {"running", "queued"}:
            s.patch(
                "jobs",
                job["id"],
                status="failed",
                error="App restarted before this job completed. Rerun the operation.",
                finished=s.now(),
            )
    for evaluation in s.rows("evaluations"):
        if evaluation.get("status") == "running":
            s.patch(
                "evaluations",
                evaluation["id"],
                status="failed",
                error="App restarted before evaluation completed. Completed cases were preserved.",
            )
    yield
    for job in s.rows("jobs"):
        if job.get("owner_pid") == os.getpid() and job["status"] in {"queued", "running"}:
            s.patch("jobs", job["id"], cancel=True)

def submit(kind, fn, *args, scope=""):
    with JOB_LOCK:
        if scope and any(
            x.get("scope") == scope and x["status"] in {"queued", "running"} for x in s.rows("jobs")
        ):
            raise ValueError("A job is already running for this document. Wait or cancel it first.")
        id = s.uid()
        s.put(
            "jobs",
            id,
            {
                "kind": kind,
                "status": "queued",
                "created": s.now(),
                "scope": scope,
                "cancel": False,
                "owner_pid": os.getpid(),
            },
        )

    def worker():
        s.patch("jobs", id, status="running", started=s.now())
        s.event(id, "start", f"{kind} started")
        try:
            result = fn(*args, id)
            if s.get("jobs", id).get("cancel"):
                raise ValueError("Cancelled by user.")
            s.patch("jobs", id, status="completed", finished=s.now(), result=result, error=None)
            s.event(id, "complete", f"{kind} completed")
        except Exception as exc:
            message = p.safe_error(exc)
            s.patch(
                "jobs",
                id,
                status="cancelled" if s.get("jobs", id).get("cancel") else "failed",
                error=message,
                finished=s.now(),
            )
            s.event(id, "error", message)
            if kind == "evaluation" and s.get("evaluations", id):
                s.patch("evaluations", id, status="failed", error=message)

    POOL.submit(worker)
    return {"job_id": id}

def job(id: str):
    j = s.get("jobs", id, True)
    j["events"] = sorted(
        [e for e in s.rows("events") if e["run_id"] == id], key=lambda x: x["time"]
    )
    return j

def cancel(id: str):
    return s.patch("jobs", id, cancel=True)
