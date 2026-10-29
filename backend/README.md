# Backend

The Python package lives under `backend/src/app/`, with its tests in `backend/tests/`. It runs extraction, preprocessing, chunking, indexing, model adapters, the research agent, memory, monitoring and evaluation. The product walkthrough is in the [main README](../README.md); the browser interface is documented in the [frontend README](../frontend/README.md).

## Code map

```text
backend/
├── src/app/
│   ├── main.py        ASGI composition and router registration
│   ├── api/           Thin HTTP routes and local-origin policy
│   ├── services/      Imports, connection probes, jobs and monitoring
│   ├── ingestion/     Extraction, preprocessing and index construction
│   ├── agents/        Research, context management and evaluation
│   ├── search/        Metadata, filtering and local embedding profiles
│   ├── integrations/  Model providers and Azure service adapters
│   ├── core/          Shared schemas, storage, paths and URL policy
│   └── cli.py         Desktop start/stop entry point
└── tests/             Behavioral and provider contract tests
```

Routes parse requests and delegate workflows. Services coordinate existing functions; integrations own provider/service protocols. Shared storage, schemas and URL rules stay independent of HTTP routes. The existing `app.main:app` entry point and HTTP contract remain unchanged.

## Open

Double-click **scripts/start.command** or open **http://127.0.0.1:8020** when the app is running. Double-click **scripts/stop.command** to stop it. Run these commands from your cloned project directory.

In this desktop installation, your Gemini development connection is saved locally, and a keyless **Ollama · Qwen3 8B** profile is ready to test. **Connections & settings** supports the four initial providers: **Gemini (free/paid), OpenAI platform API, Groq (free/paid), and local Ollama**, plus the existing Azure OpenAI workflow. Choose starter models, load the current provider/installed inventory, or enter an exact model ID. Save multiple model profiles for chat, processing and evaluation. See [model connections](../docs/providers.md) for setup and capability limits. API keys are write-only, encrypted using a separate workspace key, and excluded from source control. No provider key is bundled with a source export.

## Supported sources and practical boundaries

- **PDF:** native text spans/layout, embedded images, detected tables and page previews. Native chart recognition is heuristic; vector drawings are labeled figure candidates. Vision layout recognizes and crops visible elements; OCR uses Tesseract if installed. Check extraction against the original, especially complex diagrams and scanned pages.
- **Word DOCX/DOC:** ordered paragraphs/headings/tables, embedded images, chart data, headers/footers, footnotes, comments and additional `document*.xml` parts. Pagination depends on Word and is not invented. Legacy `.doc` is converted locally using macOS textutil; on other systems, convert it to `.docx` first. Inspect converted layout and floating objects against the original.
- **Excel XLSX/XLS, CSV/TSV:** cell data, row groups, sheet names, formulas and cached values. XLSX embedded images and supported chart data are retained. Chart previews are explicitly reconstructed from saved data; they are not screenshots from Excel. Legacy XLS extracts cells, with chart/image limitations disclosed. Formulas/macros never execute.
- **TXT/Markdown/HTML/code/repository files/Jupyter:** content is parsed as data. Notebooks retain saved text/image outputs without executing cells. Folder imports exclude hidden files, secrets, environments and build artifacts. HTML scripts never run; inline images and imported local image files are supported. An optional checkbox fetches public images from the same webpage origin. Cross-origin images remain references.
- **Images:** PNG, JPEG, WebP, GIF, TIFF, BMP are converted to inspectable PNG assets. Animated/multipage image inputs use the first frame.
- **Audio/video:** common formats are decoded with bundled FFmpeg and transcribed in five-minute packets using local Whisper or the selected provider. Segments retain times and links to the original recording. Video visuals are not indexed, as requested. Speech recognition can be imperfect.
- **PPTX:** additional basic text/image extraction is included, with slide references.

Limits: 250 MB per import; source-folder imports up to 2,000 supported files and 250 MB total, with 5 MB per nested file; local PDF extraction up to 500 pages (Azure Layout: up to 2,000, subject to tier/coverage); workbook extraction up to two million cells; ground truth 1–100 cases and 3 MB. These are local app limits, separate from provider quotas. Very large documents can need more calls/time; inspect run limits before processing.

## Index fields, hybrid search and context

Configure each index field as **searchable, filterable, sortable or retrievable** before building. The app validates supported combinations and preserves the fields needed for grounded responses. Choose filters for pages, element types, sections, sources, sheets, tags or recording times. Hybrid search combines keyword/BM25 and vector similarity inside that scope; agent refinements cannot widen user-selected filters.

For local text embeddings, use the same smaller **EmbeddingGemma** or larger **Qwen3 Embedding 4B** profiles as AgilePlanner. These embed text and extracted table data. For image/chart/table-preview pixels, choose CLIP, Azure Vision or Gemini multimodal embeddings explicitly.

Choose the actual answer model, a smaller/larger/custom capacity preset, **low / medium / high effort**, and an optional per-question text context cap. Agentic RAG budgets instructions, conversation, metadata and evidence together for every agent stage. Character limits, output token limits and visual-token usage stay distinct. See [retrieval and context](../docs/retrieval.md) for field semantics, embedding profiles, effort limits and evaluation controls.

## Memory, skills and tools

Short-term memory is the recent conversation in a document/index-scoped chat. Long-term memory stores user-declared preferences and a visible summary of the latest research question. It is not promoted into source evidence. Inspect, add or delete memory under Research; disable memory in Settings. Conversation deletion removes active context while monitoring records remain local until the workspace data is removed.

Built-in skills cover document research, visual analysis, tables, media citations and evidence-aware memory. Tools expose bounded index search, element inspection, scoped memory, evidence assessment and explicitly requested image generation. The workflow is a bounded state machine in `backend/src/app/agents/research.py`; it does not require a hosted orchestration service or execute imported source code. Agentic chunking uses a model-generated partition of source-unit IDs; validation rejects omissions, duplication, reordering and unknown IDs. Source text stays verbatim. All visuals receive their own searchable vectors rather than being hidden behind a combined chunk's first image.

## Cost and observability

All cloud operations share a call limit and a usage ledger. Provider-reported input, output, cached and available thought-token usage remain separate from pricing. Set the applicable per-million-token and optional per-image rates in the connection editor. **Unknown usage/prices stay unpriced; they are not zero.** Free-tier labels are user declarations, not independently verified invoices. Quota errors never trigger automatic retries or a paid fallback.

Optional dollar caps use estimates and require pricing for every operation. Visual input and transcription costs cannot be bounded reliably with text rates, so those operations require the call limit instead of a dollar cap. Estimates do not guarantee an invoice ceiling. Local embedding/transcription estimates exclude hardware, electricity and initial downloads.

Monitoring retains local question/evidence/model previews, which may contain document data. PII masking affects indexed text, not original files, page images, transcripts sent to providers, pre-masking extraction or old traces. It is a heuristic, not complete anonymization. The interface makes cloud-transfer boundaries visible. The server binds to loopback, validates local origins, rejects external Host headers, blocks public URL imports targeting private IPs and serves imported HTML/code as downloads. Treat this as a personal desktop workspace, not an authenticated shared server.

## Evaluation

See [evaluation](../docs/evaluation.md) for schema, metrics and controlled comparisons, [architecture](../docs/architecture.md) for the component map, and [verification](../docs/verification.md) for the actual test evidence and limitations.

## Development

Python 3.11+; this installation uses Python 3.12. On this Mac the environment and dependencies are installed. For a fresh copy, run `scripts/setup.command`, then `scripts/start.command`. First use downloads local BGE/CLIP/Whisper weights to ignored runtime storage. No cloud fallback is used if a local model is unavailable.

```sh
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8020
```

Set `AGENTIC_RAG_PORT` to use another port and `RAG_DATA_DIR` to use a different data directory. Keep each running workspace on its own port/directory. API documentation is at `/api/docs`; mutations require `X-Agentic-RAG-Client: local-workspace`.

## References

The implementation is original; the following resources informed its design. No external repository code was copied.

- [AhmedAl93: multimodal-agentic-RAG](https://github.com/AhmedAl93/multimodal-agentic-RAG): agentic/semantic chunking, descriptions with original visual references, evidence sufficiency and query refinement.
- [Agentic RAG 101](https://github.com/aishwaryanr/awesome-generative-ai-guide/blob/main/resources/agentic_rag_101.md): bounded planning, retrieval and self-assessment.
- [Alijanloo: MultiModalRag](https://github.com/Alijanloo/MultiModalRag): layout structure, visual grounding and modular processing.
- The supplied six-page workshop PDF: extraction/summarization, configurable preprocessing, five chunking strategies, hybrid retrieval and source references. Document content was treated as reference material, not instructions.
- Local AgilePlanner documentation: scoped memory, hybrid search, evidence budgeting, local observability, immutable evaluation inputs, independent human review and explicit unpriced costs.
- [OpenAI vision](https://developers.openai.com/api/docs/guides/images-vision), [OpenAI embeddings](https://developers.openai.com/api/reference/resources/embeddings/methods/create), [OpenAI image generation](https://developers.openai.com/api/docs/guides/image-generation).
- [Azure Responses](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/responses), [Gemini embeddings](https://ai.google.dev/gemini-api/docs/embeddings), [Gemini audio](https://ai.google.dev/gemini-api/docs/audio), [FastEmbed image embeddings](https://qdrant.github.io/fastembed/examples/Image_Embedding/).

## Azure backend

Entity extraction uses Document Intelligence `prebuilt-layout`. The raw JSON is retained before common preprocessing and chunking. Publication creates a new index in an existing Azure AI Search service; user field attributes, hybrid retrieval, metadata filters and optional semantic reranking are pinned to the index. Optional Azure Vision and private Blob references are separate adapters. The same agent, context manager, monitoring and evaluation operate over the remote index. Read the [Azure setup and service contracts](../docs/azure.md) and [architecture](../docs/architecture.md).

## Diagram sources

Regenerate both architecture views from the project root with `.venv/bin/python docs/diagrams/build_architecture.py` and `.venv/bin/python docs/diagrams/build_azure_flow.py`. Sources, SVG, PNG and editable draw.io exports use the same dark palette. The builders check label widths and canvas bounds.

## Clone this project

```sh
git clone https://github.com/joshuadominic0598/multimodal-agentic-rag.git
cd multimodal-agentic-rag
./scripts/setup.command
./scripts/start.command
```

The launch scripts target macOS with zsh. For another environment, create a Python virtual environment, install the project with `python -m pip install -e .`, and run the documented Uvicorn command bound to loopback. Install Ollama separately when using local models. Azure resources and model deployments must already exist in your account.

## Formatting and packaging

Dependencies and package discovery are declared once in `pyproject.toml`. Install the development tools with `.venv/bin/python -m pip install -e '.[dev]'`.

```sh
.venv/bin/python scripts/format_code.py
.venv/bin/python scripts/format_code.py --check
.venv/bin/python -m pytest -q
.venv/bin/python -m build --outdir work/dist
```

The formatting command applies Ruff import/format rules and then enforces one blank line between logical sections without changing multiline strings. Comments explain constraints, not individual operations. Keep module boundaries functional; do not add wrapper classes or interfaces without a concrete need.

The built package includes the frontend and benchmark templates. Source checkouts use `frontend/` and `docs/examples/`; installed wheels locate their bundled resources under the environment's shared data directory. `RAG_DATA_DIR` keeps the runtime workspace independent of package layout. The default remains the checkout's ignored `data/` directory.
