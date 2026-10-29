"""Workspace state, health and frontend/source delivery."""

import os

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.agents.research import SKILLS, TOOLS
from app.core import store as s
from app.core.paths import EXAMPLES_DIR, FRONTEND_DIR
from app.core.schemas import Settings
from app.ingestion.extraction import FORMATS
from app.integrations import azure_auth, azure_cloud
from app.integrations import providers as p
from app.search import index_schema
from app.services.documents import BROWSE_ROOTS

router = APIRouter()

@router.get("/api/health")
def health():
    return {"app": "agentic-rag", "version": "1.0.0", "pid": os.getpid()}

@router.get("/")
def home():
    return FileResponse(FRONTEND_DIR / "index.html")

@router.get("/api/state")
def state():
    return {
        "provider_catalog": p.CATALOG,
        "index_schema": index_schema.info(),
        "azure_profiles": [azure_cloud.public(x) for x in s.rows("azure_profiles")],
        "azure_accounts": azure_auth.accounts(),
        "azure_publications": s.rows("azure_publications")[:100],
        "azure_analyses": s.rows("azure_analyses")[:100],
        "documents": s.rows("documents"),
        "connections": [p.public(x) for x in s.rows("connections")],
        "settings": s.get("settings", "main"),
        "jobs": s.rows("jobs")[:100],
        "datasets": s.rows("datasets"),
        "evaluations": [
            {k: v for k, v in x.items() if k != "results"} for x in s.rows("evaluations")
        ],
        "storage": str(s.DATA),
        "roots": [str(x) for x in BROWSE_ROOTS if x.exists()],
        "formats": sorted(FORMATS),
        "skills": SKILLS,
        "tools": TOOLS,
    }

@router.put("/api/settings")
def settings(body: Settings):
    return s.put("settings", "main", body.model_dump())

@router.get("/api/files/{relative:path}")
def file(relative: str):
    path = s.asset_path(relative)
    ext = path.suffix.lower()
    inline = ext in {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".pdf",
        ".mp3",
        ".mp4",
        ".wav",
        ".m4a",
        ".ogg",
        ".webm",
        ".mov",
    }
    return FileResponse(
        path, filename=path.name, content_disposition_type="inline" if inline else "attachment"
    )

@router.get("/api/examples/{name}")
def example(name: str):
    if name not in {"ground-truth-template.csv", "ground-truth-template.json"}:
        raise ValueError("Example not found.")
    return FileResponse(EXAMPLES_DIR / name, filename=name)
