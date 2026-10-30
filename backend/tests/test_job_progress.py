import threading
import time

import pytest

from app.core import store as s
from app.core.progress import report
from app.ingestion import indexing
from app.services import jobs

def wait_for_job(id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = s.get("jobs", id)
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.01)
    pytest.fail("The background job did not finish")

def test_progress_waits_for_real_work_and_completion():
    ready, release = threading.Event(), threading.Event()

    def worker(run):
        report(run, "extraction", "Read 2/4 pages", 32.5, completed=2, total=4, unit="pages")
        ready.set()
        assert release.wait(5)
        report(run, "saving", "Saving source references", 100)
        assert s.get("jobs", run)["progress"]["percent"] == 99
        return {"count": 4}

    id = jobs.submit("extraction", worker, scope=s.uid())["job_id"]
    try:
        assert ready.wait(5)
        progress = jobs.job(id)["progress"]
        assert progress["percent"] == 32.5
        assert (progress["completed"], progress["total"], progress["unit"]) == (2, 4, "pages")
        report(id, "preparation", "A delayed earlier event", 10)
        assert jobs.job(id)["progress"]["percent"] == 32.5
    finally:
        release.set()
    completed = wait_for_job(id)
    assert completed["progress"]["percent"] == 100
    assert completed["status"] == "completed"

def test_discover_running_job_outside_recent_history(client):
    scope = s.uid()
    id = s.uid()
    s.put(
        "jobs", id, {"scope": scope, "kind": "extraction", "status": "running", "created": s.now()}
    )
    try:
        report(id, "extraction", "Reading page 3/6", 21.6, completed=2, total=6, unit="pages")
        for _ in range(105):
            s.put(
                "jobs",
                s.uid(),
                {
                    "scope": "another-source",
                    "kind": "indexing",
                    "status": "completed",
                    "created": s.now(),
                },
            )
        assert id not in {job["id"] for job in s.rows("jobs")[:100]}
        result = client.get("/api/jobs", params={"scope": scope}).json()["jobs"]
        assert [job["id"] for job in result] == [id]
        assert result[0]["progress"]["percent"] == 21.6
        with pytest.raises(ValueError, match="already running"):
            jobs.submit("indexing", lambda run: None, scope=scope)
    finally:
        s.patch("jobs", id, status="cancelled")

@pytest.mark.parametrize("cancel", [False, True])
def test_failed_or_cancelled_work_never_shows_complete(cancel):
    def worker(run):
        report(
            run, "embedding", "Embedded 16/32 chunks", 57.5, completed=16, total=32, unit="chunks"
        )
        if cancel:
            jobs.cancel(run)
        raise ValueError("The operation stopped")

    id = jobs.submit("indexing", worker, scope=s.uid())["job_id"]
    job = wait_for_job(id)
    assert job["status"] == ("cancelled" if cancel else "failed")
    assert job["progress"]["percent"] == 57.5

def test_index_reports_completed_embedding_batches(doc, cfg, fake_vectors):
    indexing.extract_document(doc["id"], cfg.model_dump(), s.uid())
    id = jobs.submit(
        "indexing", indexing.build_index, doc["id"], cfg.model_dump(), scope=doc["id"]
    )["job_id"]
    job = wait_for_job(id)
    assert job["status"] == "completed"
    events = jobs.job(id)["events"]
    progress = [event["details"]["progress"] for event in events if "progress" in event["details"]]
    values = [item["percent"] for item in progress]
    assert values == sorted(values)
    embeddings = [item for item in progress if item["stage"] == "embedding"]
    assert any(item["completed"] == item["total"] and item["total"] > 0 for item in embeddings)
    assert max(values) == 99
    assert job["progress"]["percent"] == 100
