"""Bounded investigation and exact text-character budgeting for every agent stage."""

import json

EFFORT = {
    "low": {"queries": 1, "passes": 1, "calls": 5, "chunks": 4, "images": 2},
    "medium": {"queries": 2, "passes": 2, "calls": 12, "chunks": 8, "images": 4},
    "high": {"queries": 3, "passes": 4, "calls": 30, "chunks": 15, "images": 6},
}
PROFILES = {
    "small": {"context_chars": 12000, "max_output": 1500},
    "large": {"context_chars": 120000, "max_output": 6000},
}

def limits(question, connection):
    policy = EFFORT[question.effort]
    cap = min(
        (connection or {}).get("context_chars", 40000),
        question.context_chars or (connection or {}).get("context_chars", 40000),
    )
    local_cap = (
        connection.get("ollama_context_tokens", 16384) - connection.get("max_output", 3000) - 1024
        if connection and connection.get("provider") == "ollama"
        else None
    )
    return {
        **policy,
        "passes": min(policy["passes"], question.max_passes),
        "calls": min(policy["calls"], question.max_calls),
        "chunks": min(policy["chunks"], question.top_k),
        "context_chars": cap,
        "local_input_byte_cap": local_cap,
        "effort": question.effort,
        "unit": "characters of serialized text input; visual tokens are model-specific and tracked separately",
    }

def pack(system, header, payload, cap, byte_cap=None):
    """Drop optional context and shorten evidence while retaining valid JSON and IDs."""
    payload = json.loads(json.dumps(payload, ensure_ascii=False))
    removed = {
        "history": 0,
        "memory": 0,
        "catalog_values": 0,
        "evidence": 0,
        "evidence_characters": 0,
        "guidance_characters": 0,
    }

    def render():
        return header + "\n" + json.dumps(payload, ensure_ascii=False)

    for _ in range(2000):
        prompt = render()
        size = len((system + prompt).encode("utf-8"))
        if len(system) + len(prompt) <= cap and (byte_cap is None or size <= byte_cap):
            return (
                prompt,
                payload,
                {
                    "text_input_chars": len(system) + len(prompt),
                    "text_input_bytes": size,
                    "cap_chars": cap,
                    "local_input_byte_cap": byte_cap,
                    "trimmed": removed,
                },
            )
        ctx = payload.get("context", {})
        if ctx.get("history"):
            ctx["history"].pop(0)
            removed["history"] += 1
            continue
        if ctx.get("memory"):
            ctx["memory"].pop()
            removed["memory"] += 1
            continue
        fields = payload.get("catalog", {}).get("fields", {})
        values = [v for v in fields.values() if v.get("values")]
        if values:
            max(values, key=lambda v: len(json.dumps(v, ensure_ascii=False)))["values"].pop()
            removed["catalog_values"] += 1
            continue
        evidence = payload.get("evidence", [])
        long = [e for e in evidence if len(e.get("text", "")) > 160]
        if long:
            e = max(long, key=lambda e: len(e["text"]))
            n = len(e["text"])
            e["text"] = e["text"][: max(160, n // 2)]
            e["excerpt_truncated"] = True
            removed["evidence_characters"] += n - len(e["text"])
            continue
        if len(evidence) > 1:
            evidence.pop()
            removed["evidence"] += 1
            continue
        if len(ctx.get("guidance", "")) > 300:
            before = len(ctx["guidance"])
            ctx["guidance"] = ctx["guidance"][: max(300, before // 2)]
            removed["guidance_characters"] += before - len(ctx["guidance"])
            continue
        catalog = payload.get("catalog")
        if catalog:
            payload["catalog"] = {}
            continue
        raise ValueError(
            "The question, required scope and instructions exceed the selected text context cap. Shorten the question or increase the configured context budget (and Ollama runtime context for a local model)."
        )
    raise ValueError("Could not fit this request within the selected context budget.")
