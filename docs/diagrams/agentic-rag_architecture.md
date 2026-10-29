# Agentic RAG system architecture

![Agentic RAG multimodal agentic RAG architecture](../assets/agentic-rag_architecture.png)

[High-resolution PNG](../assets/agentic-rag_architecture.png) · [Scalable SVG](../assets/agentic-rag_architecture.svg) · [Editable draw.io](agentic-rag_architecture.drawio)

This diagram follows the service boxes, directional flows and evaluation/monitoring feedback layout in the AgilePlanner README. It uses Agentic RAG's actual stack and its black, grey, blue, purple and orange palette.

Blue arrows carry source data, extracted entities, metadata, embeddings and retrieved evidence. Purple arrows connect the user, Agentic RAG workspace, FastAPI agent and configured answer models; dashed purple arrows show evaluation and human-guided revisions. Orange arrows carry traces, usage and cost records.

The diagram distinguishes local parsing from Azure Document Intelligence, text embeddings from pixel embeddings, and local vector storage from an index in an existing Azure AI Search service. Context caps and investigation effort are separate from model capability. Audio/video contributes transcripts and timestamp references. Blob publication and image generation require explicit configuration. Connected provider options do not imply that every account or model was tested live. See [verification](../verification.md) for that boundary.

The files are generated together by `build_architecture.py`. The builder checks all text labels against their allotted width and canvas bounds, emits an editable draw.io document and a standalone SVG with embedded local icons, and uses `rsvg-convert` for the PNG when available. Regeneration overwrites the named exports. The SVG and draw.io can be edited without access to an external image service. Icon attribution is retained in [sources](../assets/icons/sources.md).

The model-connections service exposes Gemini free/paid accounts, OpenAI platform keys, Groq free/paid accounts and local Ollama (Qwen3 8B default), with Azure OpenAI retained for connected Azure resources. Model discovery, per-model verification, context reserves, usage and quota handling apply across the shared agent/evaluation workflow.
