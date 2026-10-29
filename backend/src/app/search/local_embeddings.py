"""The same two private text-embedding choices used by AgilePlanner."""

import time
from urllib.parse import urlsplit

import httpx

from app.core import store as s

PROFILES = {
    "ollama-small": {
        "model": "embeddinggemma",
        "label": "Smaller · EmbeddingGemma",
        "chunk_size": 1000,
        "overlap": 200,
    },
    "ollama-large": {
        "model": "qwen3-embedding:4b",
        "label": "Larger · Qwen3 Embedding 4B",
        "chunk_size": 3000,
        "overlap": 500,
    },
}

def endpoint(url):
    u = urlsplit(url)
    if (
        u.scheme not in {"http", "https"}
        or u.hostname not in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}
        or u.username is not None
        or u.password is not None
        or u.query
        or u.fragment
        or u.path not in {"", "/", "/v1", "/v1/"}
    ):
        raise ValueError("Private embedding models require a local Ollama endpoint.")
    return url.rstrip("/").removesuffix("/v1")

def embed(texts, engine, config, budget):
    from app.ingestion.indexing import normalize

    cfg = config or {}
    url = endpoint(cfg.get("ollama_url", "http://127.0.0.1:11434"))
    model = PROFILES[engine]["model"]
    query = cfg.get("embedding_query", False)
    if engine == "ollama-small":
        texts = [
            ("task: search result | query: " if query else "title: none | text: ") + t
            for t in texts
        ]
    elif query:
        texts = [
            "Instruct: Retrieve document passages relevant to the search query.\nQuery: " + t
            for t in texts
        ]
    # Local calls are bounded and priced at zero API fees, excluding the user's hardware.
    budget.check(0)
    id = s.uid()
    start = time.time()
    s.put(
        "local_calls",
        id,
        {
            "run_id": budget.run,
            "model": model,
            "operation": "query embedding" if query else "document embedding",
            "status": "running",
            "start": start,
            "cost_usd": 0,
            "api_fees_only": True,
        },
    )
    try:
        with httpx.Client(timeout=180, trust_env=False, follow_redirects=False) as client:
            r = client.post(
                url + "/api/embed", json={"model": model, "input": texts, "truncate": False}
            )
            r.raise_for_status()
            obj = r.json()
        vectors = obj["embeddings"]
        if len(vectors) != len(texts):
            raise ValueError("Local embedding count did not match the input.")
        result = [normalize(v) for v in vectors]
        s.patch(
            "local_calls",
            id,
            status="completed",
            duration=time.time() - start,
            prompt_tokens=obj.get("prompt_eval_count"),
            embedding_count=len(vectors),
            dimension=len(result[0]) if result else 0,
        )
        s.event(
            budget.run,
            "embedding",
            model + " · local embedding request",
            query=query,
            items=len(texts),
            duration=time.time() - start,
        )
        return result
    except Exception:
        s.patch(
            "local_calls",
            id,
            status="failed",
            duration=time.time() - start,
            error="Local embedding service failed. Check Ollama and the selected installed model; no cloud fallback was made.",
        )
        raise ValueError(
            f"Local {model} embeddings failed. Keep Ollama running and install that exact model, or reduce chunk size if its context limit was exceeded. No input was silently truncated or sent to a cloud fallback."
        ) from None
