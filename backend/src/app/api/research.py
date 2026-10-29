"""Conversational research and document-scoped memory endpoints."""

from fastapi import APIRouter

from app.agents.research import answer
from app.core import store as s
from app.core.schemas import Memory, Question
from app.services.jobs import submit

router = APIRouter()

@router.post("/api/chat")
def chat(body: Question):
    return submit("chat", answer, body.model_dump())

@router.get("/api/sessions")
def sessions(document_id: str):
    return [
        x for x in s.rows("sessions") if x["document_id"] == document_id and not x.get("isolated")
    ]

@router.get("/api/sessions/{id}")
def session_detail(id: str):
    session = s.get("sessions", id, True)
    candidates = [x for x in s.rows("answers") if x.get("session_id") == id]
    return {**session, "latest_answer": candidates[0] if candidates else None}

@router.get("/api/memory")
def memories(document_id: str):
    return [x for x in s.rows("memory") if x["document_id"] == document_id]

@router.post("/api/memory")
def remember(body: Memory):
    s.get("documents", body.document_id, True)
    return s.put(
        "memory", s.uid(), {**body.model_dump(), "type": "user_preference", "updated": s.now()}
    )

@router.delete("/api/memory/{id}")
def forget(id: str):
    s.delete("memory", id)
    return {"deleted": True}

@router.delete("/api/sessions/{id}")
def forget_session(id: str):
    s.delete("sessions", id)
    s.delete("memory", "summary-" + id)
    return {"deleted": True}
