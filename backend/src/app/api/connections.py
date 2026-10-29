"""Model profiles and explicit capability checks."""

from fastapi import APIRouter

from app.core import store as s
from app.core.schemas import Connection
from app.integrations import providers as p
from app.services import connections

router = APIRouter()

@router.put("/api/connections/{id}")
def update_connection(id: str, body: Connection):
    return p.save(body.model_dump(), id)

@router.delete("/api/connections/{id}")
def delete_connection(id: str):
    s.delete("connections", id)
    return {"deleted": True}

@router.get("/api/connections/{id}/models")
def models(id: str):
    return p.list_models(p.resolve(id))

@router.post("/api/connections")
def connection(body: Connection, copy_from: str = ""):
    return connections.connection(body.model_dump(), copy_from)

@router.post("/api/connections/{id}/test")
def test_connection(id: str):
    return connections.test_connection(id)

@router.post("/api/model-options")
def discover_models(body: Connection, connection_id: str = ""):
    return connections.discover_models(body.model_dump(), connection_id)
