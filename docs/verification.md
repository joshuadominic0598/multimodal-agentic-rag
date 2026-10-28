# Verification · 24 October 2026

This is a working personal desktop implementation. The results below describe the tested sources and connections, not a general accuracy guarantee.

## Automated checks

**131 tests passed**, covering source provenance, hybrid index isolation, complete chunk offset coverage, invalid agent plans, visual chunk separation, atomic activation, cancellation, DOCX parts/headers/tables, legacy DOC conversion on macOS, XLSX rows/formulas/chart previews, HTML scripts and table assets, notebook saved outputs, native PDF previews, scoped clarification, conversation isolation, page-scoped evidence coverage, invalid citations, image-generation failure handling, restored chat evidence, ground-truth validation, unverified-reference applicability, controlled comparison snapshots, provider wire formats, encrypted credentials, capability verification invalidation, origin/path/URL boundaries, usage accounting, budget limits and quota handling.

The tests use deterministic provider simulations and small fixtures. OpenAI, Groq and Azure were not called live. Dependency consistency and frontend syntax checks passed. Python's PDF bindings emit upstream deprecation warnings; the test run has no failures.

## Live checks

| Check | Observed result |
|---|---|
| Supplied Gemini credential | Authenticated model listing; text and red/blue image-understanding probes succeeded |
| Development model | Gemini 2.5 Flash was listed but rejected for new users; Gemini 3.1 Flash Lite was successfully tested and configured |
| Workshop PDF | Native extraction and six-page vision layout completed. Current reviewed inventory has 101 elements; cached model coordinates were normalized into original-source crops in a new extraction revision |
| Agentic chunking | Model planned source-unit groups; coverage/order validation passed; 60 chunks were indexed |
| Description retrieval | A local BGE text index was created and retained as an earlier version |
| Multimodal retrieval | A local CLIP index embedded actual visual assets and text. Image and text vectors share a 512-dimensional space |
| Gemini multimodal embeddings | A combined pixel/text request returned a 768-dimensional Gemini Embedding 2 vector |
| Long inputs | BGE and CLIP processed long Latin/non-Latin input through tokenizer-bounded packets and returned valid vectors |
| Scoped answer | A live answer listed all five strategies on page 5, with valid chunk citations, 12 source chunks and six attached visual inputs |
| Browser workflow | Library, processing configuration, clarification, a live cited answer, saved-chat reopening and original page/visual links were inspected in the local interface |
| Responsive layout | The available 501-pixel browser viewport had no horizontal document overflow after correction; a separate wide desktop browser was not available for visual QA |
| Local audio | A synthetic 9.4-second recording was transcribed into three timestamped segments and indexed. A speech-library/PyAV incompatibility was found and fixed by pinning PyAV 16.1.0 |
| Local video | A synthetic MP4 with the same speech was transcribed and indexed; chunks retain the original video path and timestamps |
| Comparison flow | A shared three-case benchmark ran against Gemini 3.1 Flash Lite and Gemini 3.8 Flash. The former completed both factual answers and a clarification case. The latter completed the clarification case but encountered provider HTTP 503 failures on two factual cases; these failures are separate from quality metrics |
| Updated benchmark | After the page-scope retrieval correction, the three-case benchmark completed with Gemini 3.1 Flash Lite: two factual answers and one clarification. The optional same-model evidence judge returned 1.0 faithfulness for each factual answer; this is a small self-judged benchmark, not independently measured general accuracy |
| Image generation | A live Gemini image-generation request hit HTTP 429/quota limits. No paid fallback or automatic retry was attempted. The UI records this limitation separately from successful image analysis |
| Desktop launcher | App start, stop, restart and loopback health checks passed |

Historical comparisons retain their own prompt/index/dataset/application fingerprints. Subsequent parser-only changes for HTML table previews and legacy DOC conversion were verified locally with targeted fixtures; they did not trigger additional cloud answer generation. Source assets and earlier indexes remain intact.

## Limits and pending validation

- OpenAI and Azure require live user testing with the user's API credentials, account access and Azure deployments. Contract simulations do not establish account availability.
- Image generation needs an eligible model and quota. The successful vision/embedding checks do not establish image-generation access.
- Local OCR requires Tesseract, which was not installed/tested in this environment. Vision layout is available as the tested PDF alternative.
- Legacy XLS, large/complex Word workbooks, multilingual speech, very long media, adversarial files and large source repositories need representative user testing. Synthetic English speech tests establish the media path, not transcription quality across these cases.
- Native PDF table/layout recognition and model-generated layout/descriptions can miss or misclassify elements. Inspect extraction and coverage notices before indexing.
- The application retains unknown costs as unpriced. No independently verified billing total is claimed. Provider quota and account billing remain authoritative.
- The server is a loopback personal workspace. It is not a multi-user hosted product, an access-controlled network service or a certified security boundary.

## Dark theme update

The interface now uses a fixed dark color scheme, in the requested order: black, grey, blue, purple, orange. UI surfaces, inputs, tables, code blocks, notifications, dialogs and native media/file controls use dark styling. The Agentic RAG icon and browser theme color were updated to match.

All six screens were inspected in the running browser. Computed styles confirmed dark backgrounds on settings and evaluation controls and the local file-browser dialog; no white UI color declarations remain. This presentation-only change did not alter backend behavior or trigger additional model calls.

## Azure workflow update

The additional Azure checks use mocked service transports and SDK credentials, not live Azure resources. They cover encrypted/write-only service keys; validation errors without credential echoes; resource endpoint and analysis-location restrictions; explicit single-use plans bound to source/settings; one analyze submission and bounded polling; raw Layout JSON and table/figure/source-region mapping; free-tier partial coverage; unsupported-source rejection; cancellation; successful Search index publication; upload failure/conflict preserving the previous index; cloud-only hybrid/page retrieval and evidence-drift rejection; Azure Vision text packet coverage and image bytes; Microsoft auth scopes and OS-encrypted cache settings; pinned resource identity; private Blob uploads and reference links; shared agent/evaluation integration; cloud usage and budget accounting.

Microsoft sign-in is simulated through the SDK contract. No real tenant login, permission grants, Azure extraction, Search writes, Azure Vision calls, Blob uploads or Azure OpenAI inference occurred. The in-app flow and dark Azure screens are inspected separately in the running browser. Live validation awaits the user's existing resource details and account permissions.

Final running-app checks confirmed the dark Azure workspace, Microsoft/service-key form switching, unique field labels/IDs, no horizontal page overflow at the available 501-pixel viewport, native Azure Vision in the embedding menu, a destination review with the selected model disclosure, and Azure service monitoring. Opening and dismissing the review made zero Azure requests. The temporary local UI fixture was removed. Existing source indexes remained active; a running-app local retrieval preview returned all 12 indexed chunks from workshop page 5 without any new model or Azure calls. With no priced historical model calls, the known-cost subtotal now displays Unpriced rather than zero.

## Field schema, filtered retrieval, embedding profiles and context update

The expanded suite has **97 passing tests**. Added coverage checks index field attribute validation, unsupported collection sorting, required grounded-answer fields, field-driven lexical indexing, Azure publication flags and search-field/return-field selection, metadata predicates and escaped OData, prefiltering before candidate limits, keyword-only requests without embeddings, vector-only requests, pinned keyword terms, disabled filters, older Azure schema rebuild notices, agent filter intersections, clarification scope/context preservation, exact context-packet bounds, investigation effort, private Ollama endpoints and model-specific query prefixes.

Live local embedding sanity checks succeeded for the two installed Ollama models: EmbeddingGemma returned 768-dimensional vectors and Qwen3 Embedding 4B returned 2,560-dimensional vectors. For both, a solar-energy question ranked its related passage above an unrelated database passage. This establishes connectivity, dimensions and a small relevance check, not broad quality.

A running-app keyword preview filtered workshop page 5 to section headers and returned four low-effort matches without a model-generation request. A separate live Gemini low-effort answer retrieved five filtered source chunks for page 5 and used three provider calls. The planning, assessment and final text packets were 5,591, 1,537 and 4,900 characters respectively, below the selected 12,000-character cap. The answer listed all five strategies; one grouped citation used nonstandard formatting, so the numeric-ID citation check should not be treated as a complete formatting or claim-support guarantee. Visual token usage remains separate from text-character limits.

The new README architecture uses the AgilePlanner service-box/flow/feedback layout, with the label Agentic RAG workspace. Its 114 text labels were checked for width and canvas bounds. SVG, PNG and editable draw.io exports were generated together. The diagram describes implemented configuration paths; live Azure/OpenAI validation still awaits real user resources and keys.


## Four initial model providers

The connection editor now exposes Gemini, OpenAI platform, Groq and local Ollama first, retaining Azure OpenAI as the additional existing-resource option. Each supports multiple saved model profiles, starter choices, exact model IDs and live provider/installed model discovery. Gemini/Groq free and paid account labels do not alter billing or imply zero pricing. Encrypted-key reuse when adding another model is restricted to the same provider.

The 34 additional automated checks cover both cloud account labels; write-only credentials; key replacement invalidating verification; an in-flight test refusing to verify a subsequently changed model; keyless/idempotent Qwen3 8B setup; provider-change key isolation; private Ollama endpoints; cloud-backed/embedding-only local model rejection; installed inventory; paginated Gemini inventory; fixed OpenAI/Groq origins; model discovery without saving credentials; safe profile cloning; native Groq chat/JSON and native Ollama chat/JSON wire formats; image-byte payloads for compatible models; local input/output token counts and zero API fees; UTF-8 context packing and token reserves; unsupported-operation rejection; quota headers and safe errors. Existing checks also cover the full agent, indexing, evaluation and Azure paths. All 131 tests passed, frontend syntax validation passed, and dependency consistency passed.

Live verification:

- **Ollama `qwen3:8b`:** already installed on this Mac. The connection test returned “Connection ready.” Native JSON planning/assessment and final synthesis completed through the shared agent against the workshop PDF. The answer listed all five strategies on page 5 with five valid chunk citations and original source references. Three local generation calls recorded provider input/output token counts and zero API fees. Final-server packets used 7,120 / 2,078 / 6,202 text characters within the 12,000-character cap and the separate 13,860-byte local reserve; hardware/electricity are excluded. Qwen3 8B was used as a text-only answer model over the pinned local index.
- **Local agentic chunking:** one native Qwen3 8B call grouped six extracted elements into three topic chunks in an isolated test workspace. Source-unit coverage and order validation passed.
- **Gemini:** authenticated model inventory returned 60 entries and included the existing development model. Earlier Gemini text, image understanding, embeddings and cited-answer checks remain recorded above. No paid Gemini account was used; paid-mode connection behavior is verified through shared-adapter contracts, not billing-account access.
- **Browser:** all five provider choices are present; Groq model selection accepts namespaced GPT-OSS IDs; Gemini free/paid choice and context presets render correctly; Ollama is keyless, defaults to Qwen3 8B, lists eight installed chat choices and excludes the two embedding-only models from the answer picker. The active Gemini profile and existing source/index records remain intact. No test OpenAI/Groq credential was saved in the user's workspace.
- **OpenAI, Groq and Azure inference:** contract simulations only. Live inference, account permissions, per-model capability and quota await the user's credentials/resources. Catalog visibility and starter choices do not prove account access.

The architecture PNG/SVG and editable draw.io source now include the four requested providers, Azure OpenAI, model choice, context and quota handling. The source export excludes runtime databases, credentials, originals, downloaded models and development scratch files.


## Product rename and initial repository · 29 October 2026

The product is now **Agentic RAG — Document Knowledge Studio**. The existing icon is byte-for-byte unchanged. User-facing text, source identifiers, launch messages, environment options, request headers, Azure index defaults and generated architecture assets use the current name. The main README is a product walkthrough; backend and frontend READMEs hold implementation/setup details. A separate Azure diagram covers Document Intelligence Layout, chunking, Search publication, filtered hybrid retrieval, Azure OpenAI, source references and optional services.

All **131 tests passed** after the rename; frontend syntax and launcher syntax checks passed. Source, Azure setup, connections and processing screens showed the current branding with no horizontal overflow. The three existing source files remained downloadable with unchanged SHA-256 hashes; only the two app-generated sample labels/file references were renamed. Existing model connections and index records were preserved. No new cloud generation or live Azure operations were performed for this presentation change.
