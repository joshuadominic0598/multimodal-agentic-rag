import copy
import json

import httpx
import pytest

from app.agents import context as cm
from app.core import store as s
from app.core.schemas import Pipeline, Question, SearchFilters
from app.ingestion import indexing as ix
from app.integrations import providers as p
from app.search import index_schema as schema
from app.search import local_embeddings as le
from app.search import retrieval as rt

def test_field_flags_are_typed_and_collections_not_sortable():
    config = schema.configure(
        {"source_name": {"searchable": True, "retrievable": False}, "tags": {"filterable": False}}
    )
    assert config["source_name"]["searchable"] and not config["source_name"]["retrievable"]
    assert not config["tags"]["filterable"]
    for bad in [
        {"pages": {"sortable": True}},
        {"content": {"retrievable": False}},
        {"content_vector": {"filterable": True}},
        {"title": {"surprise": True}},
    ]:
        with pytest.raises(ValueError):
            schema.configure(bad)
    empty = {f["name"]: {"searchable": False} for f in schema.SPECS}
    with pytest.raises(ValueError, match="at least one"):
        schema.configure(empty)

def test_metadata_filter_truth_values_and_safe_odata():
    chunk = {
        "text": "sample",
        "title": "Solar",
        "kinds": ["table"],
        "pages": [3, 6],
        "assets": ["picture.png"],
        "filter_metadata": {
            "kinds": ["table"],
            "sections": ["Director's report"],
            "source_names": ["notes.pdf"],
            "source_types": ["pdf"],
            "source_paths": [],
            "sheets": [],
            "tags": ["verified"],
            "has_visual": True,
            "time_start": 10,
            "time_end": 25,
        },
    }
    f = {
        "sections": ["Director's report"],
        "page_from": 4,
        "page_to": 8,
        "has_visual": True,
        "time_from": 20,
        "equals": {"source_name": "notes.pdf"},
    }
    assert rt.matches(chunk, f)
    assert "Director''s report" in rt.odata(f)
    assert "pages/any(p: p ge 4 and p le 8)" in rt.odata(f)
    assert not rt.matches(chunk, {"has_visual": False})
    assert not rt.matches(chunk, {"page_from": 4, "page_to": 5})
    assert not rt.matches(chunk, [{"kinds": ["table"]}, {"kinds": ["text"]}])
    assert not rt.matches(chunk, {"time_to": 5})
    assert rt.clean({"has_visual": False}) == {"has_visual": False}
    with pytest.raises(ValueError):
        SearchFilters(page_from=8, page_to=2)
    with pytest.raises(ValueError):
        SearchFilters(time_from=float("nan"))

def test_local_hybrid_filters_before_lexical_limit(indexed):
    doc, index = indexed
    base = index["chunks"][0]
    chunks = []
    with s.db() as db:
        db.execute("DELETE FROM vectors WHERE index_id=?", (index["id"],))
        db.execute("DELETE FROM search WHERE index_id=?", (index["id"],))
        for n in range(70):
            c = {
                **base,
                "id": f"c{n + 1:05d}",
                "title": "solar",
                "text": "solar " * 100 if n < 69 else "solar evidence",
                "kinds": ["text"] if n < 69 else ["table"],
                "pages": [n + 1],
            }
            c["filter_metadata"] = rt.metadata(c, [])
            chunks.append(c)
            db.execute("INSERT INTO search VALUES(?,?,?)", (index["id"], c["id"], c["text"]))
            db.execute(
                "INSERT INTO vectors VALUES(?,?,?)",
                (index["id"], c["id"], ix.normalize([1, 1, 1]).tobytes()),
            )
    index = {**index, "chunks": chunks}
    hits = ix.search(
        index, "solar", p.Budget("prefilter-candidates"), 5, filters={"kinds": ["table"]}
    )
    assert [h["id"] for h in hits] == ["c00070"]
    assert hits[0]["keyword_rank"] == 1 and hits[0]["vector_rank"] == 1
    assert not ix.search(
        index, "solar", p.Budget("empty-candidates"), 5, filters={"kinds": ["image"]}
    )

def test_keyword_retrieval_makes_no_embedding_request(indexed, monkeypatch):
    doc, index = indexed
    monkeypatch.setattr(ix, "vectors", lambda *a: pytest.fail("keyword search embedded query"))
    hits = ix.search(index, "solar", p.Budget("keyword-only"), 4, search_mode="keyword")
    assert hits and all(h["cosine"] is None and h["keyword_rank"] for h in hits)

def test_local_vector_path_and_keyword_override(indexed):
    _, index = indexed
    vector = ix.search(index, "night", p.Budget("vector-only"), 4, search_mode="vector")
    assert vector and all(h["keyword_rank"] is None for h in vector)
    lexical = ix.search(
        index,
        "unrelated question",
        p.Budget("keywords-pin"),
        4,
        search_mode="keyword",
        keyword_query="solar",
    )
    assert lexical and "solar" in lexical[0]["text"].lower()

def test_disabled_filter_field_rejected_before_calls(indexed):
    _, index = indexed
    index = {
        **index,
        "config": {**index["config"], "index_fields": {"kinds": {"filterable": False}}},
    }
    with pytest.raises(ValueError, match="not configured as filterable"):
        ix.search(index, "solar", p.Budget("disabled-filter"), 4, filters={"kinds": ["text"]})
    assert "kinds" not in rt.catalog(index)["fields"]

def test_old_azure_index_requires_rebuild_for_rich_filters(indexed):
    _, index = indexed
    index = {**index, "backend": "azure-ai-search"}
    index.pop("retrieval_schema_version", None)
    rt.require_schema(index, {"page_from": 2})
    with pytest.raises(ValueError, match="predates"):
        rt.require_schema(index, {"kinds": ["table"]})

def test_index_field_choices_control_keyword_index(doc, cfg, fake_vectors):
    config = Pipeline(
        **{
            **cfg.model_dump(),
            "index_fields": {
                "content": {"searchable": False},
                "title": {"searchable": False},
                "source_name": {"searchable": True},
            },
            "metadata_tags": ["checked"],
        }
    )
    ix.extract_document(doc["id"], config.model_dump(), "schema-extract")
    result = ix.build_index(doc["id"], config.model_dump(), "schema-build")
    index = s.get("indexes", result["index_id"])
    assert not ix.search(index, "solar", p.Budget("schema-keywords"), 4, search_mode="keyword")
    assert ix.search(index, "evidence", p.Budget("schema-filename"), 4, search_mode="keyword")
    assert rt.catalog(index)["fields"]["tags"]["values"][0]["value"] == "checked"

def test_agent_cannot_widen_user_filters(indexed, monkeypatch):
    from app.agents.research import answer

    doc, index = indexed
    chunks = copy.deepcopy(index["chunks"])
    chunks[0]["kinds"] = ["table"]
    chunks[0]["filter_metadata"]["kinds"] = ["table"]
    s.patch("indexes", index["id"], chunks=chunks)
    # Narrowing to an incompatible existing kind must produce no sources, never relax.
    c = {
        "id": "sim",
        "provider": "gemini",
        "model": "fake",
        "key": "none",
        "context_chars": 12000,
        "max_output": 1000,
    }

    def generate(c, b, system, prompt, *args, **kw):
        if "Plan up to" in prompt:
            return {"queries": ["solar"], "filters": {"kinds": ["table"]}}
        if "Assess whether" in prompt:
            return {"sufficient": True}
        return "No evidence in the selected scope.", []

    monkeypatch.setattr(p, "generate", generate)
    result = answer(
        {
            "document_id": doc["id"],
            "message": "Only table items",
            "clarified": True,
            "filters": {"kinds": ["text"]},
        },
        "pinned-agent-scope",
        c,
    )
    assert result["sources"] == [] and result["retrieval"]["applied_filters"] == [
        {"kinds": ["text"]},
        {"kinds": ["table"]},
    ]

def test_clarification_preserves_initial_retrieval_scope(indexed):
    from app.agents.research import answer

    doc, index = indexed
    first = answer(
        {
            "document_id": doc["id"],
            "message": "Explain solar",
            "filters": {"kinds": ["text"]},
            "search_mode": "keyword",
            "effort": "low",
            "context_chars": 8000,
        },
        "filter-clarify",
    )
    later = answer(
        {
            "document_id": doc["id"],
            "session_id": first["session_id"],
            "message": "Explain solar",
            "clarified": True,
            "clarification_answer": "Use all matching text.",
            "preview": True,
        },
        "filter-after-clarify",
    )
    assert (
        later["context_policy"]["context_chars"] == 8000
        and later["context_policy"]["effort"] == "low"
    )
    assert later["retrieval"]["search_mode"] == "keyword" and later["retrieval"]["filters"] == {
        "kinds": ["text"]
    }

def test_context_packets_fit_exact_character_limit():
    system = "system rules " * 150
    payload = {
        "question": "What does the evidence say?",
        "scope": {"filters": {"pages": [5]}},
        "context": {
            "history": [{"content": "history " * 5000}],
            "memory": [{"text": "memory " * 1000}],
            "guidance": "guide " * 2000,
        },
        "catalog": {"fields": {"sections": {"values": [{"value": "X" * 4000} for _ in range(5)]}}},
        "evidence": [{"chunk_id": f"c{i:05d}", "text": "Long evidence " * 3000} for i in range(6)],
    }
    prompt, packed, account = cm.pack(system, "Answer with citations", payload, 8000)
    assert len(system) + len(prompt) <= 8000 and account["text_input_chars"] <= 8000
    assert (
        packed["question"] == payload["question"]
        and packed["scope"] == payload["scope"]
        and packed["evidence"]
    )
    assert account["trimmed"]["history"] == 1 and account["trimmed"]["evidence_characters"] > 0
    assert payload["context"]["history"]  # input is never mutated

def test_effort_and_connection_caps_are_independent():
    for effort, calls, passes in [("low", 5, 1), ("medium", 12, 2), ("high", 30, 4)]:
        q = Question(
            document_id="doc",
            message="question",
            effort=effort,
            max_calls=30,
            max_passes=4,
            context_chars=120000,
        )
        limits = cm.limits(q, {"context_chars": 12000})
        assert (
            limits["context_chars"] == 12000
            and limits["calls"] == calls
            and limits["passes"] == passes
        )

@pytest.mark.parametrize("engine", ["ollama-small", "ollama-large"])
def test_ollama_embedding_contract_and_query_prefix(engine, monkeypatch):
    real = httpx.Client
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        assert req.url.host == "127.0.0.1" and req.url.path == "/api/embed"
        assert "authorization" not in req.headers
        return httpx.Response(
            200,
            json={
                "model": le.PROFILES[engine]["model"],
                "embeddings": [[0.2, 0.5, 0.8]],
                "prompt_eval_count": 8,
            },
        )

    monkeypatch.setattr(
        le.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler))
    )
    assert (
        len(le.embed(["solar"], engine, {"embedding_query": True}, p.Budget("ollama-" + engine))[0])
        == 3
    )
    assert seen[0]["truncate"] is False and seen[0]["model"] == le.PROFILES[engine]["model"]
    assert seen[0]["input"][0].startswith(
        "task: search result | query:"
        if engine == "ollama-small"
        else "Instruct: Retrieve document"
    )

def test_private_embeddings_reject_remote_endpoint():
    for url in [
        "https://api.example.com",
        "http://127.0.0.1:11434/other",
        "http://user:secret@localhost:11434",
    ]:
        with pytest.raises(ValueError):
            le.endpoint(url)

def test_filter_and_schema_api(client, indexed):
    _, index = indexed
    data = client.get("/api/indexes/" + index["id"] + "/filters").json()
    assert "kinds" in data["fields"]
    assert client.get("/api/index-schema").json()["fields"]
    assert (
        client.post(
            "/api/chat",
            json={
                "document_id": index["document_id"],
                "message": "test",
                "filters": {"raw_odata": "id ne ''"},
            },
        ).status_code
        == 422
    )

def test_exact_ordinal_filter_matches_uploaded_position(indexed):
    _, index = indexed
    index = {
        **index,
        "config": {**index["config"], "index_fields": {"ordinal": {"filterable": True}}},
    }
    rt.validate_fields(index, {"equals": {"ordinal": 0}})
    assert rt.matches(index["chunks"][0], {"equals": {"ordinal": 0}})
    assert not rt.matches(index["chunks"][0], {"equals": {"ordinal": 1}})
