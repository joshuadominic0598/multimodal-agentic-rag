# Azure workspace

![Azure document workflow](assets/azure-workflow.png)

[Scalable diagram](assets/azure-workflow.svg) · [Editable draw.io](diagrams/azure-workflow.drawio)


Agentic RAG can orchestrate an Azure document pipeline while the app runs on your desktop:

**Local source → Azure Document Intelligence `prebuilt-layout` → inspect elements and raw JSON → preprocessing and chunking → embeddings → new Azure AI Search index → agentic retrieval → Azure OpenAI answers.**

Connect resources that already exist in your account. Agentic RAG creates a versioned index inside your Search service; it does not provision services, deployments, storage accounts or access roles. All cloud actions begin in the app.

## Connect from Agentic RAG

1. Open **Azure workspace**. Choose service keys, Microsoft sign-in, or an existing Azure CLI session.
2. For Microsoft sign-in, enter your tenant ID/domain and, if needed, your approved public-client application ID. Start sign-in in Agentic RAG, open the Microsoft link, and enter the displayed one-time code. Return to Agentic RAG for completion status. Tokens use the OS encrypted credential cache; plaintext cache fallback is disabled. Organizations can restrict device-code login or the default Microsoft developer client. An administrator may need to supply an approved app registration. See [Microsoft's device-code credential](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.devicecodecredential?view=azure-python) and [encrypted cache options](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.tokencachepersistenceoptions?view=azure-python).
3. Enter the Document Intelligence resource endpoint and Search service endpoint. With key authentication, enter the matching Document Intelligence key and a Search **admin** key. A query key cannot create indexes. Saved keys are encrypted and write-only; leaving an edited key blank retains it.
4. Choose the Document Intelligence tier and an index prefix. Run **Check access**. This reads service metadata only; it does not submit a file or create an index. It cannot establish every data-write permission.
5. In **Connections & settings**, add an Azure OpenAI connection: resource endpoint, answer deployment ID, text embedding deployment ID, authentication method, and image-input capability. Use the same tenant/application identity if using Microsoft sign-in. Test the actual deployments before relying on vision. Select that connection in your Azure workspace profile.
6. Optionally add Azure Vision for native visual embeddings, and an existing private Blob container for cloud source references. Save the profile.

Public Azure endpoint domains are supported. Sovereign-cloud domains and arbitrary custom gateway endpoints are not configured in this version. Private networking must make the configured resource hostname reachable from the desktop; Agentic RAG does not change firewalls or network access.

For Microsoft authentication, the identity needs the relevant service roles. Search index creation commonly requires **Search Service Contributor**; uploading/querying content requires **Search Index Data Contributor**. Read-only consumers can use **Search Index Data Reader**. Search must allow role-based data access. These permissions are separate from a subscription's generic Contributor role. See [Search role permissions](https://learn.microsoft.com/en-us/azure/search/search-security-rbac).

Azure OpenAI inference needs an appropriate role such as **Cognitive Services OpenAI User**. Document Intelligence/Vision require the applicable Cognitive Services data permissions; private Blob uploads require Blob data write access. Your administrator should scope roles to the existing resources. Agentic RAG never grants them. See [Azure OpenAI keyless access](https://learn.microsoft.com/en-us/azure/developer/ai/keyless-connections) and [Azure AI role definitions](https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles/ai-machine-learning).

## Extract, inspect and publish

Import a supported source in **Source library**. In **Processing studio**, select the Azure workflow and your saved workspace. Choose description or multimodal retrieval. Azure entity extraction is fixed to `prebuilt-layout`; local parsing and LLM layout detection are not used as fallbacks.

Choose an optional page range and Layout features, then start extraction. The review panel shows the file, endpoint, target model, selected operations and configured rates. If visual descriptions are enabled, it also identifies the separate model that will receive visual crops and nearby text **after** Azure extraction. No document is sent by simply selecting a profile or opening a plan.

Agentic RAG submits the file once, polls the returned operation, validates its result address before forwarding authentication, and saves the full returned JSON locally. Inspect or download that JSON from Processing or Azure workspace. The inventory maps Azure paragraph roles, tables/cells, figures/captions, formulas, selection marks, sections and geometry to source references. Word/line details, styles and other returned fields remain in raw JSON. PDF page previews and table crops render the source regions Azure identified; they do not detect additional entities locally. Azure figures include charts but do not guarantee a separate chart classification. Optional visual descriptions are labeled model-generated.

Review the returned page coverage. Select preprocessing and fixed, recursive, document, semantic or agentic chunking. Preview chunks before indexing. Agentic chunking plans boundaries using the selected model; it cannot rewrite, omit, duplicate or reorder source units.

Start **Build vector index** and review its destination and unique index name. Agentic RAG embeds chunks, creates a new Search index, checks every upload result, and verifies document visibility before activating the version. A conflict, partial upload, cancellation or failure preserves the previous active index. Failed candidates and their names remain visible for cleanup in your Azure service. No existing index is overwritten or automatically deleted.

The agent uses hybrid keyword/vector queries against the pinned Azure index. An explicit page request also queries Azure with a page filter. Responses are checked against the immutable local chunk snapshot before being accepted. A Search failure is surfaced; there is no hidden local retrieval fallback. Clarification, memory, source inspection, bounded search refinement, human review and evaluation/model comparisons also work with Azure index versions.

## Formats and visual retrieval

Layout supports PDF, supported image formats, DOCX, XLSX, PPTX and HTML. It is not a universal parser for code repositories, recordings or arbitrary file formats. Legacy `.doc`/`.xls` files need conversion for the Azure workflow; the local workflow remains available for the broader source library. Office embedded images are not extracted by Layout, and spreadsheet table extraction has limitations. Export Office documents to PDF when visual layout matters. F0 analyzes at most two pages and has a 4 MB request limit. Agentic RAG displays partial or unverified coverage instead of claiming the whole document was extracted. See [Layout capabilities and input limits](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/layout?view=doc-intel-4.0.0).

| Retrieval mode | Embedding choices | Answer model input |
|---|---|---|
| Descriptions | Local BGE or provider text embeddings, including Azure OpenAI | Source text, table data and available visual descriptions |
| Multimodal | Azure Vision, local CLIP or Gemini multimodal embeddings | Retrieved text and original visuals if the answer deployment accepts images |

Azure OpenAI text embeddings do not embed pixels. Native Azure Vision text/image vectors use one pinned model version; long text is split into supported packets and aggregated without dropping words. Its regional availability and account access must be checked. See [Azure Vision image retrieval](https://learn.microsoft.com/en-us/azure/ai-services/computer-vision/how-to/image-retrieval).

A text-only answer model still receives usable text and descriptions; the UI warns that it cannot inspect images. Image understanding and new-image generation require separate model capabilities and quota. An Azure Search index can also be tested with your Gemini answer connection if you explicitly select it; this sends the selected answer evidence to Gemini.

## Source storage, monitoring and costs

Without Blob publication, the Search index is in Azure and original references remain on this desktop. If Blob publication is enabled, originals, Layout JSON and visual assets upload to your existing private container under document/index-scoped names. Retrieved source cards offer private cloud reference links through Agentic RAG; no public SAS links are created. Copying source files to Blob does not turn this desktop app into a hosted multi-user service. Its workspace database, memory and traces remain local.

Monitoring shows Layout submissions and status polls, Vision embeddings, Search index creation and document uploads, retrieval calls, Blob uploads and model calls. Each operation records its status, duration, resource, usage units where available and known cost estimate. Evaluation answer costs include Azure retrieval operations.

Enter your applicable rates in the profile. Layout estimates use returned pages; Azure billing page definitions and paid add-ons can differ. Vision uses request counts; Search has an optional query/reranking estimate. **Existing Search service capacity is billed separately by Azure** and its configured hourly rate is a reference, not an allocated per-run bill. Blob retention, storage transactions and unconfigured charges remain outside known totals. Unknown costs stay unpriced. Dollar caps require priced operations; use call limits for operations whose cost cannot be bounded. There are no automatic analyze retries or paid fallbacks after quota errors.

REST contracts are pinned to Document Intelligence `2024-11-30` and Search `2025-09-01`. See [Layout analyze](https://learn.microsoft.com/en-us/rest/api/aiservices/document-models/analyze-document?view=rest-aiservices-v4.0%20(2024-11-30)), [create Search index](https://learn.microsoft.com/en-us/rest/api/searchservice/indexes/create?view=rest-searchservice-2025-09-01), and [hybrid Search requests](https://learn.microsoft.com/en-us/rest/api/searchservice/documents/search-post?view=rest-searchservice-2025-09-01).

## Validation boundary

The Azure workflow has deterministic contract coverage for asynchronous extraction, original JSON, table/figure mapping, source coverage, endpoint and poll-address restrictions, encrypted keys, Microsoft auth/cache settings, cloud index publishing, failed candidates, scoped hybrid/page retrieval, evidence drift, private Blob uploads, evaluation integration and cost accounting. **No live Azure account or deployment was provided, so live Azure validation remains pending.** Access checks and model tests in the app are the next step after entering your real service details privately.

## Field setup and filtered retrieval

Processing now includes a field-by-field searchable/filterable/sortable/retrievable editor. Typed metadata fields are published separately, and required provenance is validated against a pinned chunk digest. Research combines keyword/vector search with metadata prefilters, and explicit filters survive every agent refinement. Existing Azure indexes created with an older schema require a new version for these fields. See [retrieval and context](retrieval.md) for local embedding choices, context caps and effort limits.
