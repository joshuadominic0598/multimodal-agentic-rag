# Evaluation

Import a UTF-8 CSV or JSON file in Evaluation lab after building an index. CSV headers must be distinct, and every row must match the header width. A JSON file can be an array of cases or an object containing `cases`.

| Field | Meaning |
|---|---|
| `question` | Required user query |
| `reference_answer` | Expected answer, checked independently of the generated candidate |
| `expected_chunk_ids` | Optional expected evidence IDs from the selected saved index; JSON list or comma-separated CSV field |
| `reference_status` | `verified`, `unverified` (default), or `behavior` |
| `should_clarify` | Whether this is a curated ambiguity test |
| `clarification_answer` | Optional scope supplied to ordinary factual cases |

A missing expected answer is accepted only for clarification cases. Unknown chunk IDs are rejected. Every import is immutable and has its own content hash, source hash and index fingerprint. To revise ground truth, download it, edit it and import a new snapshot. Importing does not rewrite previous experiments.

Choose one to four model connections and an optional common judge. The run freezes connection configuration, application fingerprint, prompt/guidance, saved index and ground truth. Models use fresh conversation state and do not read or update ordinary user memory. Test cases are independent in this initial implementation; ordered multi-turn benchmark replay is not implemented. All candidates use the same selected index and retrieval settings. A provider alias can change behind an unchanged model name; the snapshot does not identify private model weights.

Metrics are separate signals, not a blended grade:

- **Token F1**: bag-of-words overlap between actual and reference answers. Useful for a baseline; it is not factual correctness.
- **ROUGE-L F1**: longest common subsequence overlap over word tokens, capped at 3,000 tokens per side for local runtime bounds.
- **Context precision/recall**: intersection of actual retrieved chunk IDs and verified expected IDs. These are strict ID metrics, not semantic passage judgments. Missing/unverified expected evidence makes them inapplicable.
- **MRR and nDCG**: position of verified expected evidence in the actual ranked sources. Relevance is binary by expected chunk ID.
- **Citation validity**: emitted chunk IDs were supplied to the answer model. It does not establish support for every claim or complete citation coverage.
- **Clarification correctness**: whether observed clarify/answer behavior matches the case. Human review determines whether the question was useful.
- **Optional judge faithfulness**: a model's 0–1 estimate of answer support in actual retrieved contexts, with rationale. This is a model judgment, not a Ragas implementation, and it can share model biases. Judge errors are recorded separately.
- **Human score and note**: independently entered rating from 1 to 5. It is never synthesized by the system.
- **Operational signals**: completed/failed cases, measured latency, call count and priced/unpriced generation cost. Judge cost is visible in the parent evaluation's call ledger and is not silently folded into each answer's estimate.

Means include applicable cases only; applicability counts are retained. Quota/network failures are execution failures, not zero-quality answers. Missing metrics are null, not fabricated zeros. The dashboard keeps the expected answer, actual answer and actual retrieved sources together.

For a controlled model comparison, keep the exact benchmark/index/prompt/pass settings fixed. For a chunking or preprocessing experiment, build another index and create an appropriately rebound benchmark snapshot with reviewed expected IDs. Different source or benchmark versions limit a direct comparison; inspect the hashes before interpreting a change as an improvement.
