"""Render the Azure workflow as SVG, PNG and editable draw.io."""

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
W, H = 2600, 2340
BG, LANE, BOX = "#090b11", "#111620", "#1a2231"
TEXT, MUTED, BLUE, PURPLE, ORANGE = "#e4e9f4", "#9ca8ba", "#68b8ff", "#b59aff", "#f0ad67"
parts = []
bounds = []
seq = 1
mx = ET.Element("mxfile", host="app.diagrams.net", version="24.7.17")
dia = ET.SubElement(mx, "diagram", name="Azure document workflow", id="azure-workflow")
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
icon("app", 85, 83, 78)
text(185, 135, "Agentic RAG", 60, TEXT, True)
text(185, 185, "Document Knowledge Studio · Azure workflow", 30, MUTED)
rect(1800, 83, 690, 82, fill=LANE)
text(2145, 133, "YOUR EXISTING AZURE RESOURCES", 25, BLUE, True, anchor="middle")

rect(70, 230, 2460, 510, fill=LANE, stroke="#25384c")
text(100, 275, "01  CONNECT YOUR SERVICES & EXTRACT THE DOCUMENT", 23, BLUE, True)
node(
    100,
    325,
    480,
    300,
    "Knowledge Studio",
    [
        "Import a supported document",
        "Choose your Azure workspace",
        "Review the cloud operation",
        "Original stays in your library",
    ],
    brand="app",
    title_size=30,
)
node(
    735,
    325,
    620,
    330,
    "Azure workspace",
    [
        "Your resource endpoints + deployments",
        "Service keys / Microsoft sign-in / CLI",
        "Check access from the app",
        "No service or role provisioning",
    ],
    brand="azure",
    color=PURPLE,
    title_size=32,
)
node(
    1510,
    325,
    980,
    330,
    "Document Intelligence",
    [
        "prebuilt-layout parses document content and structure",
        "PDF / supported Office, HTML or image sources",
        "Returned text, tables, figures, sections and source geometry",
        "Raw Layout JSON and returned coverage remain inspectable",
    ],
    brand="azure",
    title_size=33,
)
arrow([(580, 475), (735, 475)], BLUE, "configure", (657, 447))
arrow([(1355, 475), (1510, 475)], BLUE, "analyze", (1432, 447))
arrow(
    [(2000, 655), (2000, 785), (450, 785), (450, 920)],
    BLUE,
    "returned entities + raw Layout JSON",
    (1200, 775),
)

rect(70, 835, 2460, 445, fill=LANE, stroke="#25384c")
text(100, 880, "02  INSPECT, CHOOSE CHUNKS & PUBLISH A VERSION", 23, BLUE, True)
node(
    100,
    935,
    700,
    295,
    "Inspect Layout output",
    [
        "Review extracted elements and source regions",
        "Keep original text, tables and visual references",
        "Check page coverage before indexing",
        "Azure owns entity extraction in this workflow",
    ],
    brand="sqlite",
    title_size=33,
)
node(
    950,
    935,
    680,
    295,
    "Preprocess & chunk",
    [
        "Choose cleanup and a chunking strategy",
        "Preview boundaries, including agentic groups",
        "Configure searchable / filterable / sortable fields",
        "Select text or visual embedding engine",
    ],
    brand="python",
    title_size=32,
)
node(
    1790,
    935,
    700,
    295,
    "Azure AI Search",
    [
        "Create a new index in your existing service",
        "Upload chunks, vectors and source metadata",
        "Verify uploads before activating the version",
        "Earlier active index survives a failed build",
    ],
    brand="azure",
    title_size=33,
)
arrow([(800, 1080), (950, 1080)], BLUE, "prepare", (875, 1054))
arrow([(1630, 1080), (1790, 1080)], BLUE, "index", (1710, 1054))

rect(70, 1375, 2460, 420, fill=LANE, stroke="#343047")
text(100, 1418, "03  ASK, RETRIEVE & ANSWER", 23, PURPLE, True)
node(
    100,
    1475,
    650,
    280,
    "Research Agent",
    [
        "Clarify the question and plan the search",
        "Respect page / section / source filters",
        "Inspect evidence and assess sufficiency",
        "Bound effort, context and conversation memory",
    ],
    brand="app",
    color=PURPLE,
    title_size=33,
)
node(
    930,
    1475,
    650,
    280,
    "Azure OpenAI",
    [
        "Your answer deployment + authentication",
        "Use retrieved text, rows and descriptions",
        "Attach visuals for a compatible deployment",
        "Generate a source-grounded response",
    ],
    brand="openai",
    color=PURPLE,
    title_size=33,
)
node(
    1760,
    1475,
    730,
    280,
    "Answer + references",
    [
        "Citations point back to source chunks",
        "Open original pages, tables and images",
        "Ask follow-ups within the selected source",
        "Separate observations, inference and gaps",
    ],
    brand="app",
    color=PURPLE,
    title_size=33,
)
arrow(
    [(650, 1475), (650, 1300), (2080, 1300), (2080, 1230)],
    PURPLE,
    "agent search tool",
    (1190, 1285),
)
arrow(
    [(2220, 1230), (2220, 1340), (800, 1340), (800, 1510), (750, 1510)],
    BLUE,
    "keyword + vector search + metadata filters",
    (1350, 1330),
)
arrow([(750, 1605), (930, 1605)], PURPLE, "evidence", (840, 1578))
arrow([(1580, 1605), (1760, 1605)], PURPLE, "response", (1670, 1578))

rect(70, 1860, 2460, 350, fill=LANE, stroke="#343047")
text(100, 1903, "OPTIONAL SERVICES & THE SHARED REVIEW LOOP", 23, ORANGE, True)
node(
    100,
    1950,
    700,
    220,
    "Azure Vision · optional",
    ["Text + image vectors for visual retrieval", "Pixel embeddings are separate from chat vision"],
    brand="azure",
    title_size=31,
)
node(
    950,
    1950,
    680,
    220,
    "Private Blob · optional",
    [
        "Originals, Layout JSON and visual assets",
        "Source references through your private container",
    ],
    brand="azure",
    title_size=31,
)
node(
    1790,
    1950,
    700,
    220,
    "Monitoring + evaluation",
    [
        "Index / retrieval / model traces and known costs",
        "Ground truth, model comparison and human review",
    ],
    brand="python",
    color=ORANGE,
    title_size=31,
)
text(
    100,
    2265,
    "Review → adjust preprocessing, chunks, fields or model → build a new version → evaluate again",
    26,
    PURPLE,
    True,
)
text(
    100,
    2315,
    "Connected resources, personal desktop workspace. Your Azure permissions, model capabilities and quotas apply.",
    23,
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
(OUT / "azure-workflow.svg").write_text(svg)
ET.ElementTree(mx).write(
    ROOT / "docs/diagrams/azure-workflow.drawio", encoding="utf-8", xml_declaration=True
)
(ROOT / "docs/diagrams/azure-workflow.bounds.json").write_text(json.dumps(bounds, indent=2))
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
            str(OUT / "azure-workflow.png"),
            str(OUT / "azure-workflow.svg"),
        ],
        check=True,
    )
print(
    json.dumps(
        {
            "labels_checked": len(bounds),
            "canvas": [W, H],
            "png": [W * 2, H * 2] if renderer else None,
            "editable": "docs/diagrams/azure-workflow.drawio",
        }
    )
)
