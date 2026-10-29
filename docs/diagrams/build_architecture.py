"""Regenerate Agentic RAG's SVG, editable draw.io and PNG architecture exports."""

import base64
import html
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

from PIL import ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/assets"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 3300, 2390
BG, LANE, BOX = "#090b11", "#111620", "#1a2231"
TEXT, MUTED, BLUE, PURPLE, ORANGE = "#e4e9f4", "#9ca8ba", "#68b8ff", "#b59aff", "#f0ad67"
parts = []
bounds = []
seq = 1
mx = ET.Element("mxfile", host="app.diagrams.net", version="24.7.17")
dia = ET.SubElement(mx, "diagram", name="Agentic RAG architecture", id="agentic-rag-system")
model = ET.SubElement(
    dia, "mxGraphModel", page="1", pageWidth=str(W), pageHeight=str(H), background=BG, grid="1"
)
tree = ET.SubElement(model, "root")
ET.SubElement(tree, "mxCell", id="0")
ET.SubElement(tree, "mxCell", id="1", parent="0")
font_root = Path("/System/Library/Fonts/Supplemental")

def vertex(x, y, w, h, style, value=""):
    global seq
    seq += 1
    node = ET.SubElement(
        tree, "mxCell", id=str(seq), parent="1", vertex="1", style=style, value=value
    )
    ET.SubElement(
        node, "mxGeometry", x=str(x), y=str(y), width=str(w), height=str(h), **{"as": "geometry"}
    )

def rect(x, y, w, h, fill=BOX, stroke="#354558", radius=16):
    parts.append(
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
    )
    vertex(x, y, w, h, f"rounded=1;arcSize=10;fillColor={fill};strokeColor={stroke};strokeWidth=2;")

def text(x, y, value, size=26, color=TEXT, bold=False, maxwidth=None, anchor="start"):
    family = "Arial Bold.ttf" if bold else "Arial.ttf"
    font = ImageFont.truetype(str(font_root / family), size)
    actual = font.getlength(value)
    left = x - actual / 2 if anchor == "middle" else x
    if maxwidth is not None and actual > maxwidth:
        raise ValueError(f"Text too wide: {value} ({actual}>{maxwidth})")
    if left < 0 or left + actual > W or y - size < 0 or y > H:
        raise ValueError("Label outside canvas: " + value)
    parts.append(
        f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" font-weight="{700 if bold else 400}" text-anchor="{anchor}">{html.escape(value)}</text>'
    )
    vertex(
        left,
        y - size,
        max(100, actual + 15),
        size * 1.4,
        f"text;html=0;fillColor=none;strokeColor=none;whiteSpace=nowrap;overflow=visible;spacing=0;fontFamily=Arial;fontSize={size};fontColor={color};fontStyle={int(bold)};",
        value,
    )
    bounds.append({"text": value, "x": left, "y": y - size, "width": actual, "height": size * 1.3})

def arrow(points, color=BLUE, label="", at=None, dashed=False):
    global seq
    parts.append(
        '<polyline points="'
        + " ".join(f"{x},{y}" for x, y in points)
        + f'" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" marker-end="url(#arrow{color[1:]})"'
        + (' stroke-dasharray="12 9"' if dashed else "")
        + "/>"
    )
    seq += 1
    node = ET.SubElement(
        tree,
        "mxCell",
        id=str(seq),
        parent="1",
        edge="1",
        style=f"edgeStyle=none;rounded=1;strokeColor={color};strokeWidth=3;endArrow=block;dashed={int(dashed)};",
    )
    geo = ET.SubElement(node, "mxGeometry", relative="1", **{"as": "geometry"})
    for name, point in [("sourcePoint", points[0]), ("targetPoint", points[-1])]:
        ET.SubElement(geo, "mxPoint", x=str(point[0]), y=str(point[1]), **{"as": name})
    if len(points) > 2:
        arr = ET.SubElement(geo, "Array", **{"as": "points"})
        for x, y in points[1:-1]:
            ET.SubElement(arr, "mxPoint", x=str(x), y=str(y))
    if label:
        text(*at, label, 20, color, anchor="middle")

def icon(name, x, y, size=55):
    file = OUT / "icons" / f"{name}.svg"
    if not file.exists():
        return
    raw = file.read_bytes()
    if name in {"openai", "ollama"}:
        logo = ET.fromstring(raw)
        logo.set("fill", TEXT)
        logo.set("color", TEXT)
        for element in logo.iter():
            if element.tag.endswith("path") and element.get("fill") != "none":
                element.set("fill", TEXT)
            if element.get("stroke") and element.get("stroke") != "none":
                element.set("stroke", TEXT)
        raw = ET.tostring(logo, encoding="utf-8")
    encoded = base64.b64encode(raw).decode()
    parts.append(
        f'<image href="data:image/svg+xml;base64,{encoded}" x="{x}" y="{y}" width="{size}" height="{size}"/>'
    )
    vertex(
        x,
        y,
        size,
        size,
        "shape=image;imageAspect=1;image=data:image/svg+xml," + quote(raw.decode(), safe="") + ";",
    )

def node(x, y, w, h, title, lines, brand=None, color=BLUE, title_size=33):
    rect(x, y, w, h, stroke=color if color == PURPLE else "#354558")
    if brand:
        icon(brand, x + 25, y + 25)
    else:
        rect(x + 25, y + 27, 48, 48, fill=LANE, stroke=color, radius=10)
        text(x + 49, y + 62, "◈", 26, color, anchor="middle")
    text(x + 98, y + 65, title, title_size, TEXT, True, w - 120)
    for i, line in enumerate(lines):
        text(x + 28, y + 125 + i * 39, line, 25, TEXT, maxwidth=w - 56)

rect(0, 0, W, H, fill=BG, stroke=BG, radius=0)
text(85, 65, "SERVICES  /  MODELS  /  TOOL CALLS  /  CONTEXT  /  FEEDBACK", 20, MUTED, True)
icon("app", 85, 95, 78)
text(185, 145, "Agentic RAG", 65, TEXT, True)
text(185, 195, "Document Knowledge Studio", 32, MUTED)
rect(2500, 75, 700, 85, fill=LANE)
text(2850, 127, "DESKTOP APP + YOUR EXISTING AZURE", 25, BLUE, True, anchor="middle")
rect(70, 220, 3160, 720, fill=LANE, stroke="#25384c")
text(100, 265, "01  DOCUMENT INGESTION, FIELD CONFIGURATION & INDEXING", 23, BLUE, True)
node(
    100,
    320,
    430,
    300,
    "Source library",
    [
        "PDF · Word · Excel · HTML",
        "Code · repositories · notebooks",
        "Images · audio · video",
        "Originals copied to local storage",
    ],
)
node(
    660,
    320,
    500,
    300,
    "Extraction",
    [
        "Local parsers + saved outputs",
        "OR Azure Document Intelligence",
        "prebuilt-layout → raw JSON",
        "Audio / video → text transcripts",
    ],
    brand="azure",
)
node(
    1290,
    320,
    500,
    300,
    "Element inventory",
    [
        "Text · titles · headers · tables",
        "Figures · images · source regions",
        "Pages · sheets · file paths · times",
        "Inspect originals and coverage",
    ],
    brand="sqlite",
)
node(
    1920,
    320,
    580,
    300,
    "Prepare & chunk",
    [
        "Preprocessing + five chunk strategies",
        "Agentic boundaries preserve source text",
        "Search / filter / sort / return flags",
        "Index tags + immutable provenance",
    ],
    brand="python",
)
node(
    2640,
    320,
    560,
    355,
    "Embedding choice",
    [
        "TEXT: EmbeddingGemma / Qwen3 4B",
        "Also local BGE / provider text models",
        "PIXELS: CLIP / Azure Vision / Gemini",
        "Tables: extracted rows or visual pixels",
        "One pinned embedding space per index",
    ],
    brand="ollama",
    title_size=32,
)
arrow([(530, 470), (660, 470)], BLUE, "import", (595, 443))
arrow([(1160, 470), (1290, 470)], BLUE, "extract", (1225, 443))
arrow([(1790, 470), (1920, 470)], BLUE, "review", (1855, 443))
arrow([(2500, 470), (2640, 470)], BLUE, "embed", (2570, 443))
node(
    1250,
    740,
    1250,
    160,
    "Versioned retrieval index",
    ["Local: SQLite FTS5 / BM25 + dense vectors   |   Azure: AI Search + HNSW"],
    brand="sqlite",
    title_size=33,
)
arrow([(1540, 620), (1540, 740)], BLUE, "metadata", (1640, 695))
arrow([(2920, 675), (2920, 820), (2500, 820)], BLUE, "vectors + field schema", (2730, 793))
text(
    1250,
    924,
    "Private Blob sources are optional. Cloud services are connected, never provisioned by Agentic RAG.",
    21,
    MUTED,
)
text(100, 1010, "02  LIVE AGENT, CONTEXT MANAGEMENT & MODEL CALLS", 23, PURPLE, True)
node(100, 1140, 250, 205, "User", ["Questions", "Clarifications"], color=PURPLE, title_size=31)
node(
    490,
    1090,
    470,
    300,
    "Knowledge Studio",
    [
        "Vanilla JavaScript + CSS",
        "Import · configure · inspect",
        "Research · evaluate · monitor",
        "Citations + original source links",
    ],
    color=PURPLE,
    title_size=30,
)
rect(1120, 1070, 1370, 410, stroke=PURPLE)
icon("fastapi", 1150, 1095)
icon("python", 1220, 1095)
text(1300, 1140, "Research Agent", 42, TEXT, True)
text(
    1150,
    1195,
    "Clarify → plan → filtered hybrid search → inspect → assess → cited answer",
    28,
    TEXT,
    True,
    1305,
)
for x, w, title, lines in [
    (
        1150,
        410,
        "Context & memory",
        [
            "Recent turns + scoped preferences",
            "Low / medium / high investigation",
            "User cap → bounded input packets",
        ],
    ),
    (
        1600,
        410,
        "Search tools",
        [
            "Keyword / BM25 + dense vectors",
            "RRF fusion + typed metadata filters",
            "Pinned document + index scope",
        ],
    ),
    (
        2050,
        410,
        "Inspect & assess",
        [
            "Original visuals + extracted rows",
            "Timestamps + exact source citations",
            "Optional labeled image generation",
        ],
    ),
]:
    rect(x, 1235, w, 205, fill=LANE, stroke="#3f4667")
    text(x + 22, 1280, title, 29, TEXT, True, w - 44)
    for i, line in enumerate(lines):
        text(x + 22, 1325 + i * 37, line, 22, MUTED, maxwidth=w - 44)
node(
    2640,
    1070,
    560,
    410,
    "Model connections",
    [
        "Gemini API: free / paid account",
        "OpenAI platform API key",
        "Groq API: free / paid account",
        "Local Ollama: Qwen3 8B default",
        "Also Azure OpenAI deployments",
        "Model picker + capability / quota checks",
    ],
    brand="openai",
    color=PURPLE,
    title_size=32,
)
arrow([(350, 1205), (490, 1205)], PURPLE, "ask", (420, 1180))
arrow([(490, 1280), (350, 1280)], PURPLE, "view", (420, 1313))
arrow([(960, 1205), (1120, 1205)], PURPLE, "question", (1040, 1178))
arrow([(1120, 1365), (960, 1365)], PURPLE, "answer + sources", (1040, 1398))
arrow([(2490, 1205), (2640, 1205)], PURPLE, "request", (2565, 1178))
arrow([(2640, 1370), (2490, 1370)], PURPLE, "response", (2565, 1405))
arrow([(1900, 900), (1900, 1070)], BLUE, "filtered evidence", (2010, 992))
rect(70, 1660, 3160, 565, fill=LANE, stroke="#343047")
text(100, 1705, "03  EVALUATION, HUMAN REVIEW, COSTS & ITERATION", 23, PURPLE, True)
node(
    100,
    1775,
    450,
    305,
    "Ground truth",
    [
        "CSV / JSON cases + references",
        "Pin document + chunk / index IDs",
        "Verified and unverified labels",
        "Include retrieval filters and mode",
    ],
    color=PURPLE,
    title_size=31,
)
node(
    700,
    1775,
    650,
    305,
    "Evaluation lab",
    [
        "Compare up to four configured models",
        "Token F1 · ROUGE-L · precision / recall",
        "MRR · nDCG · optional evidence judge",
        "Pin prompts, data, schema and application",
    ],
    color=PURPLE,
    title_size=32,
)
node(
    1530,
    1775,
    530,
    305,
    "Human review",
    [
        "Inspect actual answers + sources",
        "Rate results independently",
        "Revise chunking / fields / model",
        "Rebuild a new version and retest",
    ],
    color=PURPLE,
    title_size=32,
)
node(
    2410,
    1775,
    790,
    305,
    "Monitoring & cost ledger",
    [
        "SQLite traces · indexing · retrieval · service calls",
        "Model usage · visual inputs · latency · failures",
        "Context caps + trimming + selected evidence",
        "Known estimates + unpriced costs kept distinct",
    ],
    color=ORANGE,
    title_size=33,
)
arrow([(550, 1915), (700, 1915)], PURPLE, "pin cases", (625, 1888), True)
arrow([(1350, 1915), (1530, 1915)], PURPLE, "review", (1440, 1888), True)
arrow(
    [(1325, 1480), (1325, 1600), (1000, 1600), (1000, 1775)],
    PURPLE,
    "replay + score",
    (1130, 1575),
    True,
)
arrow(
    [(2460, 1480), (2460, 1590), (2800, 1590), (2800, 1775)], ORANGE, "traces + usage", (2825, 1565)
)
arrow(
    [(1900, 2080), (1900, 2285), (50, 2285), (50, 295), (2210, 295), (2210, 320)],
    PURPLE,
    dashed=True,
)
text(1180, 2190, "REVIEW → ADJUST → REBUILD → EVALUATE AGAIN", 27, PURPLE, True, anchor="middle")
for x, color, label, dashed in [
    (600, BLUE, "Data + source evidence", False),
    (1140, PURPLE, "Agent + model traffic", False),
    (1690, PURPLE, "Evaluation + feedback", True),
    (2250, ORANGE, "Telemetry + costs", False),
]:
    arrow([(x, 2330), (x + 75, 2330)], color, dashed=dashed)
    text(x + 95, 2338, label, 22, MUTED)
text(
    100,
    2370,
    "Text-only embeddings never embed pixels. Context caps are text characters; visual token use remains provider-specific.",
    20,
    MUTED,
)
markers = "".join(
    f'<marker id="arrow{c[1:]}" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8Z" fill="{c}"/></marker>'
    for c in [BLUE, PURPLE, ORANGE]
)
svg = (
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Arial, sans-serif"><defs>{markers}</defs>'
    + "".join(parts)
    + "</svg>"
)
(OUT / "agentic-rag_architecture.svg").write_text(svg)
ET.ElementTree(mx).write(
    ROOT / "docs/diagrams/agentic-rag_architecture.drawio", encoding="utf-8", xml_declaration=True
)
(ROOT / "docs/diagrams/agentic-rag_architecture.bounds.json").write_text(
    json.dumps(bounds, indent=2)
)
renderer = shutil.which("rsvg-convert")
if renderer:
    subprocess.run(
        [
            renderer,
            "-w",
            str(W * 2),
            "-h",
            str(H * 2),
            "-o",
            str(OUT / "agentic-rag_architecture.png"),
            str(OUT / "agentic-rag_architecture.svg"),
        ],
        check=True,
    )
print(
    json.dumps(
        {
            "labels_checked": len(bounds),
            "canvas": [W, H],
            "png": [W * 2, H * 2] if renderer else None,
            "editable": "docs/diagrams/agentic-rag_architecture.drawio",
        }
    )
)
