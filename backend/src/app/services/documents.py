"""Local source browsing and bounded file, folder and webpage imports."""

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from app.core import store as s
from app.core.security import validate_url
from app.ingestion.extraction import supported

BROWSE_ROOTS = [Path.home() / name for name in ["Desktop", "Documents", "Downloads"]]
SKIP_DIRS = {
    ".git",
    ".venv",
    ".venv-evaluation",
    "venv",
    "node_modules",
    "__pycache__",
    ".cache",
    "data",
    "dist",
    "build",
    ".next",
    ".pnpm-store",
    "target",
    ".idea",
    ".vscode",
}
SECRET_NAMES = {
    ".env",
    ".secret-key",
    ".gemini-bootstrap",
    "id_rsa",
    "id_ed25519",
    "credentials.json",
    "service-account.json",
}

def allowed_path(raw, folder=False):
    path = Path(raw).expanduser().resolve(strict=True)
    if not any(path.is_relative_to(root.resolve()) for root in BROWSE_ROOTS):
        raise ValueError("Choose a path within Desktop, Documents or Downloads.")
    if (
        any(
            part.startswith(".") or part in SKIP_DIRS
            for part in path.parts[len(Path.home().parts) :]
        )
        or path.name in SECRET_NAMES
    ):
        raise ValueError("Hidden files, secrets and runtime folders are excluded.")
    if folder and not path.is_dir():
        raise ValueError("Choose a folder.")
    return path

def browse(path: str = ""):
    if not path:
        return {
            "path": "",
            "entries": [
                {"name": p.name, "path": str(p), "directory": True}
                for p in BROWSE_ROOTS
                if p.exists()
            ],
        }
    folder = allowed_path(path, True)
    entries = []
    for pth in sorted(folder.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if (
            pth.name.startswith(".")
            or pth.name in SKIP_DIRS
            or pth.name in SECRET_NAMES
            or pth.is_symlink()
        ):
            continue
        if pth.is_dir() or supported(pth):
            entries.append(
                {
                    "name": pth.name,
                    "path": str(pth),
                    "directory": pth.is_dir(),
                    "size": pth.stat().st_size if pth.is_file() else None,
                }
            )
        if len(entries) >= 500:
            break
    parent = (
        str(folder.parent) if any(folder.parent.is_relative_to(r) for r in BROWSE_ROOTS) else ""
    )
    return {"path": str(folder), "parent": parent, "entries": entries}

def register(name, raw, origin="upload"):
    if not supported(Path(name)):
        raise ValueError(
            "Unsupported format. Choose a supported document, text, image or media file."
        )
    if len(raw) > 250 * 1024 * 1024:
        raise ValueError("Single files are limited to 250 MB.")
    if not raw:
        raise ValueError("The file is empty.")
    id = s.uid()
    safe = Path(name).name
    relative = f"originals/{id}/{safe}"
    dest = s.DATA / relative
    dest.parent.mkdir()
    dest.write_bytes(raw)
    return s.put(
        "documents",
        id,
        {
            "name": safe,
            "path": relative,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw),
            "origin": origin,
            "status": "stored",
            "created": s.now(),
            "active_index": "",
            "extraction_id": "",
        },
    )

def import_path(path_value: str):
    path = allowed_path(path_value)
    if path.is_file():
        return register(path.name, path.read_bytes(), str(path))
    files = []
    total = 0
    for root, dirs, names in os.walk(path, followlinks=False):
        dirs[:] = [
            d
            for d in dirs
            if not d.startswith(".") and d not in SKIP_DIRS and not (Path(root) / d).is_symlink()
        ]
        for name in sorted(names):
            file = Path(root) / name
            if (
                file.is_symlink()
                or name in SECRET_NAMES
                or name.startswith(".")
                or not supported(file)
            ):
                continue
            if file.stat().st_size > 5 * 1024 * 1024:
                continue
            if len(files) >= 2000:
                raise ValueError("Folder exceeds 2000 supported files. Choose a smaller folder.")
            raw = file.read_bytes()
            total += len(raw)
            if total > 250 * 1024 * 1024:
                raise ValueError("Folder import exceeds 250 MB.")
            files.append((str(file.relative_to(path)), raw))
    if not files:
        raise ValueError("No supported files in this folder.")
    id = s.uid()
    folder = s.DATA / "originals" / id
    folder.mkdir()
    manifest = []
    for name, raw in files:
        target = folder / "files" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        manifest.append({"name": name, "path": str(target.relative_to(s.DATA))})
    relative = f"originals/{id}/repository.repo.json"
    (s.DATA / relative).write_text(json.dumps(manifest))
    return s.put(
        "documents",
        id,
        {
            "name": path.name + " (folder)",
            "path": relative,
            "is_bundle": True,
            "sha256": s.digest([(n, hashlib.sha256(r).hexdigest()) for n, r in files]),
            "size": total,
            "origin": str(path),
            "status": "stored",
            "created": s.now(),
            "active_index": "",
            "extraction_id": "",
            "file_count": len(files),
        },
    )

def import_url(url: str):
    with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
        for _ in range(4):
            validate_url(url)
            with client.stream(
                "GET", url, headers={"User-Agent": "Agentic RAG-Local-RAG/1.0"}
            ) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                if not any(
                    t in response.headers.get("content-type", "")
                    for t in ["text/html", "text/plain"]
                ):
                    raise ValueError("URL must return an HTML or text webpage.")
                raw = bytearray()
                for packet in response.iter_bytes():
                    raw.extend(packet)
                    if len(raw) > 10 * 1024 * 1024:
                        raise ValueError("Webpage exceeds 10 MB.")
                return register((urlparse(url).hostname or "webpage") + ".html", bytes(raw), url)
    raise ValueError("Too many webpage redirects.")

def document(id: str):
    doc = s.get("documents", id, True)
    return {
        **doc,
        "extraction": s.get("extractions", doc.get("extraction_id", "")),
        "chunk_preview": s.get("chunk_previews", doc.get("chunk_preview", "")),
        "indexes": [x for x in s.rows("indexes") if x["document_id"] == id],
    }
