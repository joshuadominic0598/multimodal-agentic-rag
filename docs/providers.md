# Model connections

Open **Connections & settings**. Agentic RAG's four initial providers are Gemini, OpenAI platform, Groq and local Ollama. Azure OpenAI remains available for the existing Azure workflow. You can save several profiles per provider and select different profiles for processing, answers and evaluation.

| Provider | Setup in Agentic RAG | Model choices | Account / cost behavior |
|---|---|---|---|
| Gemini API | Add your Google AI Studio API key | Starter choices, live paginated model inventory, or exact ID | Free and paid project keys use the same adapter. Choose the account label that matches your project. Google controls billing, access and quota. |
| OpenAI platform | Add your platform API key | Starter choices, models listed for your key, or exact API ID | API billing/credits are separate from ChatGPT or Codex subscriptions. Test the actual selected model. |
| Groq API | Add your Groq key | GPT-OSS 20B, GPT-OSS 120B and Qwen3.8 27B starter choices; live model inventory; exact IDs | Free or paid account label. Groq enforces model availability and account limits; Agentic RAG does not assume every listed model is free or usable. |
| Ollama · local | Keep Ollama running; no API key | Default **`qwen3:8b`**, other starter choices, installed chat-model inventory or an exact installed model ID | Requests stay on the configured local endpoint. Cloud-backed models are excluded. The ledger records zero API fees, excluding hardware and electricity. |
| Azure OpenAI | Existing resource endpoint and deployment name; resource key or supported Microsoft authentication | Your deployment IDs; the model catalog may contain names that differ from deployments | Existing Azure account billing and permissions apply. Document extraction and Search setup are described in [Azure workspace](azure.md). |

## Choose and verify a model

1. Choose the provider. Enter your key for a cloud connection, or your local Ollama endpoint.
2. Choose a starter model, click **Load my model list** / **Find installed models**, or enter an exact model ID. Model inventory requests do not generate answers. The app does not download Ollama weights automatically; install the desired model through Ollama first.
3. Set a descriptive profile name, account tier, text context budget and output limit. For Ollama, also set its runtime token window within the installed model's declared maximum and your available memory.
4. Save, then click **Test connection**. With image input enabled, Agentic RAG performs a separate red/blue image probe. A model's presence in the catalog does not guarantee inference access, remaining quota or image support.
5. Select **Use for chat**, or choose the profile independently in Processing studio, Research agent or Evaluation lab. **Add another model** creates a new profile and can reuse that provider's saved encrypted key. Editing a model or replacing its key clears previous verification; the original profile remains available when you add a new one.

The free/paid selector records your setup. It does not upgrade an account, verify billing, change rate limits or switch to paid inference automatically. Starter IDs can change or become unavailable; use live discovery and the connection test. Native provider errors are shown without credential echoes. A quota failure does not trigger a retry, a different provider or a paid fallback. Available Groq quota/reset headers are retained in the model trace.

## Images, tables and audio

**Model capability and account tier are separate.** Qwen3 8B and the default Groq GPT-OSS profile are configured as text-only. They can reason over extracted table rows and existing descriptions, but cannot inspect unseen image pixels. Select description mode for text-based answers, or choose and verify an image-capable model. Groq and Ollama adapters send actual image bytes when vision is enabled and supported by the selected model; starter models are not all vision models.

A vision answer model does not also become an image embedding engine. Keep embedding selection separate: **EmbeddingGemma / Qwen3 Embedding 4B** for local text, **CLIP** for local pixels, or a supported Gemini/OpenAI/Azure text embedding connection; Gemini multimodal and Azure Vision are separate pixel choices. Groq and Ollama chat connections cannot be selected as generic provider text embedding adapters. A local chat model with a cloud embedding index can still cause cloud retrieval-embedding requests: inspect the pinned index's engine and connection before assuming the whole workflow is offline.

Groq transcription uses `whisper-large-v3`; Gemini and existing OpenAI/Azure transcription remain supported. For an Ollama answer connection, choose **Local Whisper** to transcribe audio/video. Transcripts preserve links/timestamps to the recording. Groq and Ollama image generation are not implemented; use an eligible Gemini, OpenAI or Azure image-generation profile instead. Image understanding, embeddings, transcription and image generation each have separate access and quota requirements.

## Context and monitoring

Low / medium / high effort controls the bounded investigation, including searches, passes and model calls. The smaller/larger/custom preset sets input/output budgets; it does not choose a model or establish its token window.

For local generation, Agentic RAG configures Ollama's `num_ctx` and reserves output tokens plus a template allowance. UTF-8 input bytes conservatively bound text tokens. Research context is packed against both this reserve and the user's character cap; optional memory/history and evidence excerpts are trimmed while retaining valid JSON, source IDs and explicit truncation metadata. Agentic chunking batches preserve all source units within these bounds. Requests that still cannot fit are rejected before generation, without silent truncation. This conservative check may use less of a model's token window than an exact tokenizer would. Image tokens are separate and cannot be inferred from text characters.

Every generated answer and JSON plan uses the same call ledger, context policy, source tools and evaluation path. The trace retains provider/model, latency, available token counts, known estimated cost, failures and reported quota headers. Unknown cloud pricing stays unpriced, even for a user-declared free tier. Local API-fee estimates exclude hardware, electricity, downloads and any separately configured cloud service.

## Provider references

- [Gemini account billing and tiers](https://ai.google.dev/gemini-api/docs/billing)
- [OpenAI model discovery](https://developers.openai.com/api/reference/resources/models/methods/list) and [GPT-4.1 Mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini)
- [Groq API compatibility](https://console.groq.com/docs/openai), [models](https://console.groq.com/docs/models) and [free/paid rate limits](https://console.groq.com/docs/rate-limits)
- [Ollama native chat](https://docs.ollama.com/api/chat) and [installed model inventory](https://docs.ollama.com/api/tags)
