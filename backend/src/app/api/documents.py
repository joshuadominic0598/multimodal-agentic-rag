"""Source library and document-processing endpoints."""

from fastapi import APIRouter, File, UploadFile

from app.core import store as s
from app.core.schemas import ImportPath, ImportURL, Pipeline
from app.ingestion.indexing import build_index, extract_document, preview_chunks
from app.search import index_schema, retrieval
from app.services import documents
from app.services.jobs import submit

router = APIRouter()

@router.post("/api/documents/upload")
async def upload(file: UploadFile = File(...)):
    raw = await file.read(250 * 1024 * 1024 + 1)
    return documents.register(file.filename or "document.txt", raw)

@router.post("/api/documents/{id}/extract")
def extract(id: str, body: Pipeline):
    return submit("extraction", extract_document, id, body.model_dump(), scope=id)

@router.post("/api/documents/{id}/chunks")
def chunks(id: str, body: Pipeline):
    return submit("chunking", preview_chunks, id, body.model_dump(), scope=id)

@router.post("/api/documents/{id}/index")
def index(id: str, body: Pipeline):
    return submit("indexing", build_index, id, body.model_dump(), scope=id)

@router.get("/api/indexes/{id}")
def get_index(id: str):
    return s.get("indexes", id, True)

@router.get("/api/indexes/{id}/filters")
def index_filters(id: str):
    return retrieval.catalog(s.get("indexes", id, True))

@router.get("/api/index-schema")
def get_index_schema():
    return index_schema.info()

@router.get("/api/browse")
def browse(path: str = ""):
    return documents.browse(path)

@router.post("/api/documents/import")
def import_path(body: ImportPath):
    return documents.import_path(body.path)

@router.post("/api/documents/url")
def import_url(body: ImportURL):
    return documents.import_url(body.url)

@router.get("/api/documents/{id}")
def document(id: str):
    return documents.document(id)
