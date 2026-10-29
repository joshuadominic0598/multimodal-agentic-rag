"""Compose the local HTTP application without running workflows on import."""

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles

from app.api import azure, connections, documents, evaluation, monitoring, research, workspace
from app.api.security import local_only, source_network_error, validation_error, value_error
from app.core.paths import FRONTEND_DIR
from app.core.security import validate_url as validate_url
from app.integrations import providers
from app.services.documents import register as register
from app.services.jobs import lifespan

providers.bootstrap()
app = FastAPI(
    lifespan=lifespan,
    title="Agentic RAG · Document Knowledge Studio",
    version="1.0.0",
    docs_url="/api/docs",
)
app.middleware("http")(local_only)
app.add_exception_handler(RequestValidationError, validation_error)
app.add_exception_handler(ValueError, value_error)
app.add_exception_handler(httpx.HTTPError, source_network_error)
for routes in [workspace, azure, connections, documents, research, monitoring, evaluation]:
    app.include_router(routes.router)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
