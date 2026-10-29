"""Loopback HTTP policy and redacted API error responses."""

from fastapi import Request
from fastapi.responses import JSONResponse

async def local_only(request: Request, call_next):
    host = request.headers.get("host", "").split(":")[0]
    if host not in {"127.0.0.1", "localhost", "testserver"}:
        return JSONResponse({"detail": "Open this app through localhost."}, status_code=403)
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("x-agentic-rag-client") != "local-workspace":
            return JSONResponse({"detail": "Missing local workspace header."}, status_code=403)
        if origin and origin not in {
            f"http://127.0.0.1:{request.url.port}",
            f"http://localhost:{request.url.port}",
            "http://testserver",
        }:
            return JSONResponse({"detail": "Cross-origin request rejected."}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    )
    response.headers["Cache-Control"] = "no-store"
    return response

async def validation_error(request, exc):
    # Do not echo submitted keys or other request values in validation errors.
    return JSONResponse(
        {"detail": [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]},
        status_code=422,
    )

async def value_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=422)

async def source_network_error(request, exc):
    return JSONResponse(
        {"detail": "Could not fetch the webpage. Check its public URL and network access."},
        status_code=422,
    )
