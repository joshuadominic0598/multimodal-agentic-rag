from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

FilterValue = Annotated[str, Field(min_length=1, max_length=2000)]

class SearchFilters(Strict):
    equals: dict[str, str | bool | int | float] = Field(default_factory=dict, max_length=15)
    pages: list[Annotated[int, Field(ge=1, le=100000)]] = Field(
        default_factory=list, max_length=100
    )
    page_from: int | None = Field(default=None, ge=1, le=100000)
    page_to: int | None = Field(default=None, ge=1, le=100000)
    kinds: list[FilterValue] = Field(default_factory=list, max_length=50)
    sections: list[FilterValue] = Field(default_factory=list, max_length=50)
    source_names: list[FilterValue] = Field(default_factory=list, max_length=50)
    source_types: list[FilterValue] = Field(default_factory=list, max_length=50)
    source_paths: list[FilterValue] = Field(default_factory=list, max_length=50)
    sheets: list[FilterValue] = Field(default_factory=list, max_length=50)
    tags: list[FilterValue] = Field(default_factory=list, max_length=50)
    has_visual: bool | None = None
    time_from: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    time_to: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered_ranges(self):
        for start, end in [("page_from", "page_to"), ("time_from", "time_to")]:
            if (
                getattr(self, start) is not None
                and getattr(self, end) is not None
                and getattr(self, start) > getattr(self, end)
            ):
                raise ValueError("Filter range start must not exceed its end.")
        return self

class Connection(Strict):
    name: str = Field(min_length=1, max_length=80)
    provider: Literal["openai", "azure", "gemini", "groq", "ollama"]
    model: str = Field(min_length=1, max_length=100)
    api_key: str = Field(default="", max_length=500)
    auth_mode: Literal["api-key", "entra", "azure-cli"] = "api-key"
    tenant_id: str = Field(default="organizations", pattern=r"^[A-Za-z0-9.-]{1,100}$")
    client_id: str = Field(default="", max_length=100)
    endpoint: str = Field(default="", max_length=400)
    embedding_model: str = "text-embedding-3-small"
    image_model: str = ""
    vision: bool = False
    free_tier: bool = False
    account_tier: Literal["unknown", "free", "paid", "local"] = "unknown"
    ollama_context_tokens: int = Field(default=16384, ge=2048, le=131072)
    input_price: float | None = Field(default=None, ge=0)
    output_price: float | None = Field(default=None, ge=0)
    cached_price: float | None = Field(default=None, ge=0)
    embedding_price: float | None = Field(default=None, ge=0)
    image_price: float | None = Field(default=None, ge=0)
    max_output: int = Field(default=3000, ge=128, le=12000)
    capacity_profile: Literal["small", "large", "custom"] = "custom"
    context_chars: int = Field(default=40000, ge=8000, le=200000)

class IndexFieldOptions(Strict):
    searchable: bool | None = None
    filterable: bool | None = None
    sortable: bool | None = None
    retrievable: bool | None = None

class Pipeline(Strict):
    mode: Literal["description", "multimodal"]
    strategy: Literal["fixed", "recursive", "document", "semantic", "agentic"] = "document"
    embedding: Literal[
        "local-text",
        "local-clip",
        "provider-text",
        "gemini-multimodal",
        "azure-vision",
        "ollama-small",
        "ollama-large",
    ] = "local-text"
    connection_id: str = ""
    embedding_connection_id: str = ""
    ollama_url: str = Field(default="http://127.0.0.1:11434", max_length=300)
    extraction_backend: Literal["local", "azure-document-intelligence"] = "local"
    index_backend: Literal["local", "azure-ai-search"] = "local"
    azure_profile_id: str = ""
    azure_plan_id: str = ""
    azure_pages: str = Field(default="", pattern=r"^(?:\d+(?:-\d+)?)(?:,\s*\d+(?:-\d+)?)*$|^$")
    azure_features: list[
        Literal[
            "ocrHighResolution", "formulas", "styleFont", "barcodes", "languages", "keyValuePairs"
        ]
    ] = []
    azure_semantic_rerank: bool = False
    index_fields: dict[str, IndexFieldOptions] = Field(default_factory=dict, max_length=30)
    metadata_tags: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=30
    )
    chunk_size: int = Field(default=1600, ge=200, le=6000)
    overlap: int = Field(default=150, ge=0, le=1000)
    strip_headers: bool = True
    deduplicate: bool = True
    mask_pii: bool = False
    describe_visuals: bool = True
    vision_layout: bool = False
    ocr: bool = False
    fetch_web_images: bool = False
    transcription: Literal["local", "provider"] = "local"
    whisper_model: str = Field(default="tiny", pattern="^(tiny|base|small|medium)$")
    max_calls: int = Field(default=80, ge=1, le=2000)
    budget_usd: float | None = Field(default=None, ge=0)

class Question(Strict):
    document_id: str
    index_id: str = ""
    connection_id: str = ""
    session_id: str = ""
    message: str = Field(min_length=1, max_length=6000)
    clarified: bool = False
    clarify_policy: Literal["always", "when_needed"] = "always"
    clarification_answer: str = Field(default="", max_length=3000)
    top_k: int = Field(default=6, ge=1, le=15)
    max_passes: int = Field(default=2, ge=1, le=4)
    max_calls: int = Field(default=8, ge=1, le=30)
    budget_usd: float | None = Field(default=None, ge=0)
    preview: bool = False
    generate_image: bool = False
    search_mode: Literal["hybrid", "keyword", "vector"] = "hybrid"
    keyword_query: str = Field(default="", max_length=1000)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    use_agent_filters: bool = True
    effort: Literal["low", "medium", "high"] = "medium"
    context_chars: int | None = Field(default=None, ge=8000, le=200000)

class Review(Strict):
    score: int = Field(ge=1, le=5)
    note: str = Field(default="", max_length=3000)

class AzureProfile(Strict):
    name: str = Field(min_length=1, max_length=80)
    auth_mode: Literal["api-key", "entra", "azure-cli"] = "api-key"
    tenant_id: str = Field(default="organizations", pattern=r"^[A-Za-z0-9.-]{1,100}$")
    client_id: str = Field(default="", max_length=100)
    document_endpoint: str = Field(min_length=1, max_length=400)
    document_key: str = Field(default="", max_length=500)
    document_tier: Literal["unknown", "F0", "S0"] = "unknown"
    search_endpoint: str = Field(min_length=1, max_length=400)
    search_key: str = Field(default="", max_length=500)
    index_prefix: str = Field(default="agentic-rag", pattern=r"^[a-z][a-z0-9-]{1,30}$")
    openai_connection_id: str = ""
    vision_endpoint: str = Field(default="", max_length=400)
    vision_key: str = Field(default="", max_length=500)
    blob_endpoint: str = Field(default="", max_length=400)
    blob_key: str = Field(default="", max_length=500)
    blob_container: str = Field(
        default="agentic-rag-sources", pattern=r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$"
    )
    publish_assets: bool = False
    document_price_per_1000_pages: float | None = Field(default=None, ge=0)
    vision_price_per_1000_requests: float | None = Field(default=None, ge=0)
    search_price_per_1000_queries: float | None = Field(default=None, ge=0)
    search_hourly_estimate: float | None = Field(default=None, ge=0)
    timeout_seconds: int = Field(default=900, ge=30, le=3600)

class AzureSignIn(Strict):
    tenant_id: str = Field(default="organizations", pattern=r"^[A-Za-z0-9.-]{1,100}$")
    client_id: str = Field(default="", max_length=100)

class AzurePlanRequest(Strict):
    document_id: str
    stage: Literal["extract", "index"]
    config: Pipeline

class Settings(Strict):
    active_connection: str = ""
    guidance: str = Field(max_length=12000)
    memory_enabled: bool = True

class ImportPath(Strict):
    path: str

class ImportURL(Strict):
    url: str = Field(max_length=2000)

class Memory(Strict):
    document_id: str
    text: str = Field(min_length=1, max_length=3000)

class Evaluation(Strict):
    dataset_id: str
    connection_ids: list[str] = Field(min_length=1, max_length=4)
    judge_id: str = ""
    max_calls: int = Field(default=10, ge=1, le=30)
    max_passes: int = Field(default=2, ge=1, le=4)
