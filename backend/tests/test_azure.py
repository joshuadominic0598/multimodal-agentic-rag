"""Azure contracts run against deterministic transports; no live credentials required."""

import io
import json
import re
import time

import httpx
import pytest
from PIL import Image

from app.core import store as s
from app.core.schemas import AzureProfile, Connection, Pipeline
from app.ingestion import indexing as ix
from app.integrations import azure_auth as auth
from app.integrations import azure_cloud as az
from app.integrations import azure_layout as layout
from app.integrations import providers as p
from app.main import register

HTTP_CLIENT = httpx.Client

@pytest.fixture
def profile():
    return az.save(
        AzureProfile(
            name="Azure contract",
            document_endpoint="https://agentic-rag-tests.cognitiveservices.azure.com",
            document_key="di-private-key",
            search_endpoint="https://agentic-rag-tests.search.windows.net",
            search_key="search-private-key",
            document_tier="S0",
            search_price_per_1000_queries=0.1,
        ).model_dump()
    )

@pytest.fixture
def pdfdoc():
    import pymupdf

    pdf = pymupdf.open()
    for n in range(3):
        page = pdf.new_page()
        page.insert_text((50, 60), f"Solar {n + 1}")
    raw = pdf.tobytes()
    pdf.close()
    return register("cloud.pdf", raw)

def cfg_for(profile, **kw):
    return Pipeline(
        mode="description",
        strategy="document",
        describe_visuals=False,
        extraction_backend="azure-document-intelligence",
        index_backend="azure-ai-search",
        azure_profile_id=profile["id"],
        **kw,
    )

def planned(doc, cfg, stage):
    plan = az.plan(doc["id"], stage, cfg.model_dump())
    return cfg.model_copy(update={"azure_plan_id": plan["id"]}), plan

def transport(monkeypatch, handler):
    real = HTTP_CLIENT
    monkeypatch.setattr(
        az.httpx, "Client", lambda **kwargs: real(transport=httpx.MockTransport(handler))
    )

def result(pages=(1, 2, 3)):
    return {
        "status": "succeeded",
        "analyzeResult": {
            "apiVersion": "2024-11-30",
            "modelId": "prebuilt-layout",
            "stringIndexType": "unicodeCodePoint",
            "content": "Solar ☀ panels produce energy.\nA | B\n1 | 2",
            "pages": [
                {"pageNumber": n, "width": 8.5, "height": 11, "unit": "inch", "lines": []}
                for n in pages
            ],
            "paragraphs": [
                {
                    "role": "title",
                    "content": "Solar ☀",
                    "spans": [{"offset": 0, "length": 7}],
                    "boundingRegions": [{"pageNumber": 1, "polygon": [0, 0, 8, 0, 8, 1, 0, 1]}],
                },
                {
                    "content": "panels produce energy.",
                    "spans": [{"offset": 8, "length": 22}],
                    "boundingRegions": [{"pageNumber": 1, "polygon": [0, 1, 8, 1, 8, 2, 0, 2]}],
                },
            ],
            "tables": [
                {
                    "rowCount": 2,
                    "columnCount": 2,
                    "cells": [
                        {"rowIndex": r, "columnIndex": c, "content": str(1 + r * 2 + c)}
                        for r in range(2)
                        for c in range(2)
                    ],
                    "spans": [{"offset": 32, "length": 9}],
                    "boundingRegions": [{"pageNumber": 2, "polygon": [0, 1, 8, 1, 8, 4, 0, 4]}],
                }
            ],
            "figures": [
                {
                    "id": "3.1",
                    "caption": {"content": "Solar trend"},
                    "spans": [{"offset": 42, "length": 1}],
                    "boundingRegions": [{"pageNumber": 3, "polygon": [0, 1, 8, 1, 8, 5, 0, 5]}],
                }
            ],
            "sections": [
                {
                    "spans": [{"offset": 0, "length": 43}],
                    "elements": ["/paragraphs/0", "/paragraphs/1"],
                }
            ],
            "styles": [{"isHandwritten": False}],
        },
    }

def layout_transport(monkeypatch, profile, output=None):
    seen = []
    b = io.BytesIO()
    Image.new("RGB", (40, 40), "blue").save(b, format="PNG")

    def handler(req):
        seen.append(req)
        assert req.headers["Ocp-Apim-Subscription-Key"] == "di-private-key"
        if req.method == "POST":
            body = json.loads(req.content)
            assert body["base64Source"] and req.url.params["stringIndexType"] == "unicodeCodePoint"
            return httpx.Response(
                202,
                headers={
                    "Operation-Location": profile["document_endpoint"]
                    + "/documentintelligence/documentModels/prebuilt-layout/analyzeResults/result-123?api-version=2024-11-30"
                },
            )
        if "/figures/" in req.url.path:
            return httpx.Response(200, content=b.getvalue(), headers={"Content-Type": "image/png"})
        return httpx.Response(200, json=output or result())

    transport(monkeypatch, handler)
    monkeypatch.setattr(layout.time, "sleep", lambda _: None)
    return seen

def test_profile_keys_are_encrypted_and_never_returned(profile, client):
    raw = s.get("azure_profiles", profile["id"])
    assert raw["document_key_secret"] != "di-private-key"
    assert az.resolve(profile["id"])["document_key"] == "di-private-key"
    exported = json.dumps(client.get("/api/state").json())
    assert "di-private-key" not in exported and "search-private-key" not in exported
    assert "document_key_secret" not in exported
    edited = az.save(
        AzureProfile(
            **{k: v for k, v in raw.items() if k in AzureProfile.model_fields}
        ).model_dump(),
        profile["id"],
    )
    assert edited["has_document_key"]

@pytest.mark.parametrize(
    "value",
    [
        "https://evil.invalid",
        "http://agentic-rag.search.windows.net",
        "https://agentic-rag.search.windows.net/a",
        "https://user:pass@agentic-rag.search.windows.net",
        "https://agentic-rag.search.windows.net?key=secret",
    ],
)
def test_endpoint_blocks_credentials_paths_and_other_hosts(value):
    with pytest.raises(ValueError):
        az.endpoint(value, "search")

def test_cloud_plan_is_explicit_bound_and_single_use(pdfdoc, profile):
    cfg = cfg_for(profile)
    cfg, plan = planned(pdfdoc, cfg, "extract")
    assert (
        plan["target"] == "prebuilt-layout" and plan["pages"] == 3 and "key" not in json.dumps(plan)
    )
    changed = cfg.model_copy(update={"chunk_size": 800})
    with pytest.raises(ValueError, match="stale"):
        az.consume_plan(pdfdoc, changed, "extract", "stale")
    az.consume_plan(pdfdoc, cfg, "extract", "first")
    with pytest.raises(ValueError, match="already started"):
        az.consume_plan(pdfdoc, cfg, "extract", "second")

def test_layout_maps_only_azure_entities_and_retains_raw_json(pdfdoc, profile, monkeypatch):
    cfg, _ = planned(pdfdoc, cfg_for(profile), "extract")
    seen = layout_transport(monkeypatch, profile)
    # Native parsers and vision layout must not detect Azure entities.
    from app.ingestion.extraction import Extractor

    monkeypatch.setattr(Extractor, "run", lambda _: pytest.fail("local parser called"))
    out = ix.extract_document(pdfdoc["id"], cfg.model_dump(), "azure-extract")
    ex = s.get("extractions", out["extraction_id"])
    assert ex["backend"] == "azure-document-intelligence"
    assert ex["coverage"]["complete"] is True
    assert json.loads(s.asset_path(ex["raw_json_asset"]).read_text()) == result()
    kinds = {x["kind"] for x in ex["elements"]}
    assert {"title", "text", "table", "image", "page_preview", "section"} <= kinds
    table = next(x for x in ex["elements"] if x["kind"] == "table")
    assert table["rows"] == [["1", "2"], ["3", "4"]]
    assert table["bbox"][2] == pytest.approx(8 / 8.5) and not table["preview_reconstructed"]
    figure = next(x for x in ex["elements"] if x["kind"] == "image")
    assert figure["figure_id"] == "3.1" and s.asset_path(figure["asset"]).exists()
    assert len([x for x in seen if x.method == "POST"]) == 1
    ledger = [c for c in s.rows("cloud_calls") if c["run_id"] == "azure-extract"]
    assert all("private-key" not in json.dumps(c) for c in ledger)

def test_f0_partial_coverage_is_not_complete(pdfdoc, profile, monkeypatch):
    s.patch("azure_profiles", profile["id"], document_tier="F0")
    cfg, _ = planned(pdfdoc, cfg_for(profile), "extract")
    output = result((1, 2))
    output["analyzeResult"]["figures"] = []
    layout_transport(monkeypatch, profile, output)
    out = ix.extract_document(pdfdoc["id"], cfg.model_dump(), "azure-partial")
    ex = s.get("extractions", out["extraction_id"])
    assert not ex["coverage"]["complete"] and ex["coverage"]["source_pages"] == 3
    assert any("Partial coverage" in w for w in ex["warnings"])

@pytest.mark.parametrize(
    "url",
    [
        "https://evil.invalid/documentintelligence/documentModels/prebuilt-layout/analyzeResults/a?api-version=2024-11-30",
        "https://agentic-rag-tests.cognitiveservices.azure.com/other?api-version=2024-11-30",
        "http://agentic-rag-tests.cognitiveservices.azure.com/documentintelligence/documentModels/prebuilt-layout/analyzeResults/a?api-version=2024-11-30",
    ],
)
def test_poll_location_rejects_credential_exfiltration(profile, url):
    with pytest.raises(ValueError, match="unexpected"):
        layout.poll_path(url, profile)

def test_unsupported_sources_never_fall_back(doc, profile):
    with pytest.raises(ValueError, match="Azure Layout supports"):
        az.plan(doc["id"], "extract", cfg_for(profile).model_dump())
    with pytest.raises(ValueError, match="ascending"):
        layout.selected_pages("3-1", 3)
    with pytest.raises(ValueError, match="beyond"):
        layout.selected_pages("4", 3)

def test_cancelled_extraction_does_not_submit(pdfdoc, profile, monkeypatch):
    cfg, _ = planned(pdfdoc, cfg_for(profile), "extract")
    seen = layout_transport(monkeypatch, profile)
    s.put("jobs", "azure-cancel", {"cancel": True})
    with pytest.raises(ValueError, match="Cancelled"):
        ix.extract_document(pdfdoc["id"], cfg.model_dump(), "azure-cancel")
    assert seen == [] and not s.get("documents", pdfdoc["id"]).get("extraction_id")

@pytest.fixture
def extracted(pdfdoc, profile, monkeypatch):
    cfg, _ = planned(pdfdoc, cfg_for(profile), "extract")
    layout_transport(monkeypatch, profile)
    ix.extract_document(pdfdoc["id"], cfg.model_dump(), "azure-search-extract-" + s.uid())
    return s.get("documents", pdfdoc["id"]), profile, cfg

def search_transport(monkeypatch, partial=False, conflict=False, query_failure=False):
    seen = []
    saved = {}

    def handler(req):
        seen.append(req)
        assert req.headers["api-key"] == "search-private-key"
        body = json.loads(req.content)
        if req.url.path == "/indexes":
            if conflict:
                return httpx.Response(409, json={"error": "no"})
            assert body["fields"][-1]["vectorSearchProfile"] == "agentic-rag-vector"
            return httpx.Response(201, json=body)
        if req.url.path.endswith("/docs/index"):
            for row in body["value"]:
                saved[row["id"]] = row
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "key": r["id"],
                            "status": not partial,
                            "statusCode": 400 if partial else 201,
                        }
                        for r in body["value"]
                    ]
                },
            )
        if query_failure and body.get("search") != "*":
            return httpx.Response(503, json={"secret": "search-private-key"})
        if body.get("count"):
            return httpx.Response(200, json={"@odata.count": len(saved), "value": []})
        rows = list(saved.values())
        page_match = re.search(r"pages/any\(p: p eq (\d+)\)", body.get("filter", ""))
        if page_match:
            rows = [row for row in rows if int(page_match[1]) in row["pages"]]
        rows = rows[: body["top"]]
        return httpx.Response(200, json={"value": [{**r, "@search.score": 0.4} for r in rows]})

    transport(monkeypatch, handler)
    return seen, saved

def test_azure_publication_and_hybrid_retrieval(extracted, monkeypatch, fake_vectors):
    doc, profile, cfg = extracted
    cfg, plan = planned(doc, cfg, "index")
    seen, saved = search_transport(monkeypatch)
    out = ix.build_index(doc["id"], cfg.model_dump(), "cloud-index-" + s.uid())
    index = s.get("indexes", out["index_id"])
    assert index["backend"] == "azure-ai-search" and index["search_index"] == plan["target"]
    assert s.get("documents", doc["id"])["active_index"] == index["id"]
    with s.db() as db:
        assert (
            db.execute("SELECT count(*) FROM vectors WHERE index_id=?", (index["id"],)).fetchone()[
                0
            ]
            == 0
        )
    hits = ix.search(index, "solar", p.Budget("cloud-search-test"), 3)
    assert hits and hits[0]["retrieval_backend"] == "azure-ai-search"
    query = json.loads(seen[-1].content)
    assert (
        query["vectorQueries"][0]["fields"] == "content_vector"
        and index["id"] in query["filter"]
        and doc["id"] in query["filter"]
    )
    az.query(index, None, "*", p.Budget("page-cloud"), 80, page=2)
    assert "pages/any" in json.loads(seen[-1].content)["filter"]
    saved[next(iter(saved))]["content"] = "changed cloud evidence"
    with pytest.raises(ValueError, match="differs"):
        ix.search(index, "solar", p.Budget("drift"), 3)

@pytest.mark.parametrize("partial,conflict", [(True, False), (False, True)])
def test_failed_cloud_candidate_preserves_active_index(
    extracted, monkeypatch, fake_vectors, partial, conflict
):
    doc, profile, cfg = extracted
    s.patch("documents", doc["id"], active_index="previous-working-index")
    cfg, _ = planned(doc, cfg, "index")
    search_transport(monkeypatch, partial=partial, conflict=conflict)
    with pytest.raises(ValueError):
        ix.build_index(doc["id"], cfg.model_dump(), "cloud-failure-" + s.uid())
    assert s.get("documents", doc["id"])["active_index"] == "previous-working-index"
    publication = next(x for x in s.rows("azure_publications") if x["document_id"] == doc["id"])
    assert publication["status"] == "failed"

def test_cloud_search_failure_does_not_read_local_vectors(extracted, monkeypatch, fake_vectors):
    doc, profile, cfg = extracted
    cfg, _ = planned(doc, cfg, "index")
    search_transport(monkeypatch, query_failure=True)
    out = ix.build_index(doc["id"], cfg.model_dump(), "query-failure-build")
    index = s.get("indexes", out["index_id"])
    with pytest.raises(ValueError, match="HTTP 503"):
        ix.search(index, "solar", p.Budget("azure-503"), 3)
    assert all("private-key" not in json.dumps(c) for c in s.rows("cloud_calls"))

def test_vision_embeddings_preserve_all_text_and_use_pixels(profile, monkeypatch):
    s.patch(
        "azure_profiles",
        profile["id"],
        vision_endpoint="https://agentic-rag-tests.cognitiveservices.azure.com",
        vision_key_secret=p.cipher().encrypt(b"vision-private-key").decode(),
    )
    cfg = az.resolve(profile["id"])
    seen = []

    def handler(req):
        seen.append(req)
        assert req.headers["Ocp-Apim-Subscription-Key"] == "vision-private-key"
        return httpx.Response(200, json={"vector": [0.2, 0.5, 0.9], "modelVersion": "2023-04-15"})

    transport(monkeypatch, handler)
    b = io.BytesIO()
    Image.new("RGB", (40, 40), "purple").save(b, format="PNG")
    from app.ingestion.extraction import asset

    a = asset("test-vision", "azure.png", b.getvalue())
    words = ["word" + str(i) for i in range(145)]
    vectors = az.vision_vectors(
        [" ".join(words), "image"], [None, a], cfg, p.Budget("azure-vision-test", 10)
    )
    assert len(vectors) == 2 and len(seen) == 4
    assert " ".join(json.loads(req.content)["text"] for req in seen[:3]) == " ".join(words)
    assert (
        seen[-1].headers["Content-Type"] == "application/octet-stream"
        and seen[-1].content == b.getvalue()
    )

def test_entra_connection_requires_no_api_key_and_uses_correct_scopes(monkeypatch):
    calls = []

    class Token:
        token = "private-access-token"

    class Credential:
        def get_token(self, scope):
            calls.append(scope)
            return Token()

    monkeypatch.setattr(auth, "credential", lambda config: Credential())
    c = p.save(
        Connection(
            name="Azure identity",
            provider="azure",
            model="test-deployment",
            endpoint="https://agentic-rag.openai.azure.com",
            auth_mode="entra",
        ).model_dump()
    )
    assert not c["has_key"] and p.auth_headers(p.resolve(c["id"])) == {
        "Authorization": "Bearer private-access-token"
    }
    auth.headers({"auth_mode": "entra"}, "search")
    assert calls == [
        "https://cognitiveservices.azure.com/.default",
        "https://search.azure.com/.default",
    ]
    assert "private-access-token" not in json.dumps(p.public(p.resolve(c["id"])))

def test_budget_counts_unpriced_cloud_usage():
    run = "azure-budget-test"
    s.put("cloud_calls", s.uid(), {"run_id": run, "cost_usd": None, "status": "completed"})
    with pytest.raises(ValueError, match="budget"):
        p.Budget(run, 10, 1).check(0.1)

def test_azure_monitor_includes_service_usage(client):
    data = client.get("/api/monitor").json()
    assert data["cloud_summary"]["calls"] > 0 and data["cloud_calls"]
    assert data["summary"]["unpriced_calls"] >= data["cloud_summary"]["unpriced"]

def test_microsoft_device_flow_uses_encrypted_cache_and_hides_record(monkeypatch):
    import azure.identity

    captured = {}

    class Record:
        username = "agentic-rag-test@example.invalid"

        def serialize(self):
            return '{"test":"private-authentication-record"}'

    class Credential:
        def __init__(self, **kw):
            captured.update(kw)

        def authenticate(self, scopes):
            captured["scopes"] = scopes
            captured["prompt_callback"](
                "https://microsoft.com/devicelogin", "TEST-CODE", int(time.time()) + 600
            )
            return Record()

    monkeypatch.setattr(azure.identity, "DeviceCodeCredential", Credential)
    started = auth.start({"tenant_id": "agentic-rag-test.onmicrosoft.com", "client_id": ""})
    for _ in range(100):
        state = auth.status(started["id"])
        if state["status"] in {"completed", "failed"}:
            break
        time.sleep(0.01)
    assert state["status"] == "completed"
    opts = captured["cache_persistence_options"]
    assert opts.allow_unencrypted_storage is False
    assert captured["disable_automatic_authentication"] is False
    assert "private-authentication-record" not in json.dumps(auth.accounts())
    raw = s.get("azure_accounts", state["account_id"])
    assert "private-authentication-record" not in raw["secret_record"]
    assert "user_code" not in state

def test_profile_identity_changes_cannot_redirect_saved_index(profile):
    snapshot = profile
    s.patch("azure_profiles", profile["id"], search_endpoint="https://different.search.windows.net")
    with pytest.raises(ValueError, match="identity changed"):
        az.resolve(profile["id"], snapshot)

def test_cloud_index_requires_azure_layout_extraction(indexed, profile):
    doc, index = indexed
    with pytest.raises(ValueError, match="Extract this document with Azure"):
        az.plan(doc["id"], "index", cfg_for(profile).model_dump())

def test_private_blob_publication_keeps_scoped_originals_and_no_public_access(
    extracted, monkeypatch, fake_vectors
):
    import azure.storage.blob

    doc, profile, cfg = extracted
    s.patch(
        "azure_profiles",
        profile["id"],
        publish_assets=True,
        blob_endpoint="https://agenticragtests.blob.core.windows.net",
        blob_key_secret=p.cipher().encrypt(b"private-blob-key").decode(),
    )
    uploads = []

    class Container:
        def get_container_properties(self):
            return {"public_access": None}

        def upload_blob(self, **kw):
            assert kw["overwrite"] is False
            uploads.append({"name": kw["name"], "raw": kw["data"].read()})

    class Blob:
        def __init__(self, **kw):
            assert kw["credential"] == "private-blob-key" and kw["retry_total"] == 0

        def get_container_client(self, name):
            assert name == "agentic-rag-sources"
            return Container()

        def close(self):
            pass

    monkeypatch.setattr(azure.storage.blob, "BlobServiceClient", Blob)
    cfg, _ = planned(doc, cfg, "index")
    search_transport(monkeypatch)
    out = ix.build_index(doc["id"], cfg.model_dump(), "private-blob-publication")
    index = s.get("indexes", out["index_id"])
    assert index["blob_assets"] and len(index["blob_assets"]) == len(uploads)
    assert all(
        x["name"].startswith("agentic-rag/" + doc["id"] + "/" + index["id"] + "/") for x in uploads
    )
    assert any(x["name"].endswith("cloud.pdf") for x in uploads)
    assert any(x["name"].endswith("azure-layout-result.json") for x in uploads)
    from app.agents.research import source_cards

    assert source_cards(index, index["chunks"][:1])[0]["cloud_references"]

def test_agent_page_inspection_stays_in_azure_search(extracted, monkeypatch, fake_vectors):
    doc, profile, cfg = extracted
    cfg, _ = planned(doc, cfg, "index")
    seen, saved = search_transport(monkeypatch)
    ix.build_index(doc["id"], cfg.model_dump(), "agent-page-cloud-build")
    from app.agents.research import answer

    response = answer(
        {"document_id": doc["id"], "message": "Explain page 2", "preview": True},
        "azure-agent-preview",
    )
    assert response["status"] == "preview" and response["sources"]
    assert any("pages/any" in json.loads(req.content).get("filter", "") for req in seen)

def test_cloud_evaluation_uses_remote_retrieval_and_counts_cloud_calls(
    extracted, monkeypatch, fake_vectors
):
    doc, profile, cfg = extracted
    cfg, _ = planned(doc, cfg, "index")
    seen, saved = search_transport(monkeypatch)
    ix.build_index(doc["id"], cfg.model_dump(), "eval-cloud-index")
    model = p.save(
        Connection(
            name="Azure answer fixture",
            provider="azure",
            model="deployment",
            endpoint="https://agentic-rag.openai.azure.com",
            api_key="unit-only-key",
        ).model_dump()
    )
    from app.agents.evaluation import parse_dataset, run_evaluation

    dataset = parse_dataset(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "solar",
                        "question": "What do panels produce?",
                        "reference_answer": "Solar panels produce energy.",
                        "reference_status": "verified",
                        "expected_chunk_ids": ["c00002"],
                    }
                ]
            }
        ).encode(),
        "cloud.json",
        doc["id"],
        s.get("documents", doc["id"])["active_index"],
    )

    def generate(c, budget, system, prompt, *args, **kw):
        if "Plan up to" in prompt:
            return {"queries": ["solar energy"]}
        if "Assess whether" in prompt:
            return {"sufficient": True}
        return "Solar panels produce energy. [c00002]", []

    monkeypatch.setattr(p, "generate", generate)
    out = run_evaluation(dataset["id"], [model["id"]], "azure-eval-contract")
    evaluation = s.get("evaluations", out["evaluation_id"])
    assert evaluation["results"][0]["status"] == "completed", evaluation["results"][0].get("error")
    assert evaluation["results"][0]["calls"] >= 1
    assert (
        evaluation["results"][0]["result"]["sources"][0]["retrieval_backend"] == "azure-ai-search"
    )

def test_validation_errors_do_not_echo_submitted_credentials(client):
    private = "sensitive-test-" * 70
    r = client.post(
        "/api/azure/profiles",
        json={
            "name": "Azure",
            "document_endpoint": "https://test.cognitiveservices.azure.com",
            "search_endpoint": "https://test.search.windows.net",
            "document_key": private,
            "search_key": "other-private-key",
        },
    )
    assert r.status_code == 422 and private not in r.text and "other-private-key" not in r.text

def test_azure_field_flags_and_filtered_hybrid_payload(extracted, monkeypatch, fake_vectors):
    doc, profile, cfg = extracted
    fields = {
        "source_name": {"searchable": True, "retrievable": False},
        "source_type": {"retrievable": False},
        "time_start": {"sortable": False},
    }
    cfg = Pipeline(**{**cfg.model_dump(), "index_fields": fields})
    cfg, _ = planned(doc, cfg, "index")
    seen, saved = search_transport(monkeypatch)
    output = ix.build_index(doc["id"], cfg.model_dump(), "custom-field-cloud-index")
    index = s.get("indexes", output["index_id"])
    definition = json.loads(next(req for req in seen if req.url.path == "/indexes").content)
    columns = {c["name"]: c for c in definition["fields"]}
    assert columns["source_name"]["searchable"] and not columns["source_name"]["retrievable"]
    assert not columns["pages"]["sortable"] and not columns["time_start"]["sortable"]
    eligible = [c for c in index["chunks"] if "table" in c["kinds"]]

    def handler(req):
        seen.append(req)
        return httpx.Response(
            200, json={"value": [{**saved[c["id"]], "@search.score": 0.4} for c in eligible]}
        )

    transport(monkeypatch, handler)
    hits = ix.search(
        index,
        "solar",
        p.Budget("custom-cloud-hybrid"),
        6,
        filters={"kinds": ["table"], "page_from": 2, "has_visual": True},
        keyword_query="solar table",
    )
    body = json.loads(seen[-1].content)
    assert hits and all("table" in x["kinds"] for x in hits)
    assert body["search"] == "solar table" and body["vectorFilterMode"] == "preFilter"
    assert (
        "kinds/any" in body["filter"]
        and "has_visual eq true" in body["filter"]
        and index["id"] in body["filter"]
    )
    assert "source_name" in body["searchFields"].split(",") and "source_name" not in body[
        "select"
    ].split(",")
    meta = json.loads(saved[eligible[0]["id"]]["metadata"])
    assert meta["chunk_hash"] == s.digest(eligible[0]) and "text" not in meta
    az.query(
        index,
        None,
        "solar",
        p.Budget("custom-cloud-keyword"),
        6,
        filters={"kinds": ["table"]},
        search_mode="keyword",
    )
    assert "vectorQueries" not in json.loads(seen[-1].content)
    az.query(
        index,
        [0.1, 0.2, 0.3],
        "unused",
        p.Budget("custom-cloud-vector"),
        6,
        filters={"kinds": ["table"]},
        search_mode="vector",
    )
    assert "search" not in json.loads(seen[-1].content)
