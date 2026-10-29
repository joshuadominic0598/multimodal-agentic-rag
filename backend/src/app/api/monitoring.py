"""Read monitoring state and request job cancellation."""

from fastapi import APIRouter

from app.services import jobs, monitoring

router = APIRouter()

@router.get("/api/monitor")
def monitor():
    return monitoring.monitor()

@router.get("/api/monitor/{run}")
def trace(run: str):
    return monitoring.trace(run)

@router.get("/api/jobs/{id}")
def job(id: str):
    return jobs.job(id)

@router.post("/api/jobs/{id}/cancel")
def cancel(id: str):
    return jobs.cancel(id)
