"""Azure Layout owns entity detection; local rendering only preserves its source regions."""

from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from urllib.parse import quote, urlparse

from app.core import store as s
from app.core.progress import report
from app.ingestion.extraction import Extractor, asset, png, render_table, table_text
from app.integrations import azure_cloud as cloud

ROLES = {
    "title": "title",
    "sectionHeading": "section_header",
    "pageHeader": "header",
    "pageFooter": "footer",
    "pageNumber": "page_number",
    "footnote": "footnote",
}

def poll_path(location, profile):
    u = urlparse(location)
    base = urlparse(profile["document_endpoint"])
    if (
        u.scheme != base.scheme
        or u.netloc != base.netloc
        or u.fragment
        or u.username
        or not re.fullmatch(
            r"/documentintelligence/documentModels/prebuilt-layout/analyzeResults/[A-Za-z0-9-]+",
            u.path,
        )
        or u.query != "api-version=" + cloud.DI_VERSION
    ):
        raise ValueError(
            "Azure returned an unexpected result location. Credentials were not forwarded."
        )
    return u.path + "?" + u.query

def selected_pages(pages, total):
    if not pages:
        return set(range(1, total + 1)) if total is not None else None
    result = set()
    for term in pages.split(","):
        bounds = [int(x) for x in term.strip().split("-")]
        start = bounds[0]
        end = bounds[-1]
        if start < 1 or end < start or end > 2000:
            raise ValueError("Use ascending page ranges between 1 and 2000.")
        result.update(range(start, end + 1))
    if total is not None and any(n > total for n in result):
        raise ValueError("A selected page is beyond the end of this document.")
    return result

def extract(doc, cfg, c, budget):
    report(budget.run, "azure-layout", "Preparing Azure Document Intelligence analysis", 2)
    profile, plan = cloud.consume_plan(doc, cfg, "extract", budget.run)
    info = cloud.source_info(doc, cfg, profile)
    expected = selected_pages(cfg.azure_pages, info["source_pages"])
    predicted = len(expected) if expected is not None else None
    if profile["document_tier"] == "F0" and predicted is not None:
        predicted = min(2, predicted)
    rate = profile.get("document_price_per_1000_pages")
    estimate = predicted * rate / 1000 if predicted is not None and rate is not None else None
    path = (
        "/documentintelligence/documentModels/prebuilt-layout:analyze?api-version="
        + cloud.DI_VERSION
        + "&outputContentFormat=markdown&stringIndexType=unicodeCodePoint"
    )
    want_figures = info["format"] in {
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".bmp",
        ".tiff",
        ".tif",
        ".heif",
    }
    if want_figures:
        path += "&output=figures"
    if cfg.azure_pages:
        path += "&pages=" + quote(cfg.azure_pages, safe=",-")
    if cfg.azure_features:
        path += "&features=" + ",".join(cfg.azure_features)
    s.event(
        budget.run,
        "azure-layout",
        "Submitting document to Azure Document Intelligence prebuilt-layout",
        source=doc["name"],
        endpoint=profile["document_endpoint"],
    )
    # A single analyze submission: polling never resends a document.
    report(
        budget.run,
        "azure-layout",
        "Waiting for Azure Layout analysis; Azure does not report page-by-page progress",
        10,
        waiting=True,
    )
    r, call_id = cloud.request(
        profile,
        "document",
        "POST",
        path,
        budget,
        body={"base64Source": base64.b64encode(s.asset_path(doc["path"]).read_bytes()).decode()},
        units=predicted,
        unit="pages",
        cost=estimate,
    )
    if r.status_code != 202 or not r.headers.get("Operation-Location"):
        raise ValueError("Azure Layout did not return an asynchronous analysis location.")
    location = poll_path(r.headers["Operation-Location"], profile)
    analysis_id = s.uid()
    s.put(
        "azure_analyses",
        analysis_id,
        {
            "document_id": doc["id"],
            "profile_id": profile["id"],
            "result_path": location,
            "run_id": budget.run,
            "created": s.now(),
            "status": "running",
            "submission_call_id": call_id,
        },
    )
    end = time.monotonic() + profile["timeout_seconds"]
    result = None
    while time.monotonic() < end:
        cloud.check(budget.run)
        try:
            delay = min(5, max(0.2, float(r.headers.get("Retry-After", 1))))
        except ValueError:
            delay = 1
        time.sleep(delay)
        r, _ = cloud.request(profile, "document", "GET", location, budget, billable=False)
        obj = r.json()
        status = obj.get("status", "").lower()
        if status == "succeeded":
            result = obj
            break
        if status in {"failed", "canceled", "cancelled"}:
            s.patch("azure_analyses", analysis_id, status=status)
            raise ValueError(
                "Azure Layout analysis failed. Check document support and Azure diagnostics. The previous extraction was preserved."
            )
        s.event(
            budget.run,
            "azure-layout",
            "Azure is analyzing the document",
            status=status or "running",
        )
    if result is None:
        s.patch("azure_analyses", analysis_id, status="timed_out")
        raise ValueError(
            "Layout polling timed out. Azure may still finish this submitted analysis; it was not submitted again. The previous extraction remains active."
        )
    namespace = doc["id"] + "-" + budget.run
    raw = asset(
        namespace,
        "azure-layout-result.json",
        json.dumps(result, ensure_ascii=False, indent=2).encode(),
    )
    s.patch("azure_analyses", analysis_id, status="completed", raw_json_asset=raw)
    analyzed = result.get("analyzeResult", {})
    report(budget.run, "azure-layout", "Azure analysis returned; mapping the document elements", 45)
    if analyzed.get("modelId") != "prebuilt-layout":
        raise ValueError("Azure returned a different model. Expected prebuilt-layout.")
    returned = {x["pageNumber"] for x in analyzed.get("pages", [])}
    warnings = list(info["warnings"])
    complete = expected is not None and returned == expected
    if expected is not None and returned != expected:
        warnings.append(
            f"Partial coverage: Azure returned {len(returned)} of {len(expected)} requested/source pages. Only returned pages are indexed."
        )
    if expected is None:
        warnings.append(
            "Full source coverage could not be independently counted for this format. Review the returned pages and raw JSON."
        )
    actual = len(returned)
    s.patch(
        "cloud_calls",
        call_id,
        units=actual,
        cost_usd=actual * rate / 1000 if rate is not None else None,
        price_status="estimated" if rate is not None else "unpriced",
        unit="returned pages (billing may differ)",
    )
    mapper = Mapper(
        doc,
        cfg,
        c,
        budget,
        namespace,
        analyzed,
        profile,
        location.split("?")[0],
        warnings,
        want_figures,
    )
    elements = mapper.run()
    report(
        budget.run,
        "azure-layout",
        "Azure elements extracted and mapped",
        65,
        completed=actual,
        total=actual,
        unit="returned pages",
    )
    # Captions are optional enrichment after Azure entity extraction, never a replacement parser.
    if cfg.describe_visuals:
        helper = Extractor(doc, cfg, c, budget)
        helper.elements = elements
        helper.warnings = warnings
        helper.enrich()
    if not any(e.get("include_in_index") is not False for e in elements):
        raise ValueError(
            "Azure Layout returned no indexable elements. Inspect the saved raw JSON in Azure operations."
        )
    return (
        elements,
        warnings,
        {
            "backend": "azure-document-intelligence",
            "model": "prebuilt-layout",
            "api_version": cloud.DI_VERSION,
            "raw_json_asset": raw,
            "azure_profile": cloud.public(profile),
            "analysis_id": analysis_id,
            "coverage": {
                "source_pages": info["source_pages"],
                "requested_pages": sorted(expected) if expected is not None else None,
                "returned_pages": sorted(returned),
                "complete": complete,
                "selected_subset": bool(cfg.azure_pages),
            },
            "azure_summary": {
                k: len(analyzed.get(k, []))
                for k in [
                    "pages",
                    "paragraphs",
                    "tables",
                    "figures",
                    "sections",
                    "styles",
                    "languages",
                    "keyValuePairs",
                ]
            },
        },
    )

class Mapper:
    def __init__(
        self, doc, cfg, c, budget, namespace, result, profile, result_path, warnings, want_figures
    ):
        self.doc = doc
        self.cfg = cfg
        self.budget = budget
        self.ns = namespace
        self.r = result
        self.profile = profile
        self.result_path = result_path
        self.warnings = warnings
        self.want_figures = want_figures
        self.elements = []
        self.pages = {x["pageNumber"]: x for x in result.get("pages", [])}
        self.pdf = None

    def meta(self, obj):
        regions = obj.get("boundingRegions", [])
        region = regions[0] if regions else {}
        number = region.get("pageNumber", obj.get("pageNumber"))
        polygon = region.get("polygon", obj.get("polygon", []))
        page = self.pages.get(number, {})
        bbox = None
        if polygon and page.get("width") and page.get("height"):
            xs = polygon[::2]
            ys = polygon[1::2]
            bbox = [
                min(xs) / page["width"],
                min(ys) / page["height"],
                max(xs) / page["width"],
                max(ys) / page["height"],
            ]
        spans = obj.get("spans", [])
        return {
            "page": number,
            "bbox": bbox,
            "bounding_regions": regions,
            "spans": spans,
            "azure_role": obj.get("role"),
            "_order": min((x["offset"] for x in spans), default=10**12),
        }

    def add(self, kind, text, obj, **extra):
        item = {
            "kind": kind,
            "text": text,
            "source_name": self.doc["name"],
            "source_asset": self.doc["path"],
            "document_id": self.doc["id"],
            "extracted_by": "azure-document-intelligence/prebuilt-layout",
            **self.meta(obj),
            **extra,
        }
        self.elements.append(item)
        return item

    def crop(self, obj, name):
        meta = self.meta(obj)
        number = meta["page"]
        bbox = meta["bbox"]
        if self.pdf is None or not number or not bbox or number > len(self.pdf):
            return None
        import pymupdf as fitz

        page = self.pdf[number - 1]
        w, h = page.rect.width, page.rect.height
        rect = fitz.Rect(bbox[0] * w, bbox[1] * h, bbox[2] * w, bbox[3] * h) & page.rect
        if rect.is_empty:
            return None
        return asset(
            self.ns,
            name,
            page.get_pixmap(
                matrix=fitz.Matrix(
                    min(2, 2200 / max(rect.width, rect.height)),
                    min(2, 2200 / max(rect.width, rect.height)),
                ),
                clip=rect,
            ).tobytes("png"),
        )

    def run(self):
        import pymupdf

        if Path(self.doc["path"]).suffix.lower() == ".pdf":
            self.pdf = pymupdf.open(s.asset_path(self.doc["path"]))
        try:
            # Render only pages reported by Azure, without detecting entities locally.
            for number, page in self.pages.items():
                cloud.check(self.budget.run)
                if (
                    self.pdf is not None
                    and number <= len(self.pdf)
                    and len([e for e in self.elements if e["kind"] == "page_preview"]) < 200
                ):
                    source = self.pdf[number - 1]
                    scale = min(1.5, 2200 / max(source.rect.width, source.rect.height))
                    a = asset(
                        self.ns,
                        f"page-{number}.png",
                        source.get_pixmap(matrix=pymupdf.Matrix(scale, scale)).tobytes("png"),
                    )
                    self.add(
                        "page_preview", "", {"pageNumber": number}, asset=a, include_in_index=False
                    )
            if len(self.pages) > 200:
                self.warnings.append(
                    "Local page previews are limited to the first 200 returned pages. Azure elements and raw JSON retain all returned pages."
                )
            table_spans = [
                span for table in self.r.get("tables", []) for span in table.get("spans", [])
            ]
            paragraphs = self.r.get("paragraphs", [])
            for para in paragraphs:
                spans = para.get("spans", [])
                inside = spans and all(
                    any(
                        t["offset"] <= sp["offset"]
                        and sp["offset"] + sp["length"] <= t["offset"] + t["length"]
                        for t in table_spans
                    )
                    for sp in spans
                )
                self.add(
                    ROLES.get(para.get("role"), "text"),
                    para.get("content", ""),
                    para,
                    include_in_index=not bool(inside),
                    contained_in_table=bool(inside),
                )
            if not paragraphs:
                for number, page in self.pages.items():
                    for line in page.get("lines", []):
                        self.add("text", line.get("content", ""), {**line, "pageNumber": number})
            for n, table in enumerate(self.r.get("tables", []), 1):
                rows = [[""] * table.get("columnCount", 0) for _ in range(table.get("rowCount", 0))]
                for cell in table.get("cells", []):
                    row, col = cell.get("rowIndex", 0), cell.get("columnIndex", 0)
                    if row < len(rows) and col < len(rows[row]):
                        rows[row][col] = cell.get("content", "")
                a = self.crop(table, f"table-{n}.png")
                rendered = False
                if not a:
                    a = render_table(self.ns, f"table-{n}-data-preview.png", rows)
                    rendered = True
                data = asset(
                    self.ns,
                    f"table-{n}.json",
                    json.dumps(table, ensure_ascii=False, indent=2).encode(),
                )
                self.add(
                    "table",
                    table_text(rows),
                    table,
                    asset=a,
                    rows=rows,
                    cells=table.get("cells", []),
                    data_asset=data,
                    preview_reconstructed=rendered,
                )
            for n, figure in enumerate(self.r.get("figures", []), 1):
                a = None
                figure_id = figure.get("id", "")
                if self.want_figures and re.fullmatch(r"[A-Za-z0-9_.-]+", figure_id):
                    response, _ = cloud.request(
                        self.profile,
                        "document",
                        "GET",
                        self.result_path
                        + "/figures/"
                        + figure_id
                        + "?api-version="
                        + cloud.DI_VERSION,
                        self.budget,
                        billable=False,
                    )
                    a = png(self.ns, f"figure-{n}.png", data=response.content)
                if not a:
                    a = self.crop(figure, f"figure-{n}.png")
                caption = figure.get("caption", {}).get("content", "")
                footnotes = "\n".join(x.get("content", "") for x in figure.get("footnotes", []))
                self.add(
                    "image",
                    caption + ("\n" + footnotes if footnotes else ""),
                    figure,
                    **({"asset": a} if a else {}),
                    azure_entity="figure",
                    figure_id=figure_id,
                    caption=figure.get("caption"),
                    description_status="pending" if a else "no_pixels",
                )
                if not a:
                    self.warnings.append(
                        f"Figure {figure_id or n} has no returned pixels. It remains a metadata/caption reference, not a visual embedding."
                    )
            for number, page in self.pages.items():
                for mark in page.get("selectionMarks", []):
                    self.add(
                        "selection_mark",
                        mark.get("state", ""),
                        {**mark, "pageNumber": number},
                        confidence=mark.get("confidence"),
                        include_in_index=False,
                    )
                for formula in page.get("formulas", []):
                    self.add(
                        "formula",
                        formula.get("value", ""),
                        {**formula, "pageNumber": number},
                        confidence=formula.get("confidence"),
                    )
                for barcode in page.get("barcodes", []):
                    self.add(
                        "barcode",
                        barcode.get("value", ""),
                        {**barcode, "pageNumber": number},
                        barcode_kind=barcode.get("kind"),
                    )
            for pair in self.r.get("keyValuePairs", []):
                key = pair.get("key", {})
                value = pair.get("value", {})
                self.add(
                    "key_value",
                    key.get("content", "") + ": " + value.get("content", ""),
                    key,
                    value_metadata=value,
                    confidence=pair.get("confidence"),
                )
            for section in self.r.get("sections", []):
                self.add(
                    "section",
                    "",
                    section,
                    include_in_index=False,
                    child_elements=section.get("elements", []),
                )
            self.elements.sort(key=lambda e: e.pop("_order"))
            section = ""
            for n, e in enumerate(self.elements, 1):
                e["id"] = f"e{n:05d}"
                if e["kind"] in {"title", "section_header"}:
                    section = e["text"]
                e["section"] = section
            self.warnings.append(
                "Entity detection uses Azure Layout only. Charts are returned as figures; optional model descriptions can explain them after extraction. Words, line geometry, styles and complete service metadata are retained in raw JSON."
            )
            return self.elements
        finally:
            if self.pdf is not None:
                self.pdf.close()
