# Index fields, hybrid retrieval and context

## Configure each field before building

Processing studio provides four attributes per field:

| Attribute | Behavior |
|---|---|
| Searchable | Add the text field to keyword matching. Local FTS5 uses BM25; Azure uses its text search index. |
| Filterable | Allow exact values or ranges to narrow eligible chunks before ranking. |
| Sortable | Make an eligible scalar field available for Azure service-side ordering. Collection fields cannot be sortable. |
| Retrievable | Return the field from the Azure Search API. Chunk text and required identity/provenance fields stay retrievable for grounded answers and validation. |

Supported fields include chunk title/content, source name/type, section, pages, element types, section/source/path/sheet collections, tags, visual presence and recording times. Different Azure types support different flags; unsupported combinations are disabled in the UI and rejected by the backend. At least one text field must remain searchable. Reserved document/index/source identity fields and vectors have fixed settings. Source JSON metadata contains a chunk digest and provenance references rather than duplicating the full text/metadata payload.

Each build pins the field choices, source, extraction, chunks and embedding configuration. A field change creates a new index version; it does not mutate a working index. Azure applies all four attributes to the published schema. The local backend honors searchable/filterable choices; retrievability and service-side ordering are Azure Search attributes. Original documents and element metadata remain inspectable in Agentic RAG; field attributes are not access-control or redaction rules.

## Metadata filters and hybrid search

Research defaults to **keyword + vector retrieval**. The agent can also use keyword-only or vector-only retrieval for an explicit comparison. An optional keyword string pins the lexical side while the agent refines the semantic query.

Filters support pages/ranges, element types, sections, source names, file types, repository paths, workbook sheets, index tags, visual presence, recording time ranges and exact scalar field matches. Values come from the selected immutable index. Different fields combine with AND; selections within a field combine with OR. The agent may add narrower filters explicitly requested in the question. It cannot remove a user's selected constraints during refinement. Clarification retains the original retrieval scope.

Local retrieval restricts both vector candidates and BM25 matches to eligible chunks before taking the ranked candidate limits, then fuses them using reciprocal-rank fusion. Azure sends the same typed predicates as an escaped global OData filter, with `search` and `vectorQueries` in one request and `vectorFilterMode=preFilter`. Mandatory document/index/source scope is always added. Returned evidence is checked against the pinned chunk digest and active filter predicates. An explicit page inspection also retains all selected filters. No-match results do not trigger unfiltered retrieval or a cloud fallback. See [Azure hybrid queries](https://learn.microsoft.com/en-us/azure/search/hybrid-search-how-to-query) and [vector filtering](https://learn.microsoft.com/en-us/azure/search/vector-search-filters).

Old local indexes can derive metadata from their saved extraction without rewriting their fingerprint. Earlier Azure indexes require a new build for the richer field schema; the app reports that requirement before making a filtered request. Existing versions remain available.

Monitoring records the retrieval method, filters, keyword string, rank fusion, matches and available keyword/vector ranks. Ground-truth JSON cases may pin `filters`, `search_mode` and `keyword_query` so comparisons use the same retrieval scope.

## Two local text embedding profiles

Agentic RAG mirrors the AgilePlanner choices:

| Profile | Model | Suggested chunk cap / overlap |
|---|---|---|
| Smaller | EmbeddingGemma via local Ollama | 1,000 / 200 characters |
| Larger | Qwen3 Embedding 4B via local Ollama | 3,000 / 500 characters |

These are character sizes, not token windows. Selecting a profile sets the suggestions; users may adjust chunk size afterwards. The model is pinned per index and reused for query vectors. A model change requires rebuilding. The local URL is restricted to loopback or `host.docker.internal`, API keys are not sent, and native Ollama embedding calls disable silent truncation. If an input exceeds model capacity or the service/model is missing, the operation fails explicitly. There is no cloud fallback. Local API fees exclude hardware/electricity; local calls appear in Monitoring.

EmbeddingGemma and Qwen3 are **text embedding models**: they handle source text, extracted table rows and generated visual descriptions. They do not embed image pixels. Choose **multimodal mode** with local CLIP, Azure Vision or Gemini multimodal embeddings for actual images, charts and table-preview pixels. These modalities remain explicit in the UI. See [EmbeddingGemma](https://ollama.com/library/embeddinggemma), [Qwen3 Embedding 4B](https://ollama.com/library/qwen3-embedding:4b), and the [native embedding API](https://docs.ollama.com/api/embed).

## Model capacity, context and effort

Select the actual answer connection separately from the embedding profile. In Connections, the smaller-model preset suggests a 12,000-character text input cap and 1,500 output tokens; the larger-model preset suggests 120,000 characters and 6,000 output tokens. Custom values are supported. A preset configures limits; it does not change a model's actual capabilities or provider window.

Research can lower the text cap per question. The effective cap is the smaller of the requested cap and saved connection cap. Agentic RAG counts system instructions plus the complete assembled text payload, including the question, history, memory, metadata catalog and evidence. Planning, evidence assessment and final synthesis each receive a valid JSON packet within that cap. Optional history, memory and catalog entries are reduced, then evidence excerpts are shortened or omitted while source IDs remain valid. Required question/scope content is not silently dropped. If it cannot fit, the call is rejected before transmission. The trace reports the cap, actual text input size, trimming and source coverage.

| Effort | Search queries / pass | Max passes | Combined call ceiling | Max visual inputs |
|---|---|---|---|---|
| Low | 1 | 1 | 5 | 2 |
| Medium | 2 | 2 | 12 | 4 |
| High | 3 | 4 | 30 | 6 |

Explicit run limits can lower these ceilings. Retrieval, embedding and generation requests share the run call budget; the agent reserves space for assessment/final synthesis when it already has evidence. Effort controls investigation, not private native reasoning. Character caps are **not token-window guarantees**: model tokenization and image-token accounting differ. Output tokens are separately capped; provider-reported usage remains authoritative. Larger retrieval samples do not establish document-wide coverage.

Ground-truth cases may also include `effort` and `context_chars` to reproduce a context/effort policy. Model configurations and the application fingerprint remain pinned in evaluation records.
