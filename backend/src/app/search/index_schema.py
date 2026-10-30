"""Validated index field attributes. Schema changes create a new index version."""

from app.core.schemas import IndexFieldOptions

# name, type, defaults, supported flags, required attributes
FLAGS = ("searchable", "filterable", "sortable", "retrievable")

def spec(
    name,
    type,
    defaults=(),
    allowed=("filterable", "sortable", "retrievable"),
    required=(),
    label=None,
):
    return {
        "name": name,
        "type": type,
        "label": label or name.replace("_", " ").capitalize(),
        "defaults": {k: k in defaults for k in FLAGS},
        "allowed": list(allowed),
        "required": dict(required),
    }

SPECS = [
    spec(
        "title", "Edm.String", ("searchable", "sortable", "retrievable"), FLAGS, label="Chunk title"
    ),
    spec(
        "content",
        "Edm.String",
        ("searchable", "retrievable"),
        FLAGS,
        (("retrievable", True),),
        label="Chunk text",
    ),
    *[
        spec(k, "Edm.String", ("filterable", "sortable", "retrievable"), FLAGS)
        for k in ("source_name", "source_type", "section")
    ],
    spec(
        "pages",
        "Collection(Edm.Int32)",
        ("filterable", "retrievable"),
        ("filterable", "retrievable"),
    ),
    *[
        spec(
            k,
            "Collection(Edm.String)",
            ("filterable", "retrievable"),
            ("searchable", "filterable", "retrievable"),
        )
        for k in (
            "kinds",
            "sections",
            "source_names",
            "source_types",
            "source_paths",
            "sheets",
            "tags",
        )
    ],
    spec("has_visual", "Edm.Boolean", ("filterable", "retrievable")),
    *[
        spec(k, "Edm.Double", ("filterable", "sortable", "retrievable"))
        for k in ("time_start", "time_end")
    ],
    spec("ordinal", "Edm.Int32", ("sortable", "retrievable")),
]
SYSTEM_FIELDS = [
    {"name": "id", "type": "Edm.String", "key": True, "filterable": True, "retrievable": True},
    *[
        {"name": k, "type": "Edm.String", "filterable": True, "retrievable": True}
        for k in ("document_id", "snapshot_id", "source_hash")
    ],
    {"name": "metadata", "type": "Edm.String", "searchable": False, "retrievable": True},
]

def configure(options=None):
    options = options or {}
    lookup = {f["name"]: f for f in SPECS}
    unknown = set(options) - set(lookup)
    if unknown:
        raise ValueError("Unknown index fields: " + ", ".join(sorted(unknown)))
    result = {}
    for name, field in lookup.items():
        override = options.get(name, {})
        if isinstance(override, IndexFieldOptions):
            override = override.model_dump(exclude_none=True)
        else:
            override = IndexFieldOptions.model_validate(override).model_dump(exclude_none=True)
        attrs = {**field["defaults"], **override}
        if any(attrs[k] and k not in field["allowed"] for k in FLAGS):
            raise ValueError(f"{name}: this field type does not support the selected attribute.")
        if any(attrs[k] != v for k, v in field["required"].items()):
            raise ValueError(f"{name}: retrievable text is required for grounded answers.")
        result[name] = attrs
    if not any(v["searchable"] for v in result.values()):
        raise ValueError(
            "Enable at least one searchable text field for keyword and hybrid retrieval."
        )
    return result

def fields(options=None):
    attrs = configure(options)
    return [
        {**{"name": spec["name"], "type": spec["type"]}, **attrs[spec["name"]]} for spec in SPECS
    ]

def values(chunk):
    m = chunk.get("filter_metadata", {})
    return {
        **m,
        "source_name": next(iter(m.get("source_names", [])), ""),
        "source_type": next(iter(m.get("source_types", [])), ""),
        "ordinal": chunk.get(
            "ordinal", int(chunk["id"][1:]) - 1 if chunk.get("id", "")[1:].isdigit() else 0
        ),
        "section": next(iter(m.get("sections", [])), ""),
        "title": chunk.get("title", ""),
        "content": chunk["text"],
        "pages": chunk.get("pages", []),
    }

def keyword_text(chunk, options=None):
    vals = values(chunk)
    attrs = configure(options)
    parts = []
    for key, setting in attrs.items():
        if setting["searchable"]:
            value = vals.get(key, "")
            parts.extend(str(v) for v in value) if isinstance(value, list) else parts.append(
                str(value)
            )
    return "\n".join(parts)

def searchable_fields(options=None):
    return [k for k, v in configure(options).items() if v["searchable"]]

def retrievable_fields(options=None):
    return [k for k, v in configure(options).items() if v["retrievable"]]

def inspection(snapshot, extraction):
    options = snapshot["config"].get("index_fields", {})
    attributes = configure(options)
    elements = {element["id"]: element for element in extraction["elements"]}
    chunks = []
    for chunk in snapshot["chunks"]:
        stored = values(chunk)
        chunks.append(
            {
                **chunk,
                "searchable_values": {
                    name: stored.get(name, "")
                    for name, flags in attributes.items()
                    if flags["searchable"]
                },
                "keyword_text": keyword_text(chunk, options),
                "elements": [elements[id] for id in chunk["element_ids"] if id in elements],
            }
        )
    return {
        "id": snapshot["id"],
        "extraction_id": extraction["id"],
        "fields": [{**field, **attributes[field["name"]]} for field in SPECS],
        "chunks": chunks,
    }

def info(options=None):
    return {
        "fields": SPECS,
        "configured": configure(options),
        "system_fields": SYSTEM_FIELDS,
        "vector_field": "content_vector",
    }
