import os
import tempfile

os.environ["RAG_DATA_DIR"] = tempfile.mkdtemp(prefix="agentic-rag-tests-")
import pytest

from app.core import store as s
from app.core.schemas import Pipeline

@pytest.fixture
def doc():
    from app.main import register

    return register(
        "evidence.md",
        b"# Solar\nSolar panels convert sunlight to electricity.\n\n# Storage\nBatteries store energy for use at night.",
    )

@pytest.fixture
def cfg():
    return Pipeline(mode="description", strategy="document", describe_visuals=False)

@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app, headers={"X-Agentic-RAG-Client": "local-workspace"})

@pytest.fixture
def fake_vectors(monkeypatch):
    import numpy as np

    from app.ingestion import indexing as ix

    def embed(texts, assets, engine, c, b):
        return [
            ix.normalize(
                np.array(
                    [
                        1 + str(t).lower().count("solar"),
                        1 + str(t).lower().count("batter"),
                        1 + str(t).lower().count("night"),
                    ],
                    dtype="float32",
                )
            )
            for t in texts
        ]

    monkeypatch.setattr(ix, "vectors", embed)
    monkeypatch.setattr(
        ix, "local_text", lambda texts, clip=False: embed(texts, [], None, None, None)
    )
    return embed

@pytest.fixture
def indexed(doc, cfg, fake_vectors):
    from app.ingestion.indexing import build_index, extract_document

    extract_document(doc["id"], cfg.model_dump(), "extract-test")
    value = build_index(doc["id"], cfg.model_dump(), "index-test")
    return s.get("documents", doc["id"]), s.get("indexes", value["index_id"])
