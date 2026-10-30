"use strict";
// Move app-owned preferences from a previous branding prefix on this origin.
for (const suffix of ["document", "pipeline"]) {
  const target = "agentic-rag-" + suffix;
  for (const prior of Object.keys(localStorage).filter(
    (k) => k !== target && k.endsWith("-" + suffix),
  )) {
    if (localStorage.getItem(target) === null)
      localStorage.setItem(target, localStorage.getItem(prior));
    localStorage.removeItem(prior);
  }
}
const $ = (s, r = document) => r.querySelector(s),
  $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const json = (v) => esc(JSON.stringify(v, null, 2));
function formatText(text) {
  const lines = esc(text).split("\n");
  return lines
    .map((line) => {
      line = line
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(
          /\[(c\d+)\]/g,
          '<button class="citation" data-action="focus-source" data-id="$1">[$1]</button>',
        );
      if (/^###? /.test(line))
        return "<h3>" + line.replace(/^#+ /, "") + "</h3>";
      if (/^[-*] /.test(line))
        return '<div class="answer-bullet">• ' + line.slice(2) + "</div>";
      return line ? "<div>" + line + "</div>" : "<br>";
    })
    .join("");
}

const fileURL = (a) =>
  "/api/files/" + a.split("/").map(encodeURIComponent).join("/");
const fmt = (n) => Number(n || 0).toLocaleString();
const bytes = (n) =>
  n > 1048576
    ? (n / 1048576).toFixed(1) + " MB"
    : (n / 1024).toFixed(1) + " KB";
const date = (t) => (t ? new Date(t * 1000).toLocaleString() : "");
const short = (s) => String(s || "").slice(0, 11);
const price = (n) => (n == null ? "Unpriced" : "$" + Number(n).toFixed(5));
const metric = (n) => (n == null ? "—" : Number(n).toFixed(3));
let state = {},
  page = location.hash.slice(1) || "library",
  docId = localStorage.getItem("agentic-rag-document") || "",
  detail = null;
let config = {
  metadata_tags: [],
  index_fields: {},
  ollama_url: "http://127.0.0.1:11434",
  extraction_backend: "local",
  index_backend: "local",
  azure_profile_id: "",
  azure_plan_id: "",
  azure_pages: "",
  azure_features: [],
  azure_semantic_rerank: false,
  mode: "",
  strategy: "agentic",
  embedding: "local-text",
  connection_id: "",
  embedding_connection_id: "",
  chunk_size: 1600,
  overlap: 150,
  strip_headers: true,
  deduplicate: true,
  mask_pii: false,
  describe_visuals: true,
  vision_layout: false,
  ocr: false,
  fetch_web_images: false,
  transcription: "local",
  whisper_model: "tiny",
  max_calls: 80,
  budget_usd: null,
  ...JSON.parse(localStorage.getItem("agentic-rag-pipeline") || "{}"),
};
let jobs = new Map(),
  pipelineRuns = new Map(),
  pipelineSyncing = false,
  jobListAvailable = true,
  monitor = null,
  traceRun = "",
  evalId = "",
  evaluation = null,
  editConnection = "",
  elementKind = "",
  elementSearch = "",
  inspectTab = "chunks",
  inspectSnapshotId = "",
  chunkInspection = null,
  chunkInspectionError = "",
  chunkSearch = "",
  chunkKind = "",
  chunkPage = 0,
  messages = [],
  chatResult = null,
  sessionId = "",
  pending = null,
  memories = [],
  browseState = null,
  toastTimer;
let connectionDraft = null,
  editAzure = "",
  azureDraft = null,
  cloudPlan = null,
  signInState = null,
  signInTimer = null;
let chatOptions = {
  connection_id: null,
  max_passes: 2,
  preview: false,
  generate_image: false,
  search_mode: "hybrid",
  keyword_query: "",
  filters: {},
  use_agent_filters: true,
  effort: "medium",
  context_chars: null,
};
const names = {
  library: "Source library",
  azure: "Azure workspace",
  processing: "Processing studio",
  research: "Research agent",
  monitoring: "Monitoring",
  evaluation: "Evaluation lab",
  settings: "Connections & settings",
};
const icons = {
  library: "▧",
  azure: "☁",
  processing: "◈",
  research: "✧",
  monitoring: "▥",
  evaluation: "◎",
  settings: "⚙",
};
const chosen = () => state.documents?.find((x) => x.id === docId);
const active = () =>
  state.connections?.find((x) => x.id === state.settings?.active_connection);
const options = (rows, id = "", placeholder = "Choose a connection") =>
  '<option value="">' +
  placeholder +
  "</option>" +
  rows
    .map(
      (c) =>
        `<option value="${esc(c.id)}" ${c.id === id ? "selected" : ""}>${esc(c.name)} · ${esc(c.model)}</option>`,
    )
    .join("");
const badge = (text, type = "") =>
  `<span class="badge ${type}">${esc(text)}</span>`;
const empty = (title, text) =>
  `<div class="empty"><b>${esc(title)}</b>${esc(text)}</div>`;
function toast(text, error = false) {
  const t = $("#toast");
  t.textContent = text;
  t.className = error ? "error" : "";
  t.style.display = "block";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.style.display = "none"), 7000);
}
async function api(url, opts = {}) {
  const r = await fetch(url, {
    ...opts,
    headers: {
      "X-Agentic-RAG-Client": "local-workspace",
      ...(opts.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...opts.headers,
    },
  });
  let data;
  try {
    data = await r.json();
  } catch {
    throw Error("The local app returned an unreadable response.");
  }
  if (!r.ok) {
    const error = Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
    error.status = r.status;
    throw error;
  }
  return data;
}
const post = (url, data = {}) =>
  api(url, { method: "POST", body: JSON.stringify(data) });
async function refresh() {
  state = await api("/api/state");
  if (!config.connection_id)
    config.connection_id = state.settings.active_connection;
  if (!state.documents.some((document) => document.id === docId)) {
    docId = state.documents[0]?.id || "";
    inspectSnapshotId = "";
    chunkInspection = null;
  }
  if (docId) await loadDetail();
}
async function loadDetail() {
  const scope = docId;
  const result = await api("/api/documents/" + scope);
  if (scope !== docId) return;
  detail = result;
  if (detail.active_index)
    detail.filter_catalog = await api(
      "/api/indexes/" + detail.active_index + "/filters",
    );
  await loadChunkInspection();
  localStorage.setItem("agentic-rag-document", docId);
}
function inspectionTargets() {
  return [
    ...(detail?.indexes || []).map((index) => ({
      id: "index:" + index.id,
      label: `${index.id === detail.active_index ? "Active index" : "Index version"} · ${short(index.id)} · ${index.chunks.length} chunks`,
    })),
    ...(detail?.chunk_preview
      ? [
          {
            id: "preview:" + detail.chunk_preview.id,
            label: `Chunk preview · ${short(detail.chunk_preview.id)} · not indexed`,
          },
        ]
      : []),
  ];
}
function selectedInspectionTarget() {
  const targets = inspectionTargets();
  return (
    targets.find((target) => target.id === inspectSnapshotId) ||
    targets.find((target) => target.id === "index:" + detail?.active_index) ||
    targets[0]
  );
}
async function loadChunkInspection() {
  const target = selectedInspectionTarget();
  if (!target) {
    chunkInspection = null;
    chunkInspectionError = "";
    return;
  }
  if (chunkInspection?.target === target.id) return;
  const scope = docId,
    [kind, id] = target.id.split(":");
  try {
    const result = await api(
      `/api/${kind === "index" ? "indexes" : "chunk-previews"}/${id}/inspection`,
    );
    if (scope !== docId || target.id !== selectedInspectionTarget()?.id) return;
    chunkInspection = { ...result, target: target.id };
    chunkInspectionError = "";
    chunkPage = 0;
  } catch (error) {
    if (scope !== docId || target.id !== selectedInspectionTarget()?.id) return;
    chunkInspection = null;
    chunkInspectionError = error.message;
  }
}
function header(title, desc, actions = "") {
  return `<div class="page-head"><div><div class="eyebrow">${page === "library" ? "YOUR KNOWLEDGE, IN FOCUS" : "DOCUMENT KNOWLEDGE STUDIO"}</div><h1>${title}</h1><p>${desc}</p></div><div class="actions">${actions}</div></div>`;
}
function selector() {
  return `<div class="field"><label for="selected-document">Working document</label><select id="selected-document" data-change="document">${state.documents.length ? state.documents.map((d) => `<option value="${d.id}" ${d.id === docId ? "selected" : ""}>${esc(d.name)}</option>`).join("") : '<option value="">Import a document first</option>'}</select></div>`;
}
function banners() {
  return (
    '<div id="job-banners">' +
    [...jobs.values()]
      .filter(
        (j) =>
          !Object.values(pipelineStages).some((stage) => stage.kind === j.kind),
      )
      .map(
        (j) =>
          `<div class="run-banner"><div><span class="spinner"></span><b>${esc(j.kind)}</b> <span data-job-message="${j.id}">Queued…</span></div><button class="btn small" data-action="cancel" data-id="${j.id}">Cancel</button></div>`,
      )
      .join("") +
    "</div>"
  );
}
const pipelineStages = {
  extract: {
    kind: "extraction",
    action: "Extract elements →",
    running: "Extracting elements…",
    complete: "Extraction completed",
  },
  chunks: {
    kind: "chunking",
    action: "Preview chunks",
    running: "Creating chunks…",
    complete: "Chunk preview ready",
  },
  index: {
    kind: "indexing",
    action: "Build vector index →",
    running: "Building vector index…",
    complete: "Index ready for questions",
  },
};
function pipelineJob(stage) {
  const kind = pipelineStages[stage].kind;
  const unique = new Map();
  for (const job of [
    ...pipelineRuns.values(),
    ...jobs.values(),
    ...(state.jobs || []),
  ]) {
    if (!unique.has(job.id)) unique.set(job.id, job);
  }
  const busy = (job) =>
    ["submitting", "queued", "running"].includes(job.status);
  return [...unique.values()]
    .filter((j) => j.scope === docId && j.kind === kind)
    .sort(
      (a, b) => Number(busy(b)) - Number(busy(a)) || b.created - a.created,
    )[0];
}
function processingProgress(job) {
  if (!job) return null;
  if (job.status === "completed") return { percent: 100 };
  if (job.progress) return job.progress;
  const events = job.events || [];
  for (const event of [...events].reverse()) {
    if (event.details?.progress) return event.details.progress;
    const page = event.message.match(/^Extracting page (\d+)\/(\d+)/);
    const embedding = event.message.match(
      /^Embedding chunks (\d+)[–-]\d+ of (\d+)/,
    );
    const audio = event.message.match(/^Transcribing segment (\d+)\/(\d+)/);
    const match = page || embedding || audio;
    if (match) {
      const completed = Number(match[1]) - 1,
        total = Number(match[2]);
      return {
        percent:
          (page ? 0 : embedding ? 30 : 10) +
          ((page ? 65 : 55) * completed) / total,
        completed,
        total,
        unit: page ? "pages" : embedding ? "chunks" : "audio segments",
        message: event.message,
      };
    }
  }
  return { percent: 0, message: "Waiting for the next processing checkpoint" };
}
function progressBar(job, status) {
  if (!job && status !== "completed") return "";
  const progress = processingProgress(job) || { percent: 100 };
  const percent = Math.max(
    0,
    Math.min(
      status === "completed" ? 100 : 99,
      Math.floor(Number(progress.percent) || 0),
    ),
  );
  return `<div class="pipeline-progress-label"><span>Workflow progress</span><b>${percent}%</b></div><progress class="pipeline-progress" max="100" value="${percent}" aria-label="Workflow progress">${percent}%</progress>${progress.total != null ? `<div class="small muted section-space">${fmt(progress.completed)} / ${fmt(progress.total)} ${esc(progress.unit)} completed</div>` : ""}${status === "running" || status === "queued" ? '<div class="small muted section-space">Please wait. Progress follows completed steps; model and service calls can take time.</div>' : ""}`;
}
function pipelineBusy() {
  return Object.keys(pipelineStages).some((stage) =>
    ["submitting", "queued", "running"].includes(pipelineJob(stage)?.status),
  );
}
function pipelineStatus(stage) {
  const info = pipelineStages[stage],
    j = pipelineJob(stage);
  const existing =
    stage === "extract"
      ? detail?.extraction
      : stage === "chunks"
        ? detail?.chunk_preview
        : detail?.indexes?.find((i) => i.id === detail.active_index);
  const status = j?.status || (existing ? "completed" : "idle");
  const busy = ["submitting", "queued", "running"].includes(status);
  let title = "Not started",
    message =
      stage === "extract"
        ? "Extract the source to inspect its elements."
        : stage === "chunks"
          ? "Preview boundaries before building your index."
          : "Review the index fields above, then build your index.";
  if (busy) {
    title =
      status === "submitting"
        ? "Starting…"
        : status === "queued"
          ? "Queued"
          : info.running;
    message =
      j.poll_error ||
      (j.rate_wait?.until > Date.now() / 1000
        ? `Waiting ${Math.max(1, Math.ceil(j.rate_wait.until - Date.now() / 1000))}s before the next ${j.rate_wait.provider} request. Your work is still running.`
        : "") ||
      j.progress?.message ||
      j.events?.at(-1)?.message ||
      "Working in the background. Please wait; you can visit other screens.";
  } else if (status === "completed") {
    title = info.complete;
    const count =
      stage === "extract"
        ? (j?.result?.count ?? existing?.elements?.length)
        : stage === "chunks"
          ? (j?.result?.count ?? existing?.chunks?.length)
          : (j?.result?.chunks ?? existing?.chunks?.length);
    message =
      stage === "extract"
        ? `${fmt(count)} elements extracted. Review them in “Inspect your knowledge”.`
        : stage === "chunks"
          ? `${fmt(count)} chunks available to review.`
          : `${fmt(count)} chunks indexed. Your index is ready to use in Research agent.`;
  } else if (status === "failed" || status === "cancelled") {
    title = status === "failed" ? "Processing failed" : "Processing cancelled";
    message =
      j.error || "The operation stopped. Review your settings and try again.";
  }
  const elapsed = j?.started
    ? Math.max(0, (j.finished || Date.now() / 1000) - j.started)
    : null;
  return `<div class="pipeline-status ${busy ? "busy" : status}" aria-busy="${busy}"><div class="pipeline-status-heading">${busy ? '<span class="spinner" aria-hidden="true"></span>' : status === "completed" ? '<span class="pipeline-check" aria-hidden="true">✓</span>' : ""}<b>${esc(title)}</b></div><p>${esc(message)}</p>${progressBar(j, status)}<div class="actions section-space">${elapsed != null ? `<span class="small muted">${Math.floor(elapsed)}s ${j.finished ? "total" : "elapsed"}</span>` : ""}${j?.id && !j.id.startsWith("pending-") ? `<button type="button" class="btn small" data-action="trace" data-id="${esc(j.id)}">View run details</button>${busy ? `<button type="button" class="btn small" data-action="cancel" data-id="${esc(j.id)}" ${j.cancel ? "disabled" : ""}>${j.cancel ? "Stopping…" : "Cancel"}</button>` : ""}` : ""}${stage === "index" && status === "completed" && detail?.active_index ? '<button type="button" class="btn small" data-action="nav" data-page="research">Ask your document →</button>' : ""}</div></div>`;
}
function pipelineButton(stage) {
  const busy = ["submitting", "queued", "running"].includes(
    pipelineJob(stage)?.status,
  );
  return `<button class="btn ${stage === "chunks" ? "" : "primary"}" type="button" data-action="pipeline" data-stage="${stage}" ${pipelineBusy() || (stage !== "extract" && !detail?.extraction) ? "disabled" : ""}>${busy ? '<span class="spinner" aria-hidden="true"></span>' + pipelineStages[stage].running : pipelineStages[stage].action}</button>`;
}
function updatePipelineStatus() {
  if (page !== "processing") return;
  for (const stage of Object.keys(pipelineStages)) {
    for (const node of $$(`[data-pipeline-status="${stage}"]`))
      node.innerHTML = pipelineStatus(stage);
    const button = $(`[data-action="pipeline"][data-stage="${stage}"]`);
    if (button) button.outerHTML = pipelineButton(stage);
  }
}
function render() {
  if (!state.documents) return;
  const c = active();
  $("#app").innerHTML =
    `<div class="shell"><aside class="sidebar"><div><div class="brand"><img src="/static/icon.svg" alt="">Agentic RAG</div><div class="brand-sub">DOCUMENT KNOWLEDGE STUDIO</div></div><div><div class="nav-label">WORKSPACE</div><nav class="nav" aria-label="Main navigation">${Object.entries(
      names,
    )
      .map(
        ([id, name]) =>
          `<button data-action="nav" data-page="${id}" class="${page === id ? "active" : ""}"><span class="nav-icon">${icons[id]}</span>${name}</button>`,
      )
      .join(
        "",
      )}</nav></div><div><div class="nav-label">WORKFLOW</div><div class="nav"><button data-action="nav" data-page="processing"><span class="nav-icon">↳</span>Extract → inspect → index</button></div></div><div class="sidebar-footer"><b><span class="status-dot"></span>Stored on this computer</b>Local originals, memory and traces.<div class="section-space">Cloud processing sends selected files and chunks to your connected services.</div></div></aside><main class="main"><div class="topbar"><div class="breadcrumb">Workspace <b>/ ${names[page] || names.library}</b></div><div class="top-actions"><button class="connection-pill" data-action="nav" data-page="settings">${c ? '<span class="status-dot"></span>' + esc(c.name) : "○ Connect a model"}</button><span class="avatar">JD</span></div></div><div class="content">${banners()}${({ library: library, azure: azureWorkspace, processing: processing, research: research, monitoring: monitoring, evaluation: evaluationPage, settings: settings }[page] || library)()}</div></main></div>`;
}
function library() {
  const docs = state.documents;
  return (
    header(
      "A home for everything you know.",
      "Bring in a source. Keep its structure. Ask better questions.",
      `<button class="btn" data-action="browse">▧ Browse this computer</button>`,
    ) +
    `<div class="hero"><div><div class="eyebrow">MULTIMODAL · AGENTIC · LOCAL STORAGE</div><h2>Your files.<br>Connected intelligence.</h2><p>Turn documents, code and recordings into searchable knowledge—with the original evidence always one click away.</p><div class="actions section-space">${badge("Text & documents")}${badge("Images & tables")}${badge("Audio & video")}</div></div><div class="hero-visual"><div class="agentic-rag"></div><div class="hero-tag">ONE SOURCE. EVERY DIMENSION.</div></div></div>` +
    `<div class="grid two mb"><div class="card"><div class="card-header"><div><h3>Import a source</h3><p>Original files are copied into your local workspace.</p></div>${badge("01 / IMPORT")}</div><label class="dropzone" id="dropzone" for="file-upload"><div class="upload-icon">↥</div><strong>Drop files here, or click to browse</strong><p>PDF, Word, Excel, text, HTML, code, notebooks, images, audio and video · 250 MB per file</p><span class="btn small section-space">Choose files</span></label><input class="file-input" id="file-upload" type="file" multiple><div class="footer-note">For a software project, use “Browse this computer” and import its folder. Hidden files, secrets and build folders are excluded.</div></div>
 <div class="card"><div class="card-header"><div><h3>Import a webpage</h3><p>Save a local snapshot for inspection and retrieval.</p></div>${badge("HTML")}</div><form id="url-form"><div class="field"><label for="web-url">Public webpage URL</label><input id="web-url" name="url" type="url" required placeholder="https://example.com/article"></div><button class="btn primary" type="submit">Import webpage ↗</button></form><div class="divider"></div><div class="note">Choose how visuals are handled in Processing: describe them as text, or embed the visual content directly. Both paths link back to the original elements.</div><p class="footer-note">Web scripts never run. Remote image links stay as references; import image files to embed their pixels.</p></div></div>` +
    `<div class="card"><div class="card-header"><div><h3>Source library <span class="muted">${docs.length}</span></h3><p>Select one working document or repository folder.</p></div><button class="btn small" data-action="refresh">↻ Refresh</button></div>${docs.length ? '<div class="list">' + docs.map((d) => `<div class="doc-row ${d.id === docId ? "selected" : ""}"><div class="file-icon">${esc(d.is_bundle ? "REPO" : d.name.split(".").pop().toUpperCase().slice(0, 5))}</div><div class="grow"><div class="doc-name">${esc(d.name)}</div><div class="doc-meta"><span>${bytes(d.size)}</span><span>${date(d.created)}</span><span>${d.element_count ? fmt(d.element_count) + " elements" : ""}</span><span>${d.chunk_count ? fmt(d.chunk_count) + " chunks" : ""}</span></div></div>${badge(d.status, d.status === "indexed" ? "green" : "")}<div class="actions"><a class="btn small" href="${fileURL(d.path)}" target="_blank" rel="noopener">Original ↗</a><button class="btn small ${d.id === docId ? "primary" : ""}" data-action="use-doc" data-id="${d.id}">${d.id === docId ? "Continue →" : "Select →"}</button></div></div>`).join("") + "</div>" : empty("Your library is ready.", "Add your first file to get started.")}</div><p class="footer-note">Storage location: ${esc(state.storage)}</p>`
  );
}
function inputField(label, name, value, type = "text", help = "", extra = "") {
  return `<div class="field"><label for="${name}">${label}</label><input id="${name}" name="${name}" type="${type}" value="${esc(value)}" ${extra}>${help ? "<small>" + help + "</small>" : ""}</div>`;
}
function selectField(label, name, opts, value, help = "") {
  return `<div class="field"><label for="${name}">${label}</label><select id="${name}" name="${name}">${opts.map(([v, t]) => `<option value="${v}" ${v === value ? "selected" : ""}>${t}</option>`).join("")}</select>${help ? "<small>" + help + "</small>" : ""}</div>`;
}
function check(label, name, value) {
  return `<label class="check"><input type="checkbox" name="${name}" ${value ? "checked" : ""}>${label}</label>`;
}
function processing() {
  if (!chosen())
    return (
      header("Processing studio", "Configure your knowledge pipeline.") +
      empty("Add a source first.", "Import a document from the source library.")
    );
  const d = chosen(),
    ex = detail?.extraction,
    idx = detail?.indexes?.find((x) => x.id === d.active_index),
    cp = detail?.chunk_preview;
  const done = [true, !!ex, !!(cp || idx), !!idx];
  const modes =
    config.mode === "multimodal"
      ? [
          ["local-clip", "Local CLIP · image + text vectors"],
          ["gemini-multimodal", "Gemini Embedding 2 · image + text"],
          ["azure-vision", "Azure Vision · image + text vectors"],
        ]
      : [
          ["ollama-small", "Smaller · EmbeddingGemma (local Ollama)"],
          ["ollama-large", "Larger · Qwen3 Embedding 4B (local Ollama)"],
          ["local-text", "Local BGE · bundled text vectors"],
          ["provider-text", "Provider text embeddings"],
        ];
  return (
    header(
      "From source to searchable knowledge.",
      "Inspect each stage and choose how your content becomes evidence.",
    ) +
    selector() +
    `<div class="flow">${["Store source", "Extract elements", "Create chunks", "Build index"].map((x, i) => `<div class="flow-step ${done[i] ? "done" : ""}"><span class="step-number">${done[i] ? "✓" : i + 1}</span>${x}</div>`).join("")}</div>` +
    `<form id="pipeline-form">${azurePipelineControls()}<div class="card mb"><div class="card-header"><div><h3>Choose your retrieval mode</h3><p>Make this choice before processing your source.</p></div>${badge(config.mode === "multimodal" ? "DIRECT VISUAL RETRIEVAL" : config.mode ? "DESCRIPTION RETRIEVAL" : "CHOOSE A MODE", config.mode ? "green" : "amber")}</div><div class="mode-cards"><div class="mode"><label><input type="radio" name="mode" value="description" ${config.mode === "description" ? "checked" : ""} required><div><b>Describe visuals as text</b><p>Search text, table data and model-written visual descriptions. Retrieve the matching original asset with its chunk.</p></div></label></div><div class="mode"><label><input type="radio" name="mode" value="multimodal" ${config.mode === "multimodal" ? "checked" : ""} required><div><b>Use multimodal embeddings</b><p>Embed pixels from images, charts and table previews. A vision model can inspect retrieved originals when answering.</p></div></label></div></div><div class="note">Vision, embeddings and image generation are separate capabilities. A text-only model can use existing text and table data; it cannot create a faithful description of unseen pixels.</div></div>
 <div class="grid two mb"><div class="card"><div class="card-header"><div><h3>Extraction & preprocessing</h3><p>Originals stay available for inspection.</p></div>${badge("02 / EXTRACT")}</div><div class="field"><label for="pipeline-connection">Processing model</label><select id="pipeline-connection" name="connection_id">${options(state.connections, config.connection_id, "Offline extraction only")}</select></div>${check("Describe images, charts and tables using the vision model", "describe_visuals", config.describe_visuals)}${config.extraction_backend === "azure-document-intelligence" ? '<div class="note mb">Entity extraction: <b>Azure Document Intelligence · prebuilt-layout</b>. Optional visual descriptions run afterwards using the processing model. Azure handles OCR and document structure.</div>' : `${check("Vision layout: read page structure and classify charts (PDF)", "vision_layout", config.vision_layout)}${check("Try local OCR for scanned PDF pages (requires Tesseract)", "ocr", config.ocr)}${check("Fetch images from the same webpage origin (HTML snapshots)", "fetch_web_images", config.fetch_web_images)}`}<div class="divider"></div>${check("Exclude page headers and footers from the index", "strip_headers", config.strip_headers)}${check("Remove exact duplicate text chunks", "deduplicate", config.deduplicate)}${check("Mask email addresses and phone-like numbers in indexed text", "mask_pii", config.mask_pii)}<div class="note warn">Masking is a text heuristic, not full anonymization. Original files, previews, traces and cloud visual/transcription calls may still contain personal data.</div><div class="grid two section-space">${
   config.extraction_backend === "azure-document-intelligence"
     ? '<div class="note">Recordings and software projects use the local workflow. Azure Layout accepts supported documents and images.</div>'
     : selectField(
         "Audio/video transcription",
         "transcription",
         [
           ["local", "Local Whisper · runs on this computer"],
           ["provider", "Selected model provider"],
         ],
         config.transcription,
       )
 }${
   config.extraction_backend === "azure-document-intelligence"
     ? ""
     : selectField(
         "Local speech model",
         "whisper_model",
         [
           ["tiny", "Tiny · fastest"],
           ["base", "Base"],
           ["small", "Small"],
           ["medium", "Medium"],
         ],
         config.whisper_model,
       )
 }</div>${pipelineButton("extract")}<div class="section-space" data-pipeline-status="extract" role="status" aria-live="polite">${pipelineStatus("extract")}</div></div>
 <div class="card"><div class="card-header"><div><h3>Chunking & embedding settings</h3><p>Choose your strategy, then review the index fields below.</p></div>${badge("03–04 / INDEX")}</div>${selectField(
   "Chunking strategy",
   "strategy",
   [
     ["agentic", "Agentic · model plans topic boundaries"],
     ["semantic", "Semantic · local similarity boundaries"],
     ["document", "Document structure · preserve elements"],
     ["recursive", "Recursive · paragraph and sentence boundaries"],
     ["fixed", "Fixed size · predictable packets"],
   ],
   config.strategy,
 )}<div class="grid two">${inputField("Chunk size (characters)", "chunk_size", config.chunk_size, "number", "Target size; topic chunks may span up to 2×.", 'min="200" max="6000"')}${inputField("Overlap (characters)", "overlap", config.overlap, "number", "", 'min="0" max="1000"')}</div>${selectField("Embedding engine", "embedding", modes, config.embedding)}${config.embedding.startsWith("ollama-") ? inputField("Local Ollama endpoint", "ollama_url", config.ollama_url, "url", "Private text embeddings only. Install the selected model in Ollama first; no silent truncation or cloud fallback.") : ""}<div class="note mb">EmbeddingGemma and Qwen3 embed text, extracted tables and visual descriptions. For image pixels, choose multimodal mode with CLIP, Azure Vision or Gemini multimodal embeddings.</div><div class="field"><label for="embedding_connection_id">Embedding connection</label><select id="embedding_connection_id" name="embedding_connection_id">${options(
   state.connections.filter((x) =>
     ["openai", "azure", "gemini"].includes(x.provider),
   ),
   config.embedding_connection_id,
   "Use supported processing connection",
 )}</select><small>Cloud embeddings send content to this connection. Local models download once and then run locally.</small></div><details><summary>Run limits & estimated cost cap</summary><div class="grid two section-space">${inputField("Maximum provider calls", "max_calls", config.max_calls, "number", "", 'min="1" max="2000"')}${inputField("Estimated dollar cap (optional)", "budget_usd", config.budget_usd ?? "", "number", "Requires pricing; visual calls need the call limit.", 'min="0" step="0.01"')}</div></details><div class="actions section-space">${pipelineButton("chunks")}</div><div class="section-space" data-pipeline-status="chunks" role="status" aria-live="polite">${pipelineStatus("chunks")}</div></div></div>${indexFieldControls()}<div class="card mb"><div class="card-header"><div><h3>Build your vector index</h3><p>Ready after extraction, chunking settings and index-field configuration.</p></div>${badge("04 / BUILD")}</div>${pipelineButton("index")}<div class="section-space" data-pipeline-status="index" role="status" aria-live="polite">${pipelineStatus("index")}</div><p class="footer-note">A new index version is activated only after every vector is saved. Earlier versions remain available for reproducible tests.</p></div></form>` +
    `<div class="card"><div class="card-header"><div><h3>Inspect your knowledge</h3><p>${ex ? fmt(ex.elements.length) + " extracted elements · " + (idx ? fmt(idx.chunks.length) + " indexed chunks" : "index not built yet") : "Run extraction to see titles, text, tables, images and media references."}</p></div>${idx ? badge("Index " + short(idx.id), "green") : ""}</div>${ex ? `${ex.backend === "azure-document-intelligence" ? `<div class="note mb">${badge("AZURE LAYOUT", "green")} Returned pages: ${esc(ex.coverage.returned_pages.join(", "))} · ${ex.coverage.complete ? "Requested coverage verified" : "Partial or unverified coverage"}<div class="actions section-space"><button class="btn small" data-action="azure-json">Inspect raw Azure JSON</button><a class="btn small" href="${fileURL(ex.raw_json_asset)}">Download full JSON ↓</a></div></div>` : ""}<details class="mb"><summary>Extraction coverage & notices (${ex.warnings.length})</summary><div>${ex.warnings.map((w) => `<div class="note warn mb">${esc(w)}</div>`).join("")}</div></details><div class="tabs"><button data-action="inspect-tab" data-tab="chunks" class="${inspectTab === "chunks" ? "active" : ""}">Searchable chunks & visuals</button><button data-action="inspect-tab" data-tab="elements" class="${inspectTab === "elements" ? "active" : ""}">All extracted elements</button><button data-action="inspect-tab" data-tab="versions" class="${inspectTab === "versions" ? "active" : ""}">Index versions</button></div>${inspectTab === "elements" ? elementsView(ex.elements) : inspectTab === "chunks" ? chunksView() : versionsView(detail.indexes)}` : empty("Nothing extracted yet.", "Choose a retrieval mode and run extraction above.")}</div>`
  );
}
function elementsView(elements) {
  const kinds = [...new Set(elements.map((x) => x.kind))];
  const selected = elements.filter(
    (e) =>
      (!elementKind || e.kind === elementKind) &&
      (!elementSearch ||
        JSON.stringify(e).toLowerCase().includes(elementSearch.toLowerCase())),
  );
  return `<div class="toolbar"><select data-change="kind"><option value="">All element types (${elements.length})</option>${kinds.map((k) => `<option value="${k}" ${k === elementKind ? "selected" : ""}>${k} (${elements.filter((x) => x.kind === k).length})</option>`).join("")}</select><input id="element-search" value="${esc(elementSearch)}" placeholder="Search extracted content…"><button class="btn small" data-action="search-elements">Search</button></div><div class="inspect-grid">${selected
    .slice(0, 80)
    .map(
      (e) =>
        `<article class="element">${e.asset ? `<a href="${fileURL(e.asset)}" target="_blank" rel="noopener"><img src="${fileURL(e.asset)}" loading="lazy" alt="${esc(e.kind + " " + e.id)}"></a>` : ""}<div class="element-content"><div class="element-head"><div class="actions">${badge(e.kind)}<span class="small muted">${e.id}</span></div><span class="small muted">${e.page ? "Page " + e.page : e.sheet ? esc(e.sheet) : e.cell ? "Cell " + e.cell : ""}</span></div>${e.section ? "<p><b>" + esc(e.section) + "</b></p>" : ""}<p>${esc(e.text || "No native text. Inspect the source visual.")}</p>${e.description ? '<details class="section-space"><summary>Model-generated description</summary><div><p>' + esc(e.description) + "</p></div></details>" : ""}<div class="doc-meta">${e.description_status ? badge(e.description_status, e.description_status === "unverified" ? "amber" : "") : ""}${e.source_path ? "<span>" + esc(e.source_path) + "</span>" : ""}${e.start_seconds != null ? "<span>" + timecode(e.start_seconds) + " – " + timecode(e.end_seconds) + "</span>" : ""}</div><details class="section-space"><summary>Provenance & raw data</summary><div><pre>${json(e)}</pre>${e.data_asset ? `<a class="btn small" href="${fileURL(e.data_asset)}">Download element data</a>` : ""}${e.source_asset ? `<a class="btn small" href="${fileURL(e.source_asset)}">Open source file</a>` : ""}</div></details></div></article>`,
    )
    .join(
      "",
    )}</div>${selected.length > 80 ? '<p class="footer-note">Showing the first 80 matches. Filter by type or text to inspect more.</p>' : ""}`;
}
function chunkVisual(element) {
  const media = element.media_asset;
  const generatedText =
    !element.description && element.description_status === "model_generated";
  return `<article class="chunk-visual">${element.asset ? `<a href="${fileURL(element.asset)}" target="_blank" rel="noopener"><img src="${fileURL(element.asset)}" loading="lazy" alt="${esc(element.kind + " " + element.id)}"></a>` : ""}<div class="element-content"><div class="actions mb">${badge(element.kind)}<code>${esc(element.id)}</code>${element.page ? badge("Page " + element.page) : ""}</div>${element.description ? `<b>Generated description</b><p class="preserve-text">${esc(element.description)}</p>` : ""}${element.text ? `<b>${generatedText ? "Model-generated visual text" : "Extracted text / OCR"}</b><p class="preserve-text">${esc(element.text)}</p>` : ""}${element.rows ? `<details class="section-space"><summary>Extracted table rows</summary><pre>${json(element.rows)}</pre></details>` : ""}${media ? `<p>${timecode(element.start_seconds)}–${timecode(element.end_seconds)}</p><a class="btn small" href="${fileURL(media)}#t=${element.start_seconds}" target="_blank" rel="noopener">Open original recording ↗</a>` : ""}<p class="footer-note">Original element context. The exact text retained in this chunk is shown alongside it.</p></div></article>`;
}
function chunksView() {
  const target = selectedInspectionTarget();
  if (!target)
    return empty(
      "No chunks yet.",
      "Preview chunks or build an index to inspect source boundaries.",
    );
  const targets = inspectionTargets(),
    snapshot = chunkInspection;
  const picker = `<div class="field"><label for="inspection-snapshot">Inspect saved index or preview</label><select id="inspection-snapshot" data-change="inspection-snapshot">${targets.map((item) => `<option value="${esc(item.id)}" ${item.id === target.id ? "selected" : ""}>${esc(item.label)}</option>`).join("")}</select></div>`;
  if (!snapshot)
    return (
      picker +
      `<div class="note warn">${esc(chunkInspectionError || "Loading the saved chunks and source visuals…")}</div>`
    );
  const fields = snapshot.fields.filter((field) => field.searchable);
  const kinds = [
    ...new Set(snapshot.chunks.flatMap((chunk) => chunk.kinds || [])),
  ];
  const matches = snapshot.chunks.filter(
    (chunk) =>
      (!chunkKind || chunk.kinds?.includes(chunkKind)) &&
      (!chunkSearch ||
        (
          chunk.id +
          " " +
          chunk.text +
          " " +
          JSON.stringify(chunk.searchable_values)
        )
          .toLowerCase()
          .includes(chunkSearch.toLowerCase())),
  );
  const pages = Math.max(1, Math.ceil(matches.length / 20));
  chunkPage = Math.min(chunkPage, pages - 1);
  const chunks = matches.slice(chunkPage * 20, (chunkPage + 1) * 20);
  return (
    picker +
    `<div class="note mb">${target.id.startsWith("preview:") ? "Preview only: these chunks have not been published to an index." : "Showing the saved index and its original extraction revision."} Unsaved field settings take effect after a new build.<div class="actions section-space">Searchable fields: ${fields.map((field) => badge(field.label)).join("")}</div></div><div class="toolbar"><select data-change="chunk-kind" aria-label="Filter chunks by element type"><option value="">All chunk types</option>${kinds.map((kind) => `<option value="${esc(kind)}" ${kind === chunkKind ? "selected" : ""}>${esc(kind)}</option>`).join("")}</select><input id="chunk-search" value="${esc(chunkSearch)}" placeholder="Find a chunk ID, title or content…" aria-label="Find a chunk"><button class="btn small" data-action="search-chunks">Search chunks</button></div><p class="small muted mb">${fmt(matches.length)} matching chunks · page ${chunkPage + 1} of ${pages}. Open a chunk to inspect its full contents and linked visuals.</p><div class="list">${
      chunks
        .map((chunk, position) => {
          const visuals = chunk.elements.filter(
            (element) => element.asset || element.rows || element.media_asset,
          );
          return `<details class="knowledge-chunk" ${position === 0 ? "open" : ""}><summary><code>${esc(chunk.id)}</code> · ${esc(chunk.title || chunk.kinds?.join(", ") || "Untitled chunk")}<span class="small muted"> · ${fmt(chunk.text.length)} characters${visuals.length ? " · " + visuals.length + " source visuals / recordings" : ""}</span></summary><div class="knowledge-chunk-body ${visuals.length ? "with-visuals" : ""}"><div><h3 class="mb">Searchable field values</h3>${fields.map((field) => `<div class="indexed-field"><b>${esc(field.label)}</b> <code>${esc(field.name)}</code><div class="indexed-value preserve-text">${esc(Array.isArray(chunk.searchable_values[field.name]) ? chunk.searchable_values[field.name].join(", ") : (chunk.searchable_values[field.name] ?? "")) || '<span class="muted">Empty in this chunk</span>'}</div></div>`).join("")}${!fields.some((field) => field.name === "content") ? `<div class="indexed-field"><b>Chunk text used for embeddings</b><p class="small muted">Keyword search is disabled for the content field in this saved index.</p><div class="indexed-value preserve-text">${esc(chunk.text)}</div></div>` : ""}<div class="doc-meta section-space">Source elements: ${esc(chunk.element_ids.join(", "))} · Pages: ${esc(chunk.pages?.join(", ") || "n/a")}</div><details class="section-space"><summary>Combined keyword-search text</summary><pre class="preserve-text">${esc(chunk.keyword_text)}</pre></details><details class="section-space"><summary>Chunk metadata & source offsets</summary><pre>${json({ offsets: chunk.offsets, metadata: chunk.filter_metadata })}</pre></details></div>${visuals.length ? `<div class="chunk-visuals">${visuals.map(chunkVisual).join("")}</div>` : ""}</div></details>`;
        })
        .join("") ||
      empty("No matching chunks.", "Clear the search or element-type filter.")
    }</div><div class="actions section-space"><button class="btn small" data-action="chunk-page" data-page="${chunkPage - 1}" ${chunkPage === 0 ? "disabled" : ""}>← Previous</button><span class="small muted">${chunkPage + 1} / ${pages}</span><button class="btn small" data-action="chunk-page" data-page="${chunkPage + 1}" ${chunkPage + 1 >= pages ? "disabled" : ""}>Next →</button></div>`
  );
}
function versionsView(indexes) {
  return indexes.length
    ? `<div class="table-wrap"><table><thead><tr><th>Index</th><th>Mode / strategy</th><th>Engine</th><th>Chunks</th><th>Created</th></tr></thead><tbody>${indexes.map((i) => `<tr><td><code>${esc(i.id)}</code>${i.id === chosen().active_index ? " " + badge("active", "green") : ""}</td><td>${esc(i.config.mode)} / ${esc(i.config.strategy)}</td><td>${esc(i.config.embedding)}<br>${i.backend === "azure-ai-search" ? badge("AZURE SEARCH", "green") + "<br><code>" + esc(i.search_index) + "</code>" : badge("LOCAL")}</td><td>${i.chunks.length}</td><td>${date(i.created)}</td></tr>`).join("")}</tbody></table></div>`
    : empty(
        "No index versions.",
        "Build an index to create your first snapshot.",
      );
}
function timecode(s) {
  s = Math.floor(s || 0);
  return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
}
function sourceView(c) {
  return `<div class="source-card" data-source-id="${esc(c.id)}"><div class="actions">${badge(c.id, "green")}<span class="small muted">${esc(c.pages?.length ? "Page " + c.pages.join(", ") : c.title || c.kinds?.join(", "))}</span></div><p>${esc(c.text)}</p>${(c.page_previews || []).map((p) => `<a class="btn small section-space" href="${fileURL(p.asset)}" target="_blank" rel="noopener">Open original page ${p.page} ↗</a>`).join("")}${(c.assets || []).map((a) => `<a href="${fileURL(a)}" target="_blank" rel="noopener"><img src="${fileURL(a)}" loading="lazy" alt="Retrieved source visual"></a>`).join("")}${(c.cloud_references || []).map((a) => `<a class="btn small section-space" href="${a.url}" target="_blank" rel="noopener">Private cloud reference · ${esc(a.name)} ↗</a>`).join("")}${(
    c.elements || []
  )
    .filter((e) => e.media_asset)
    .map(
      (e) =>
        `<div class="small muted">Transcript ${timecode(e.start_seconds)}–${timecode(e.end_seconds)}</div>${/\.(mp4|mov|webm|mkv|avi)$/i.test(e.media_asset) ? `<video controls preload="metadata" src="${fileURL(e.media_asset)}#t=${e.start_seconds},${e.end_seconds}"></video>` : `<audio controls preload="metadata" src="${fileURL(e.media_asset)}#t=${e.start_seconds},${e.end_seconds}"></audio>`}<a class="small" href="${fileURL(e.media_asset)}#t=${e.start_seconds}" target="_blank" rel="noopener">Open original recording ↗</a>`,
    )
    .join("")}${(c.elements || [])
    .filter((e) => e.data_asset || e.source_asset)
    .map(
      (e) =>
        `<div class="actions section-space">${e.data_asset ? `<a class="btn small" href="${fileURL(e.data_asset)}">Element data ↓</a>` : ""}${e.source_asset ? `<a class="btn small" href="${fileURL(e.source_asset)}" target="_blank" rel="noopener">Original source file ↗</a>` : ""}</div>`,
    )
    .join(
      "",
    )}<details class="section-space"><summary>Retrieval & provenance</summary><div><pre>${json({ rank: c.rank, score: c.score, cosine: c.cosine, keyword_rank: c.keyword_rank, vector_rank: c.vector_rank, filter_metadata: c.filter_metadata, search_mode: c.search_mode, retrieval_backend: c.retrieval_backend, reranker_score: c.reranker_score, element_ids: c.element_ids, pages: c.pages, offsets: c.offsets, elements: (c.elements || []).map((e) => ({ source_name: e.source_name, source_path: e.source_path, page: e.page, sheet: e.sheet, cell: e.cell, line_start: e.line_start, line_end: e.line_end, row_start: e.row_start, row_end: e.row_end })) })}</pre></div></details></div>`;
}
function capabilityNotice() {
  const c = state.connections.find(
    (x) =>
      x.id === (chatOptions.connection_id ?? state.settings.active_connection),
  );
  const notes = [];
  if (c && !c.vision)
    notes.push(
      "This answer model is text-only. Retrieved visuals stay available as references; the model receives only available source text and descriptions.",
    );
  if (c?.image_generation_notice) notes.push(c.image_generation_notice);
  return notes
    .map((text) => '<div class="note warn mb">' + esc(text) + "</div>")
    .join("");
}
function research() {
  const d = chosen();
  if (!d?.active_index)
    return (
      header(
        "Ask your knowledge.",
        "A research partner with evidence at every step.",
      ) +
      selector() +
      empty(
        "Build an index first.",
        "Open Processing, inspect the extracted elements, then create your vector index.",
      )
    );
  return (
    header(
      "Ask your knowledge.",
      "Clarify the question. Investigate the source. Keep the evidence.",
      `<button class="btn" data-action="new-chat">＋ New chat</button>`,
    ) +
    selector() +
    capabilityNotice() +
    `<div class="split"><div><div class="chat-area" id="chat-area">${messages.length ? messages.map((m) => `<div class="message ${m.role}"><div class="message-label">${m.role === "user" ? "YOU" : "✧ RESEARCH AGENT"}</div>${m.role === "assistant" ? formatText(m.content) : esc(m.content)}</div>`).join("") : `<div class="chat-welcome"><div class="symbol">✧</div><h2>Where should we look?</h2><p>Ask about your document’s text, visuals or tables. I’ll clarify the scope before investigating.</p>${["Explain the key ideas and cite the source.", "What do the charts and tables tell us?", "Find the most useful sections for my project."].map((t) => `<button class="suggestion" data-action="suggest" data-text="${esc(t)}">${t} ↗</button>`).join("")}</div>`}</div>${pending ? `<div class="note mb">Clarification requested for: <b>${esc(pending.original_question)}</b><br>Reply below, or continue with the whole document.</div>` : ""}<form id="chat-form"><div class="composer"><textarea id="chat-message" name="message" placeholder="${pending ? "Tell me the scope or detail you want…" : "Ask a question about " + esc(d.name) + "…"}" required></textarea><div class="composer-footer"><span class="chat-options">${pending ? "Your reply sets the scope" : "Answers include original source references"}</span><div class="actions">${pending ? '<button type="button" class="btn small" data-action="clarify-default">Whole document</button>' : ""}<button class="btn primary" type="submit">${pending ? "Investigate →" : "Ask Agentic RAG ↗"}</button></div></div></div>${retrievalControls()}<div class="grid two section-space"><div class="field"><label for="chat-connection">Answer model</label><select id="chat-connection" name="connection_id">${options(state.connections, chatOptions.connection_id ?? state.settings.active_connection, "Source retrieval preview only")}</select></div><div class="field"><label for="chat-passes">Maximum investigation passes</label><select id="chat-passes" name="max_passes">${[1, 2, 3, 4].map((n) => `<option value="${n}" ${chatOptions.max_passes === n ? "selected" : ""}>${n} · ${["", "economical", "standard", "thorough", "extended"][n]}</option>`).join("")}</select></div></div><div class="actions chat-options">${check("Retrieval preview (no generated answer)", "preview", chatOptions.preview)}${check("Generate a new illustration (requires image model)", "generate_image", chatOptions.generate_image)}</div></form><div class="card section-space"><details><summary>Memory, skills & tools</summary><div><div class="note mb">Short-term context: recent turns in this chat. Long-term memory: document-scoped preferences and a visible record of the latest research question. Memory is context, not source evidence.</div><div class="actions mb"><button class="btn small" data-action="show-memory">Manage memory</button><button class="btn small" data-action="show-sessions">Open a previous chat</button></div>${Object.entries(
      state.skills,
    )
      .map(([k, v]) => `<p class="small mb"><b>${esc(k)}</b><br>${esc(v)}</p>`)
      .join("")}<pre>${json(state.tools)}</pre></div></details></div></div>
 <aside><div class="card"><div class="card-header"><div><h3>Evidence panel</h3><p>${chatResult?.sources?.length ? chatResult.sources.length + " retrieved chunks" : "Original sources will appear here."}</p></div>${badge("GROUNDED")}</div>${chatResult ? `${chatResult.context_policy ? '<div class="note mb">' + esc(chatResult.context_policy.effort) + " effort · text input cap " + fmt(chatResult.context_policy.context_chars) + " characters · up to " + chatResult.context_policy.images + " visual inputs. See the trace for actual context usage and trimming.</div>" : ""}${chatResult.status === "preview" ? '<div class="note warn mb">Retrieval preview: source excerpts only.</div>' : ""}${chatResult.citation_warning ? '<div class="note warn mb">' + esc(chatResult.citation_warning) + "</div>" : ""}${(chatResult.sources || []).map(sourceView).join("")}${chatResult.image_error ? '<div class="note warn section-space">Image generation: ' + esc(chatResult.image_error) + "</div>" : ""}${(chatResult.generated_images || []).map((i) => `<div class="source-card">${badge("Generated illustration", "amber")}<img src="${fileURL(i.asset)}" alt="Generated illustration"><p>Created from retrieved evidence; this is not an original source.</p></div>`).join("")}${chatResult.run_id ? `<div class="actions section-space"><button class="btn small" data-action="trace" data-id="${chatResult.run_id}">View run trace</button><button class="btn small" data-action="review" data-id="${chatResult.run_id}">Rate answer</button></div>` : ""}` : empty("Evidence stays close.", "Each match links to source text, its page, its visual assets or the original recording.")}</div></aside></div>`
  );
}
function monitoring() {
  const m = monitor;
  if (!m)
    return (
      header(
        "Every step, in view.",
        "Watch indexing, retrieval and model work as they happen.",
      ) + empty("Loading monitoring…", "")
    );
  const su = m.summary;
  return (
    header(
      "Every step, in view.",
      "Actual activity, usage and available cost estimates.",
      `<button class="btn" data-action="refresh-monitor">↻ Refresh</button>`,
    ) +
    `<div class="grid four mb">${[
      ["Provider calls", fmt(su.calls), su.failed_calls + " failed"],
      [
        "Input / output tokens",
        fmt(su.input_tokens) + " / " + fmt(su.output_tokens),
        "Provider-reported usage",
      ],
      [
        "Known estimated cost",
        price(su.estimated_known_cost),
        "Estimates, not a provider invoice",
      ],
      [
        "Unpriced calls",
        fmt(su.unpriced_calls),
        "Missing prices or usage stay unknown",
      ],
    ]
      .map(
        ([l, v, n]) =>
          `<div class="stat"><div class="stat-label">${l}</div><div class="stat-value">${v}</div><small>${n}</small></div>`,
      )
      .join(
        "",
      )}</div><div class="note warn mb">Free-tier access and quota are enforced by the provider. Unknown costs are never shown as zero. Set your applicable rates in Connections to price future calls; local model costs exclude hardware and electricity.</div>${localEmbeddingMonitoring(m)}${cloudMonitoring(m)}<div class="card mb"><div class="card-header"><div><h3>Run history</h3><p>Indexing stages, clarification, agent activity and evaluation jobs.</p></div>${badge("LOCAL TRACE STORE")}</div><div class="table-wrap"><table><thead><tr><th>Run</th><th>Operation</th><th>Status</th><th>Started</th><th>Duration</th><th></th></tr></thead><tbody>${m.jobs.map((j) => `<tr><td><code>${short(j.id)}</code></td><td>${esc(j.kind)}</td><td>${badge(j.status, j.status === "failed" ? "red" : j.status === "completed" ? "green" : "amber")}</td><td>${date(j.created)}</td><td>${j.finished && j.started ? (j.finished - j.started).toFixed(1) + "s" : "—"}</td><td><button class="btn small" data-action="trace" data-id="${j.id}">Inspect →</button></td></tr>`).join("")}</tbody></table></div>${!m.jobs.length ? empty("No runs yet.", "Import and process a source to see live activity.") : ""}</div><div class="card"><div class="card-header"><div><h3>Model calls</h3><p>Inspect requests, outputs, usage, visual inputs and failures.</p></div></div><div class="list">${m.calls
      .slice(0, 60)
      .map(
        (c) =>
          `<details class="source-card"><summary>${esc(c.model)} · ${esc(c.operation)} ${badge(c.status, c.status === "failed" ? "red" : "")} <span class="muted">${c.duration?.toFixed(1) || "…"}s · ${price(c.cost_usd)}</span></summary><div><div class="doc-meta"><span>${c.input_tokens ?? "?"} input / ${c.output_tokens ?? "?"} output tokens</span><span>${c.visual_inputs || 0} visual inputs</span></div>${c.error ? '<div class="note error section-space">' + esc(c.error) + "</div>" : ""}<h3 class="section-space">Request preview</h3><pre>${esc(c.input_preview)}</pre><h3>Response preview</h3><pre>${esc(c.output_preview || "No text output recorded.")}</pre><details><summary>Usage & pricing snapshot</summary><div><pre>${json({ usage: c.usage, prices: c.prices, price_status: c.price_status, run_id: c.run_id })}</pre></div></details></div></details>`,
      )
      .join("")}</div></div>`
  );
}
function evaluationPage() {
  const d = chosen();
  return (
    header(
      "Measure. Compare. Improve.",
      "Test against your ground truth and review the actual answers.",
    ) +
    selector() +
    `<div class="grid two mb"><div class="card"><div class="card-header"><div><h3>Ground-truth datasets</h3><p>Each import creates an immutable benchmark snapshot.</p></div>${badge("01 / CURATE")}</div><div class="note mb">Use questions, expected answers and optional expected chunk IDs from this exact index. Mark references verified only after human review. Unverified references remain labeled.</div><form id="dataset-form"><input id="dataset-file" type="file" accept=".json,.csv" required ${!d?.active_index ? "disabled" : ""}><button class="btn primary section-space" type="submit" ${!d?.active_index ? "disabled" : ""}>Import benchmark</button></form><div class="actions section-space"><a class="btn small" href="/api/examples/ground-truth-template.csv">CSV template ↓</a><a class="btn small" href="/api/examples/ground-truth-template.json">JSON template ↓</a></div><div class="divider"></div>${
      state.datasets
        .filter((x) => x.document_id === docId)
        .map(
          (ds) =>
            `<div class="doc-row"><div class="grow"><div class="doc-name">${esc(ds.name)}</div><div class="doc-meta">${ds.cases.length} cases · ${date(ds.created)}<br>Index ${short(ds.index_id)}</div></div><button class="btn small" data-action="view-dataset" data-id="${ds.id}">Inspect</button></div>`,
        )
        .join("") ||
      empty(
        "No benchmark for this source.",
        "Download a template, add verified references and import it.",
      )
    }</div>
 <div class="card"><div class="card-header"><div><h3>Run a controlled comparison</h3><p>Pin the source, chunks, prompt and test cases.</p></div>${badge("02 / COMPARE")}</div><form id="evaluation-form"><div class="field"><label for="eval-dataset">Saved benchmark</label><select id="eval-dataset" name="dataset_id" required><option value="">Choose a benchmark</option>${state.datasets
   .filter((x) => x.document_id === docId)
   .map(
     (ds) =>
       `<option value="${ds.id}">${esc(ds.name)} · ${ds.cases.length} cases · ${short(ds.index_id)}</option>`,
   )
   .join(
     "",
   )}</select></div><div class="field"><label>Models to compare (up to 4)</label>${state.connections.map((c) => `<label class="check"><input type="checkbox" name="connection_ids" value="${c.id}" ${c.id === state.settings.active_connection ? "checked" : ""}>${esc(c.name)} · ${esc(c.model)}</label>`).join("") || '<p class="small">Add a provider connection in Settings.</p>'}</div><div class="field"><label for="eval-judge">Optional evidence judge</label><select id="eval-judge" name="judge_id">${options(state.connections, "", "No model judge · deterministic metrics only")}</select><small>Judge calls use provider quota and may share the answer model’s biases.</small></div><div class="grid two">${inputField("Calls per answer", "max_calls", 10, "number", "", 'min="1" max="30"')}${inputField("Retrieval passes", "max_passes", 2, "number", "", 'min="1" max="4"')}</div><button class="btn primary" type="submit">Run evaluation →</button></form><div class="footer-note">Each model starts with isolated conversation state. Reference evidence and actual retrieval are kept separate. Failed calls are recorded separately from quality scores.</div></div></div>
 <div class="card"><div class="card-header"><div><h3>Performance history</h3><p>Review metrics and per-question answers, then record a human rating.</p></div></div><div class="field"><label for="eval-history">Evaluation run</label><select id="eval-history" data-change="evaluation"><option value="">Choose a saved run</option>${state.evaluations
   .filter(
     (x) =>
       !docId ||
       state.datasets.some(
         (ds) => ds.id === x.dataset_id && ds.document_id === docId,
       ),
   )
   .map(
     (e) =>
       `<option value="${e.id}" ${evalId === e.id ? "selected" : ""}>${date(e.created)} · ${e.models?.map((c) => c.model).join(" vs ")} · ${e.status}</option>`,
   )
   .join(
     "",
   )}</select></div>${evaluation ? evaluationResults(evaluation) : empty("A useful baseline starts here.", "Run your first benchmark, inspect errors and revise one setting at a time.")}</div>`
  );
}
function evaluationResults(e) {
  const fields = [
    ["token_f1", "Token F1"],
    ["rouge_l_f1", "ROUGE-L"],
    ["context_precision", "Precision"],
    ["context_recall", "Recall"],
    ["mrr", "MRR"],
    ["ndcg", "nDCG"],
    ["judge_faithfulness", "Judge support"],
  ];
  return `<div class="note mb">Lexical overlap is descriptive, not factual accuracy. Retrieval scores require verified expected chunk IDs. Citation validity checks IDs, not whether every claim is supported. Missing metrics are shown as “—”.</div><div class="table-wrap"><table><thead><tr><th>Model</th><th>Completed / total</th>${fields.map(([k, l]) => "<th>" + l + "</th>").join("")}</tr></thead><tbody>${(e.summary || []).map((m) => `<tr><td>${esc(m.model)}</td><td>${m.completed} / ${m.total}</td>${fields.map(([k]) => `<td title="${m.metrics[k]?.applicable_cases || 0} applicable cases">${metric(m.metrics[k]?.mean)}</td>`).join("")}</tr>`).join("")}</tbody></table></div><div class="list section-space">${(e.results || []).map((r) => `<details class="source-card"><summary>${esc(r.case.id)} · ${esc(r.model)} · ${badge(r.status, r.status === "failed" ? "red" : "green")} ${badge(r.case.reference_status, r.case.reference_status === "verified" ? "green" : "amber")}</summary><div><h3>${esc(r.case.question)}</h3><p><b>Expected answer</b><br>${esc(r.case.reference_answer || "Clarification expected")}</p>${r.error ? `<div class="note error">${esc(r.error)}</div>` : `<p><b>Actual answer</b><br>${esc(r.result.answer)}</p><pre>${json(r.metrics)}</pre><div class="doc-meta">${r.latency?.toFixed(2) ?? "—"}s · ${r.calls ?? 0} calls · ${price(r.cost_usd)}</div><details class="section-space"><summary>Actual retrieved sources</summary><div>${r.result.sources.map(sourceView).join("")}</div></details>`}<div class="actions section-space"><button class="btn small" data-action="review" data-id="${r.run_id}">Human review</button><button class="btn small" data-action="trace" data-id="${r.run_id}">Inspect model trace</button></div>${e.reviews?.[r.run_id] ? '<p class="section-space">Human rating: ' + esc(e.reviews[r.run_id].score) + "/5 · " + esc(e.reviews[r.run_id].note) + "</p>" : ""}</div></details>`).join("")}</div><details class="section-space"><summary>Reproducibility snapshot</summary><div><pre>${json({ dataset_hash: e.dataset_hash, index_fingerprint: e.index_fingerprint, source_hash: e.source_hash, prompt_hash: e.prompt_hash, guidance: e.guidance, pipeline: e.pipeline_version, pipeline_fingerprint: e.pipeline_fingerprint, models: e.models })}</pre><button class="btn small" data-action="export-eval" data-id="${e.id}">Download results JSON ↓</button></div></details>`;
}
let modelInventory = null,
  copyFromConnection = "";
const providerInfo = (id) =>
  (state.provider_catalog || []).find((x) => x.id === id) || {
    label: id,
    models: [],
    defaults: {},
    notice: "",
  };
function connectionDefaults(provider) {
  return {
    name: providerInfo(provider).label,
    provider,
    model: "",
    endpoint: "",
    embedding_model: "",
    image_model: "",
    vision: false,
    account_tier: "unknown",
    max_output: 3000,
    context_chars: 40000,
    capacity_profile: "custom",
    ollama_context_tokens: 16384,
    ...providerInfo(provider).defaults,
  };
}
function connectionBody(form) {
  const data = new FormData(form),
    obj = Object.fromEntries(data);
  for (const key of [
    "input_price",
    "output_price",
    "cached_price",
    "embedding_price",
    "image_price",
    "requests_per_minute",
    "tokens_per_minute",
    "requests_per_day",
  ])
    obj[key] = obj[key] === "" || obj[key] == null ? null : Number(obj[key]);
  obj.vision = data.has("vision");
  obj.free_tier = obj.account_tier === "free";
  for (const key of ["max_output", "context_chars", "ollama_context_tokens"])
    if (obj[key] != null) obj[key] = Number(obj[key]);
  obj.endpoint = obj.endpoint || "";
  obj.embedding_model = obj.embedding_model || "";
  obj.image_model = obj.image_model || "";
  return obj;
}
function providerPacingControls(c, tier) {
  if (!["gemini", "groq"].includes(c.provider)) return "";
  const free = tier === "free",
    rpm = c.provider === "gemini" ? 2 : 6,
    tpm = c.provider === "gemini" ? 10000 : 6000;
  return `<details class="mb" ${free ? "open" : ""}><summary>Request pacing & provider allowance</summary><div class="note section-space mb">${free ? `Free-tier pacing is automatic. Blank limits use conservative app defaults: ${rpm} requests/minute and ${fmt(tpm)} estimated tokens/minute.` : "Enter limits to pace this connection. Blank paid-tier limits leave pacing to the provider."} These are app settings, not verified account quotas. Match your account’s limits in Google AI Studio or Groq Console. All profiles share a provider allowance unless you set a different quota group.</div><div class="grid two">${inputField("Requests per minute", "requests_per_minute", c.requests_per_minute ?? "", "number", free ? `Default: ${rpm}. Calls are spaced evenly.` : "Optional", 'min="1" max="10000"')}${inputField("Estimated tokens per minute", "tokens_per_minute", c.tokens_per_minute ?? "", "number", "Text, output and visual reserves are estimates, not exact provider token counts.", 'min="128" max="100000000"')}${inputField("Daily request cap (optional)", "requests_per_day", c.requests_per_day ?? "", "number", "App-only rolling 24-hour cap. Provider reset times may differ.", 'min="1" max="1000000"')}${inputField("Quota group (optional)", "quota_group", c.quota_group || "", "text", "Use the same group for profiles sharing a project or organization. Blank shares across this provider.", 'maxlength="100" pattern="[A-Za-z0-9 ._-]*"')}</div><p class="footer-note">The app honors reported cooldowns and keeps its allowance across restarts. Other applications using your account can still consume quota. Requests are not automatically retried or switched to a paid model.</p></details>`;
}
function modelPicker(c) {
  const live = modelInventory?.provider === c.provider ? modelInventory : null;
  const models = live
    ? live.models.filter((x) => x.selectable !== false).map((x) => x.id)
    : providerInfo(c.provider).models;
  return `<div class="field"><label for="model-choice">${live ? (c.provider === "ollama" ? "Installed chat models" : "Models from your provider") : "Starter model choices"}</label><select id="model-choice"><option value="">Enter a model ID below</option>${models.map((id) => `<option value="${esc(id)}" ${id === c.model ? "selected" : ""}>${esc(id)}</option>`).join("")}</select><small>${live ? esc(live.notice) : "Starter choices are examples. Load your model list to see the current inventory; then test the selected model."}</small></div><div class="actions mb"><button class="btn" type="button" data-action="discover-models">${c.provider === "ollama" ? "Find installed models" : "Load my model list"}</button></div>`;
}
function settings() {
  const cs = state.connections,
    c =
      connectionDraft ||
      cs.find((x) => x.id === editConnection) ||
      connectionDefaults("gemini");
  const local = c.provider === "ollama",
    embeds = ["openai", "azure", "gemini"].includes(c.provider),
    tier = c.account_tier || (c.free_tier ? "free" : "unknown");
  return (
    header(
      "Connections that fit your workflow.",
      "Gemini · OpenAI · Groq · local Ollama. Azure remains available for your cloud workflow.",
    ) +
    `
 <div class="grid two settings-grid"><div class="card"><div class="card-header"><div><h3>Your model connections</h3><p>Save a separate profile for each model you want to compare.</p></div><button class="btn small" data-action="new-connection">＋ Add</button></div>
 ${cs
   .map(
     (
       x,
     ) => `<div class="provider-card ${x.id === state.settings.active_connection ? "active" : ""}"><div class="card-header"><div><h3>${esc(x.name)}</h3><p>${esc(providerInfo(x.provider).label)} · ${esc(x.model)}</p></div>${badge(x.tested_text ? "connected" : "not tested", x.tested_text ? "green" : "amber")}</div>
 ${x.image_generation_notice ? '<div class="note warn mb">' + esc(x.image_generation_notice) + "</div>" : ""}<div class="actions mb">${badge(x.vision ? (x.tested_vision ? "vision verified" : "vision enabled · unverified") : "text only", x.tested_vision ? "green" : "")}${badge(x.provider === "ollama" ? "local · no API key" : (x.account_tier || (x.free_tier ? "free" : "unknown")) === "unknown" ? "account tier unspecified" : "user-declared " + (x.account_tier || (x.free_tier ? "free" : "unknown")) + " tier")}${x.image_model ? badge("image generation configured") : ""}</div>
 <div class="actions"><button class="btn small ${x.id === state.settings.active_connection ? "primary" : ""}" data-action="activate-connection" data-id="${x.id}">${x.id === state.settings.active_connection ? "Active" : "Use for chat"}</button><button class="btn small" data-action="test-connection" data-id="${x.id}">Test connection</button><button class="btn small" data-action="models" data-id="${x.id}">Choose model</button><button class="btn small" data-action="edit-connection" data-id="${x.id}">Edit</button><button class="btn small" data-action="copy-connection" data-id="${x.id}">Add another model</button></div></div>`,
   )
   .join("")}
 <div class="note">Keys are encrypted locally and never returned by the app. A model list does not establish quota or image support. Local model calls have zero API fees; hardware and electricity are excluded.</div>
 <div class="divider"></div><form id="settings-form"><h3 class="mb">Workspace guidance & memory</h3><div class="field"><label for="guidance">Project guidance</label><textarea id="guidance" name="guidance" maxlength="12000">${esc(state.settings.guidance)}</textarea><small>Saved guidance is pinned into each evaluation run. It cannot override source-evidence rules.</small></div>${check("Enable conversation context and document-scoped long-term memory", "memory_enabled", state.settings.memory_enabled)}<button class="btn" type="submit">Save workspace settings</button></form></div>
 <div class="card"><div class="card-header"><div><h3>${editConnection ? "Edit connection" : "Add a connection"}</h3><p>${local ? "Connect to Ollama running on this computer." : "Bring your provider key and choose the model."}</p></div>${badge(c.provider.toUpperCase())}</div>
 <form id="connection-form">${inputField("Connection name", "name", c.name, "text", "", 'required maxlength="80"')}
 ${selectField(
   "Provider",
   "provider",
   (state.provider_catalog || []).map((x) => [x.id, x.label]),
   c.provider,
 )}<div class="note mb">${esc(providerInfo(c.provider).notice)}</div>
 ${c.provider === "azure" ? azureModelAuthFields(c) + inputField("Azure resource endpoint", "endpoint", c.endpoint || "", "url", "https://your-resource.openai.azure.com", "required") : ""}
 ${local ? inputField("Local Ollama endpoint", "endpoint", c.endpoint || "http://127.0.0.1:11434", "url", "Loopback or host.docker.internal only. No cloud fallback.", "required") : ""}
 ${local ? "" : inputField(editConnection || copyFromConnection ? "API key (leave empty to keep current)" : "API key", "api_key", c.api_key || "", "password", "Stored encrypted with a separate local secret key.", editConnection || copyFromConnection || (c.provider === "azure" && c.auth_mode && c.auth_mode !== "api-key") ? 'autocomplete="new-password"' : 'required autocomplete="new-password"')}
 ${modelPicker(c)}${inputField("Model / deployment ID", "model", c.model, "text", local ? "Default: qwen3:8b. The model must already be installed in Ollama." : "Use the exact API model or Azure deployment ID available in your account.", 'required maxlength="100"')}
 ${selectField(
   "Account tier",
   "account_tier",
   local
     ? [["local", "Local · no provider API fees"]]
     : [
         ["unknown", "Unspecified / provider managed"],
         ["free", "Free tier / trial"],
         ["paid", "Paid tier"],
       ],
   tier,
   "This records your account setup. It does not change provider billing, unlock models or assume zero prices.",
 )}${providerPacingControls(c, tier)}
 ${embeds ? inputField("Text embedding model / deployment", "embedding_model", c.embedding_model || "", "text", "Used only for Provider text embeddings. Gemini multimodal uses gemini-embedding-2.") : '<div class="note mb">For indexing, select local EmbeddingGemma / Qwen3 Embedding, CLIP, or a separate supported cloud embedding connection in Processing studio.</div>'}
 ${embeds ? inputField("Image generation model / deployment (optional)", "image_model", c.image_model || "", "text", "Image generation is separate from image understanding and requires model access and quota.") : ""}
 ${check("This answer model accepts images (verify with Test)", "vision", c.vision)}
 <div class="grid two section-space">${selectField(
   "Model / context capacity preset",
   "capacity_profile",
   [
     ["small", "Smaller model · compact context"],
     ["large", "Larger model · extended context"],
     ["custom", "Custom capacity"],
   ],
   c.capacity_profile || "custom",
   "A preset sets limits, not model capabilities. Match them to your actual model.",
 )}
 <div class="grid two">${inputField("Max output tokens", "max_output", c.max_output, "number", "", 'min="128" max="12000"')}${inputField("Context budget (characters)", "context_chars", c.context_chars, "number", "", 'min="8000" max="200000"')}</div></div>
 ${local ? inputField("Ollama runtime context (tokens)", "ollama_context_tokens", c.ollama_context_tokens || 16384, "number", "Must fit the installed model and your memory. Agentic RAG conservatively checks UTF-8 input bytes plus output and template reserves before generation; oversized requests are rejected instead of silently truncated.", 'min="2048" max="131072"') : ""}
 <details><summary>Cost rates (USD) · optional</summary><div class="note section-space mb">Enter applicable per-million-token rates, including zero only when confirmed. Unknown cloud prices remain unpriced. Local Ollama generation records zero API fees and excludes hardware.</div><div class="grid two">${inputField("Input / 1M tokens", "input_price", c.input_price ?? "", "number", "", 'min="0" step="any"')}${inputField("Output / 1M tokens", "output_price", c.output_price ?? "", "number", "", 'min="0" step="any"')}${inputField("Cached input / 1M tokens", "cached_price", c.cached_price ?? "", "number", "", 'min="0" step="any"')}${inputField("Embeddings / 1M tokens", "embedding_price", c.embedding_price ?? "", "number", "", 'min="0" step="any"')}${inputField("Flat estimate per generated image", "image_price", c.image_price ?? "", "number", "", 'min="0" step="any"')}</div></details>
 <button class="btn primary section-space" type="submit">${editConnection ? "Save changes" : "Save connection"} →</button></form></div></div>`
  );
}
function readConfig() {
  const form = $("#pipeline-form");
  if (!form) return config;
  const data = new FormData(form);
  for (const key of [
    "mode",
    "strategy",
    "embedding",
    "connection_id",
    "embedding_connection_id",
    "transcription",
    "whisper_model",
    "azure_profile_id",
    "azure_pages",
    "ollama_url",
  ])
    if (data.has(key)) config[key] = data.get(key) || "";
  config.extraction_backend =
    data.get("workflow") === "azure" ? "azure-document-intelligence" : "local";
  config.index_backend =
    data.get("workflow") === "azure" ? "azure-ai-search" : "local";
  const schemaRows = $$("[data-schema-field]", form);
  if (schemaRows.length) {
    config.index_fields = {};
    for (const el of schemaRows) {
      const k = el.dataset.schemaField;
      config.index_fields[k] ??= {};
      config.index_fields[k][el.dataset.schemaFlag] = el.checked;
    }
  }
  if (data.has("metadata_tags"))
    config.metadata_tags = String(data.get("metadata_tags"))
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  config.azure_features = data.getAll("azure_features");
  config.azure_semantic_rerank = data.has("azure_semantic_rerank");
  for (const key of ["chunk_size", "overlap", "max_calls"])
    config[key] = Number(data.get(key));
  config.budget_usd =
    data.get("budget_usd") === "" ? null : Number(data.get("budget_usd"));
  for (const key of [
    "strip_headers",
    "deduplicate",
    "mask_pii",
    "describe_visuals",
    "vision_layout",
    "ocr",
    "fetch_web_images",
  ])
    config[key] = data.has(key);
  localStorage.setItem("agentic-rag-pipeline", JSON.stringify(config));
  return config;
}
async function navigate(next) {
  if (page === "processing") readConfig();
  page = next;
  location.hash = next;
  if (page === "monitoring") monitor = await api("/api/monitor");
  if (page === "processing" && docId) {
    await loadDetail();
    await syncPipelineJobs();
  }
  render();
  window.scrollTo(0, 0);
}
async function uploadFiles(files) {
  for (const file of files) {
    const data = new FormData();
    data.append("file", file);
    toast("Importing " + file.name + "…");
    const d = await api("/api/documents/upload", {
      method: "POST",
      body: data,
    });
    docId = d.id;
  }
  await refresh();
  render();
  toast(
    files.length + " source" + (files.length > 1 ? "s" : "") + " imported.",
  );
}
async function syncPipelineJobs(scope = docId) {
  if (!scope || pipelineSyncing) return [];
  pipelineSyncing = true;
  try {
    let fresh;
    if (jobListAvailable) {
      try {
        fresh = (await api("/api/jobs?scope=" + encodeURIComponent(scope)))
          .jobs;
      } catch (error) {
        if (error.status !== 404 && error.status !== 405) throw error;
        jobListAvailable = false;
      }
    }
    if (!fresh)
      fresh = (await api("/api/state")).jobs.filter(
        (job) => job.scope === scope,
      );
    state.jobs = [
      ...fresh,
      ...(state.jobs || []).filter((job) => job.scope !== scope),
    ];
    for (const job of fresh) {
      if (
        !Object.values(pipelineStages).some((stage) => stage.kind === job.kind)
      )
        continue;
      const key = job.scope + ":" + job.kind,
        previous = pipelineRuns.get(key);
      const running = ["queued", "running"].includes(job.status);
      if (!previous || job.created >= previous.created || running)
        pipelineRuns.set(key, job);
      if (running && !jobs.has(job.id)) {
        jobs.set(job.id, job);
        pollJob(job.id);
      }
    }
    const changed =
      scope === docId &&
      fresh.some(
        (job) =>
          job.status === "completed" &&
          ((job.result?.extraction_id &&
            job.result.extraction_id !== detail?.extraction?.id) ||
            (job.result?.index_id &&
              job.result.index_id !== detail?.active_index) ||
            (job.result?.preview_id &&
              job.result.preview_id !== detail?.chunk_preview?.id)),
      );
    if (changed) {
      readConfig();
      await refresh();
      render();
    }
    updatePipelineStatus();
    return fresh;
  } finally {
    pipelineSyncing = false;
  }
}
async function startJob(url, body, kind) {
  const scope = url.match(
    /^\/api\/documents\/([^/]+)\/(extract|chunks|index)$/,
  )?.[1];
  const key = scope ? scope + ":" + kind : "";
  const submitted = {
    id: "pending-" + kind,
    kind,
    scope,
    status: "submitting",
    created: Date.now() / 1000,
  };
  if (scope) {
    if (
      [...jobs.values()].some((j) => j.scope === scope) ||
      (scope === docId && pipelineBusy())
    )
      return;
    pipelineRuns.set(key, submitted);
    updatePipelineStatus();
  }
  let r;
  try {
    if (scope) {
      const existing = await syncPipelineJobs(scope);
      if (existing.some((job) => ["queued", "running"].includes(job.status))) {
        if (pipelineRuns.get(key)?.id.startsWith("pending-"))
          pipelineRuns.delete(key);
        updatePipelineStatus();
        return;
      }
    }
    r = await post(url, body);
  } catch (error) {
    if (scope) {
      if (pipelineRuns.get(key)?.id.startsWith("pending-"))
        pipelineRuns.delete(key);
      let existing = [];
      try {
        existing = await syncPipelineJobs(scope);
      } catch {}
      if (existing.some((job) => ["queued", "running"].includes(job.status))) {
        updatePipelineStatus();
        return;
      }
      pipelineRuns.set(key, {
        ...submitted,
        status: "failed",
        error: error.message,
      });
      updatePipelineStatus();
    }
    throw error;
  }
  const job = { ...submitted, id: r.job_id, status: "queued" };
  jobs.set(r.job_id, job);
  if (scope) {
    pipelineRuns.set(key, job);
    updatePipelineStatus();
  } else render();
  pollJob(r.job_id);
}
async function pollJob(id) {
  if (!jobs.has(id)) return;
  try {
    const j = await api("/api/jobs/" + id);
    jobs.set(id, { ...jobs.get(id), ...j });
    if (Object.values(pipelineStages).some((stage) => stage.kind === j.kind)) {
      pipelineRuns.set(j.scope + ":" + j.kind, j);
      updatePipelineStatus();
    }
    const node = $(`[data-job-message="${id}"]`);
    if (node) node.textContent = " · " + (j.events.at(-1)?.message || j.status);
    if (["completed", "failed", "cancelled"].includes(j.status)) {
      const item = jobs.get(id);
      jobs.delete(id);
      if (j.status === "completed") {
        if (item.kind === "chat") {
          chatResult = j.result;
          sessionId = j.result.session_id || sessionId;
          messages.push({ role: "assistant", content: j.result.answer });
          pending = j.result.status === "clarification" ? j.result : null;
        }
        if (item.kind === "evaluation") {
          evalId = j.result.evaluation_id;
          evaluation = await api("/api/evaluations/" + evalId);
        }
        await refresh();
        if (page === "monitoring") monitor = await api("/api/monitor");
        render();
        if (page === "research")
          $("#chat-area")?.scrollTo({
            top: $("#chat-area").scrollHeight,
            behavior: "smooth",
          });
        toast(
          item.kind === "chat"
            ? pending
              ? "A clarification is ready."
              : "Answer ready with source references."
            : item.kind + " completed.",
        );
      } else {
        if (item.kind === "chat")
          messages.push({
            role: "assistant",
            content: j.error || "The run was cancelled.",
          });
        await refresh();
        render();
        toast(j.error || "Cancelled.", true);
      }
    } else setTimeout(() => pollJob(id), 1500);
  } catch (e) {
    const job = jobs.get(id);
    if (
      job?.scope &&
      Object.values(pipelineStages).some((stage) => stage.kind === job.kind)
    ) {
      job.poll_error =
        "Waiting to reconnect for a status update. The background job may still be running.";
      pipelineRuns.set(job.scope + ":" + job.kind, job);
      updatePipelineStatus();
    } else toast(e.message, true);
    setTimeout(() => pollJob(id), 4000);
  }
}
function modal(html) {
  const dialog = $("#modal");
  dialog.innerHTML = `<div class="actions mb"><button class="btn small" data-action="close-modal">✕ Close</button></div>${html}`;
  if (!dialog.open) dialog.showModal();
}
async function openBrowse(path = "") {
  browseState = await api("/api/browse?path=" + encodeURIComponent(path));
  modal(
    `<div class="card-header"><div><h2>Browse this computer</h2><p>Choose a file or a source folder. Imports are copied to local storage.</p></div></div><div class="browser-path">${esc(browseState.path || "Desktop · Documents · Downloads")}</div><div class="actions mb">${browseState.path ? `<button class="btn small" data-action="browse" data-path="${esc(browseState.parent || "")}">↑ Parent folder</button><button class="btn primary small" data-action="import-path" data-path="${esc(browseState.path)}">Import this folder</button>` : ""}</div><div class="scroll">${browseState.entries.map((e) => `<div class="browser-entry"><span>${e.directory ? "▧" : "▤"} ${esc(e.name)}</span><button class="btn small" data-action="${e.directory ? "browse" : "import-path"}" data-path="${esc(e.path)}">${e.directory ? "Open →" : "Import"}</button></div>`).join("")}</div><p class="footer-note">Hidden files, secrets, runtime environments and build folders are excluded. Code is read as text.</p>`,
  );
}
async function showTrace(id) {
  const t = await api("/api/monitor/" + id);
  modal(
    `<h2>Run trace</h2><div class="doc-meta mono">${esc(id)}</div>${t.job?.error ? '<div class="note error section-space">' + esc(t.job.error) + "</div>" : ""}<div class="section-space">${t.events
      .sort((a, b) => a.time - b.time)
      .map(
        (e) =>
          `<div class="event"><strong>${esc(e.stage)} · ${esc(e.message)}</strong><small>${date(e.time)}</small>${Object.keys(e.details || {}).length ? "<details><summary>Details</summary><div><pre>" + json(e.details) + "</pre></div></details>" : ""}</div>`,
      )
      .join(
        "",
      )}</div><h3 class="mb">Azure service activity</h3>${(t.cloud_calls || []).map((c) => `<details class="source-card"><summary>${esc(c.service)} · ${esc(c.operation)} · ${badge(c.status, c.status === "failed" ? "red" : "")} · ${price(c.cost_usd)}</summary><div><pre>${json(c)}</pre></div></details>`).join("") || '<p class="small muted mb">No Azure service calls in this run.</p>'}<h3 class="mb section-space">Model activity</h3>${t.calls.map((c) => `<details class="source-card"><summary>${esc(c.provider)} · ${esc(c.operation)} · ${esc(c.model)} · ${badge(c.status, c.status === "failed" ? "red" : "")} · ${price(c.cost_usd)}</summary><div><pre>${json(c)}</pre></div></details>`).join("") || '<p class="small muted">No provider calls in this run.</p>'}`,
  );
}
async function sendChat(form, defaultScope = false) {
  const data = new FormData(form);
  const message = defaultScope
    ? "Use the whole document."
    : String(data.get("message") || "").trim();
  if (!message) {
    toast("Enter a question or clarification.", true);
    return;
  }
  if ([...jobs.values()].some((j) => j.kind === "chat")) {
    toast("Wait for the current answer, or cancel it first.");
    return;
  }
  readResearchOptions(form);
  const payload = {
    document_id: docId,
    connection_id: data.get("connection_id") || "",
    session_id: sessionId,
    message: pending ? pending.original_question : message,
    clarified: !!pending,
    clarification_answer: pending ? message : "",
    clarify_policy: "always",
    max_passes: Number(data.get("max_passes")),
    max_calls: { low: 5, medium: 12, high: 30 }[chatOptions.effort],
    preview: data.has("preview"),
    generate_image: data.has("generate_image"),
    filters: chatOptions.filters,
    search_mode: chatOptions.search_mode,
    keyword_query: chatOptions.keyword_query,
    use_agent_filters: chatOptions.use_agent_filters,
    effort: chatOptions.effort,
    context_chars: chatOptions.context_chars,
  };
  chatOptions = {
    ...chatOptions,
    connection_id: payload.connection_id,
    max_passes: payload.max_passes,
    preview: payload.preview,
    generate_image: payload.generate_image,
  };
  messages.push({ role: "user", content: message });
  await startJob("/api/chat", payload, "chat");
}
async function handleAction(button) {
  const a = button.dataset.action,
    id = button.dataset.id;
  if (a.startsWith("azure-")) return azureAction(a, id, button);
  if (a === "nav") return navigate(button.dataset.page);
  if (a === "close-modal") return $("#modal").close();
  if (a === "refresh") {
    await refresh();
    render();
    return;
  }
  if (a === "use-doc") {
    docId = id;
    messages = [];
    chatResult = null;
    pending = null;
    sessionId = "";
    await loadDetail();
    return navigate("processing");
  }
  if (a === "browse") return openBrowse(button.dataset.path || "");
  if (a === "import-path") {
    button.disabled = true;
    const d = await post("/api/documents/import", {
      path: button.dataset.path,
    });
    docId = d.id;
    $("#modal").close();
    await refresh();
    render();
    toast("Source imported.");
    return;
  }
  if (a === "pipeline") {
    if (pipelineBusy()) return;
    const c = readConfig();
    if (!c.mode) throw Error("Choose a retrieval mode before processing.");
    if (c.overlap >= c.chunk_size)
      throw Error("Overlap must be smaller than chunk size.");
    const stage = button.dataset.stage;
    if (
      c.mode === "multimodal" &&
      !["local-clip", "gemini-multimodal", "azure-vision"].includes(c.embedding)
    )
      throw Error("Choose a multimodal embedding engine.");
    if (c.index_backend === "azure-ai-search" && stage !== "chunks") {
      if (!c.azure_profile_id)
        throw Error("Choose an Azure workspace connection.");
      cloudPlan = await post("/api/azure/plan", {
        document_id: docId,
        stage,
        config: { ...c, azure_plan_id: "" },
      });
      showCloudPlan(cloudPlan);
      return;
    }
    return startJob(
      "/api/documents/" + docId + "/" + stage,
      c,
      stage === "extract"
        ? "extraction"
        : stage === "chunks"
          ? "chunking"
          : "indexing",
    );
  }
  if (a === "cancel") {
    await post("/api/jobs/" + id + "/cancel");
    toast(
      "Cancellation requested. An in-flight provider request will finish first.",
    );
    return;
  }
  if (a === "search-chunks") {
    chunkSearch = $("#chunk-search").value;
    chunkPage = 0;
    render();
    return;
  }
  if (a === "chunk-page") {
    chunkPage = Number(button.dataset.page);
    render();
    return;
  }
  if (a === "inspect-tab") {
    if (button.dataset.tab === "chunks") await loadChunkInspection();
    readConfig();
    inspectTab = button.dataset.tab;
    render();
    return;
  }
  if (a === "search-elements") {
    readConfig();
    elementSearch = $("#element-search").value;
    render();
    return;
  }
  if (a === "reset-index-fields") {
    readConfig();
    config.index_fields = {};
    render();
    return;
  }
  if (a === "new-chat") {
    chatOptions.filters = {};
    sessionId = "";
    pending = null;
    messages = [];
    chatResult = null;
    render();
    return;
  }
  if (a === "suggest") {
    $("#chat-message").value = button.dataset.text;
    $("#chat-message").focus();
    return;
  }
  if (a === "clarify-default") return sendChat($("#chat-form"), true);
  if (a === "show-memory") {
    memories = await api("/api/memory?document_id=" + docId);
    modal(
      `<h2>Document memory</h2><p class="small muted section-space">Scope and preferences stay tied to this source. Delete any item below.</p><div class="list section-space">${memories.map((m) => `<div class="memory-item"><div><div class="actions mb">${badge(m.type)}</div><p>${esc(m.text)}</p></div><button class="btn small danger" data-action="delete-memory" data-id="${m.id}">Forget</button></div>`).join("") || '<p class="small muted">No long-term memory yet.</p>'}</div><form id="memory-form" class="section-space"><div class="field"><label for="memory-text">Remember a preference</label><textarea id="memory-text" name="text" placeholder="For this source, use concise explanations and include page references." required maxlength="3000"></textarea></div><button class="btn primary" type="submit">Save preference</button></form>`,
    );
    return;
  }
  if (a === "delete-memory") {
    await api("/api/memory/" + id, { method: "DELETE" });
    toast("Memory removed.");
    $("#modal").close();
    return;
  }
  if (a === "show-sessions") {
    const ss = await api("/api/sessions?document_id=" + docId);
    modal(
      `<h2>Previous chats</h2><div class="list section-space">${
        ss
          .filter((x) => x.messages.length || x.pending_question)
          .map(
            (x) =>
              `<div class="doc-row"><div class="grow"><div class="doc-name">${esc(x.messages.find((m) => m.role === "user")?.content.slice(0, 100) || "Conversation")}</div><div class="doc-meta">${date(x.created)} · Index ${short(x.index_id)}</div></div><button class="btn small" data-action="open-session" data-id="${x.id}">Open</button><button class="btn small danger" data-action="delete-session" data-id="${x.id}">Delete</button></div>`,
          )
          .join("") ||
        empty(
          "No previous conversations.",
          "Your completed research chats will appear here.",
        )
      }</div>`,
    );
    return;
  }
  if (a === "open-session") {
    const x = await api("/api/sessions/" + id);
    if (x.index_id !== chosen().active_index)
      throw Error(
        "This chat used an earlier index. Its history is preserved; start a new chat to use the current index.",
      );
    sessionId = id;
    chatOptions = {
      ...chatOptions,
      ...(x.pending_retrieval || x.latest_answer?.retrieval || {}),
    };
    messages = x.messages.map((m) => ({ role: m.role, content: m.content }));
    pending = x.pending_question
      ? { original_question: x.pending_question }
      : null;
    chatResult = x.latest_answer || null;
    $("#modal").close();
    render();
    return;
  }
  if (a === "delete-session") {
    await api("/api/sessions/" + id, { method: "DELETE" });
    if (sessionId === id) {
      sessionId = "";
      messages = [];
      pending = null;
    }
    $("#modal").close();
    render();
    toast(
      "Conversation context removed. Historical monitoring traces remain available.",
    );
    return;
  }
  if (a === "refresh-monitor") {
    monitor = await api("/api/monitor");
    render();
    return;
  }
  if (a === "trace") return showTrace(id);
  if (a === "focus-source") {
    const target = $('[data-source-id="' + id + '"]');
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      target.classList.add("highlight");
      setTimeout(() => target.classList.remove("highlight"), 1800);
    }
    return;
  }
  if (a === "review") {
    const r = await api("/api/reviews/" + id);
    modal(
      `<h2>Human review</h2><p class="small muted section-space">Rate answer quality independently of automated metrics.</p><form id="review-form" data-id="${id}" class="section-space">${selectField(
        "Rating",
        "score",
        [
          [1, "1 · Poor"],
          [2, "2 · Needs work"],
          [3, "3 · Useful with corrections"],
          [4, "4 · Good"],
          [5, "5 · Excellent"],
        ],
        r?.score || 3,
      )}<div class="field"><label for="review-note">Review notes</label><textarea id="review-note" name="note" maxlength="3000">${esc(r?.note || "")}</textarea></div><button class="btn primary" type="submit">Save review</button></form>`,
    );
    return;
  }
  if (a === "view-dataset") {
    const ds = await api("/api/datasets/" + id);
    modal(
      `<h2>${esc(ds.name)}</h2><div class="doc-meta">${ds.cases.length} cases · Immutable snapshot ${short(ds.hash)}</div><div class="note section-space">To improve ground truth, export this dataset, edit it and import a new version. Historical runs keep their original references.</div><pre>${json(ds.cases)}</pre><button class="btn" data-action="export-dataset" data-id="${id}">Download JSON ↓</button>`,
    );
    return;
  }
  if (a === "export-dataset") {
    const ds = await api("/api/datasets/" + id);
    download(ds.name.replace(/\.[^.]*$/, "") + ".json", { cases: ds.cases });
    return;
  }
  if (a === "export-eval") {
    download(
      "agentic-rag-evaluation-" + short(id) + ".json",
      await api("/api/evaluations/" + id),
    );
    return;
  }
  if (a === "new-connection") {
    copyFromConnection = "";
    editConnection = "";
    connectionDraft = null;
    modelInventory = null;
    render();
    return;
  }
  if (a === "edit-connection") {
    copyFromConnection = "";
    editConnection = id;
    connectionDraft = null;
    modelInventory = null;
    render();
    return;
  }
  if (a === "activate-connection") {
    state.settings = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify({
        active_connection: id,
        guidance: state.settings.guidance,
        memory_enabled: state.settings.memory_enabled,
      }),
    });
    config.connection_id = id;
    render();
    toast("Active chat connection updated.");
    return;
  }
  if (a === "test-connection") {
    button.disabled = true;
    button.textContent = "Testing…";
    try {
      const t = await post("/api/connections/" + id + "/test");
      await refresh();
      render();
      toast(
        t.vision_verified
          ? "Text and image input verified."
          : "Text connection ready. Vision is disabled or unverified.",
      );
    } finally {
      button.disabled = false;
    }
    return;
  }
  if (a === "copy-connection") {
    const c = state.connections.find((x) => x.id === id);
    editConnection = "";
    copyFromConnection = id;
    modelInventory = null;
    connectionDraft = {
      ...c,
      name: (c.name + " · another model").slice(0, 80),
      api_key: "",
    };
    render();
    toast(
      "Choose another model. The saved key will be reused securely for this provider.",
    );
    return;
  }
  if (a === "models") {
    button.disabled = true;
    try {
      modelInventory = await api("/api/connections/" + id + "/models");
      copyFromConnection = "";
      editConnection = id;
      connectionDraft = null;
      render();
      $("#model-choice").scrollIntoView({
        block: "center",
        behavior: "smooth",
      });
      toast("Model list loaded. Choose a model and save this profile.");
    } finally {
      button.disabled = false;
    }
    return;
  }
  if (a === "discover-models") {
    const form = $("#connection-form"),
      body = connectionBody(form);
    button.disabled = true;
    button.textContent = "Loading models…";
    try {
      const result = await post(
        "/api/model-options" +
          (editConnection || copyFromConnection
            ? "?connection_id=" +
              encodeURIComponent(editConnection || copyFromConnection)
            : ""),
        body,
      );
      if (form !== $("#connection-form")) return;
      modelInventory = result;
      const picker = $("#model-choice");
      picker.innerHTML =
        '<option value="">Enter a model ID below</option>' +
        result.models
          .filter((x) => x.selectable !== false)
          .map(
            (x) =>
              `<option value="${esc(x.id)}" ${x.id === body.model ? "selected" : ""}>${esc(x.id)}</option>`,
          )
          .join("");
      picker.previousElementSibling.textContent =
        body.provider === "ollama"
          ? "Installed chat models"
          : "Models from your provider";
      picker.nextElementSibling.textContent =
        result.notice +
        (result.partial
          ? " The inventory was limited; you can still enter an exact model ID."
          : "");
      toast(
        result.models.filter((x) => x.selectable !== false).length +
          " model choices loaded.",
      );
    } finally {
      button.disabled = false;
      button.textContent =
        body.provider === "ollama"
          ? "Find installed models"
          : "Load my model list";
    }
    return;
  }
}
function download(name, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
      type: "application/json",
    }),
    url = URL.createObjectURL(blob),
    a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-action]");
  if (!b) return;
  e.preventDefault();
  try {
    await handleAction(b);
  } catch (error) {
    b.disabled = false;
    toast(error.message, true);
  }
});
document.addEventListener("change", async (e) => {
  try {
    if (
      e.target.name === "auth_mode" &&
      e.target.closest("#azure-profile-form")
    ) {
      azureDraft = Object.fromEntries(new FormData($("#azure-profile-form")));
      for (const key of ["publish_assets"])
        azureDraft[key] = $(`[name="${key}"]`, e.target.form).checked;
      render();
      return;
    }
    if (
      ["auth_mode", "account_tier"].includes(e.target.name) &&
      e.target.closest("#connection-form")
    ) {
      connectionDraft = connectionBody($("#connection-form"));
      render();
      return;
    }
    if (e.target.id === "model-choice") {
      if (e.target.value) {
        $("#model").value = e.target.value;
        $("input[name=vision]", $("#connection-form")).checked = !!providerInfo(
          $("#provider").value,
        ).defaults.vision;
        toast(
          "Model selected. Save and test this model to verify access and image input.",
        );
      }
      return;
    }
    if (e.target.id === "file-upload") {
      await uploadFiles([...e.target.files]);
      return;
    }
    if (e.target.dataset.change === "inspection-snapshot") {
      inspectSnapshotId = e.target.value;
      chunkPage = 0;
      await loadChunkInspection();
      render();
      return;
    }
    if (e.target.dataset.change === "chunk-kind") {
      chunkKind = e.target.value;
      chunkPage = 0;
      render();
      return;
    }
    if (e.target.dataset.change === "document") {
      inspectSnapshotId = "";
      chunkSearch = "";
      chunkKind = "";
      chunkInspection = null;
      if (page === "processing") readConfig();
      docId = e.target.value;
      messages = [];
      pending = null;
      chatResult = null;
      sessionId = "";
      evaluation = null;
      evalId = "";
      await loadDetail();
      render();
      return;
    }
    if (e.target.closest("#chat-form")) {
      readResearchOptions($("#chat-form"));
      if (e.target.name === "effort") {
        $('[name="max_passes"]', e.target.form).value = String(
          { low: 1, medium: 2, high: 4 }[e.target.value],
        );
        chatOptions.max_passes = Number(
          $('[name="max_passes"]', e.target.form).value,
        );
      }
      return;
    }
    if (
      e.target.name === "capacity_profile" &&
      e.target.closest("#connection-form")
    ) {
      connectionDraft = connectionBody($("#connection-form"));
      if (e.target.value === "small")
        Object.assign(connectionDraft, {
          context_chars: 12000,
          max_output: 1500,
        });
      if (e.target.value === "large")
        Object.assign(connectionDraft, {
          context_chars: 120000,
          max_output: 6000,
        });
      render();
      return;
    }
    if (e.target.closest("#pipeline-form")) {
      readConfig();
      if (
        e.target.name === "embedding" &&
        config.embedding.startsWith("ollama-")
      ) {
        Object.assign(
          config,
          config.embedding === "ollama-small"
            ? { chunk_size: 1000, overlap: 200 }
            : { chunk_size: 3000, overlap: 500 },
        );
        localStorage.setItem("agentic-rag-pipeline", JSON.stringify(config));
        render();
        return;
      }
      if (
        ["mode", "workflow", "azure_profile_id", "embedding"].includes(
          e.target.name,
        )
      ) {
        if (e.target.name === "azure_profile_id") {
          const p = state.azure_profiles.find(
            (x) => x.id === config.azure_profile_id,
          );
          if (p?.openai_connection_id) {
            config.connection_id = p.openai_connection_id;
            config.embedding_connection_id = p.openai_connection_id;
          }
        }
        if (
          config.mode === "multimodal" &&
          !["local-clip", "gemini-multimodal", "azure-vision"].includes(
            config.embedding,
          )
        )
          config.embedding = "local-clip";
        if (
          config.mode === "description" &&
          ![
            "local-text",
            "provider-text",
            "ollama-small",
            "ollama-large",
          ].includes(config.embedding)
        )
          config.embedding = "local-text";
        localStorage.setItem("agentic-rag-pipeline", JSON.stringify(config));
        render();
      }
      return;
    }
    if (e.target.dataset.change === "kind") {
      readConfig();
      elementKind = e.target.value;
      render();
      return;
    }
    if (e.target.dataset.change === "evaluation") {
      evalId = e.target.value;
      evaluation = evalId ? await api("/api/evaluations/" + evalId) : null;
      render();
      return;
    }
    if (e.target.name === "provider" && e.target.closest("#connection-form")) {
      const provider = e.target.value;
      copyFromConnection = "";
      connectionDraft = connectionDefaults(provider);
      modelInventory = null;
      render();
      return;
    }
  } catch (error) {
    toast(error.message, true);
  }
});
document.addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const button = $("[type=submit]", form);
  if (button) button.disabled = true;
  try {
    const data = new FormData(form),
      obj = Object.fromEntries(data);
    if (form.id === "azure-profile-form") {
      await saveAzureForm(obj, data);
      return;
    }
    if (form.id === "azure-signin-form") {
      await signInAzure(obj);
      return;
    }
    if (form.id === "url-form") {
      const d = await post("/api/documents/url", obj);
      docId = d.id;
      await refresh();
      render();
      toast("Webpage snapshot imported.");
    }
    if (form.id === "connection-form") {
      Object.assign(obj, connectionBody(form));
      await api(
        "/api/connections" +
          (editConnection
            ? "/" + editConnection
            : copyFromConnection
              ? "?copy_from=" + encodeURIComponent(copyFromConnection)
              : ""),
        { method: editConnection ? "PUT" : "POST", body: JSON.stringify(obj) },
      );
      editConnection = "";
      copyFromConnection = "";
      connectionDraft = null;
      modelInventory = null;
      await refresh();
      render();
      toast(
        "Connection saved. Test it to verify model access and image input.",
      );
    }
    if (form.id === "settings-form") {
      state.settings = await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          active_connection: state.settings.active_connection,
          guidance: obj.guidance,
          memory_enabled: data.has("memory_enabled"),
        }),
      });
      render();
      toast("Workspace settings saved.");
    }
    if (form.id === "chat-form") await sendChat(form);
    if (form.id === "memory-form") {
      await post("/api/memory", { document_id: docId, text: obj.text });
      $("#modal").close();
      toast("Preference saved.");
    }
    if (form.id === "review-form") {
      await post("/api/reviews/" + form.dataset.id, {
        score: Number(obj.score),
        note: obj.note,
      });
      $("#modal").close();
      if (evalId) {
        evaluation = await api("/api/evaluations/" + evalId);
        render();
      }
      toast("Human review saved.");
    }
    if (form.id === "dataset-form") {
      const upload = new FormData();
      upload.append("file", $("#dataset-file").files[0]);
      upload.append("document_id", docId);
      upload.append("index_id", chosen().active_index);
      await api("/api/datasets", { method: "POST", body: upload });
      await refresh();
      render();
      toast("Benchmark snapshot imported.");
    }
    if (form.id === "evaluation-form") {
      const ids = data.getAll("connection_ids");
      if (!ids.length) throw Error("Choose at least one model.");
      await startJob(
        "/api/evaluations",
        {
          dataset_id: obj.dataset_id,
          connection_ids: ids,
          judge_id: obj.judge_id || "",
          max_calls: Number(obj.max_calls),
          max_passes: Number(obj.max_passes),
        },
        "evaluation",
      );
    }
  } catch (error) {
    toast(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
});
document.addEventListener("dragover", (e) => {
  if (e.target.closest("#dropzone")) {
    e.preventDefault();
    $("#dropzone").classList.add("drag");
  }
});
document.addEventListener("dragleave", (e) => {
  if (e.target.closest("#dropzone")) $("#dropzone").classList.remove("drag");
});
document.addEventListener("drop", async (e) => {
  if (e.target.closest("#dropzone")) {
    e.preventDefault();
    try {
      await uploadFiles([...e.dataTransfer.files]);
    } catch (error) {
      toast(error.message, true);
    }
  }
});
window.addEventListener("hashchange", () => {
  const next = location.hash.slice(1);
  if (next !== page) navigate(names[next] ? next : "library");
});
(async () => {
  try {
    await refresh();
    if (page === "monitoring") monitor = await api("/api/monitor");
    for (const j of state.jobs.filter((j) =>
      ["queued", "running"].includes(j.status),
    )) {
      jobs.set(j.id, j);
      pollJob(j.id);
    }
    if (page === "processing") await syncPipelineJobs();
    render();
  } catch (e) {
    $("#app").innerHTML =
      '<div class="boot">AGENTIC_RAG<small>' +
      esc(e.message) +
      "</small></div>";
  }
})();
setInterval(async () => {
  if (page === "processing" && docId) {
    try {
      await syncPipelineJobs();
    } catch {
      for (const job of jobs.values()) {
        if (job.scope === docId)
          job.poll_error =
            "Waiting to reconnect for a status update. The background job may still be running.";
      }
      updatePipelineStatus();
    }
  }
}, 3000);
window.addEventListener("focus", () => {
  if (page === "processing") syncPipelineJobs().catch(() => {});
});
setInterval(async () => {
  if (page === "monitoring" && !$("#modal").open && jobs.size === 0) {
    try {
      monitor = await api("/api/monitor");
      const open = $$("details[open]").length;
      if (!open) render();
    } catch {}
  }
}, 5000);

function azureModelAuthFields(c) {
  return (
    selectField(
      "Azure authentication",
      "auth_mode",
      [
        ["api-key", "Resource API key"],
        ["entra", "Microsoft sign-in from Agentic RAG"],
        ["azure-cli", "Existing Azure CLI session"],
      ],
      c.auth_mode || "api-key",
    ) +
    inputField(
      "Tenant ID or domain",
      "tenant_id",
      c.tenant_id || "organizations",
    ) +
    inputField(
      "Public-client application ID (optional)",
      "client_id",
      c.client_id || "",
      "text",
      "Use the same tenant and app ID as your sign-in in Azure workspace. Your organization may require its own registered app.",
    )
  );
}
function azurePipelineControls() {
  const cloud = config.extraction_backend === "azure-document-intelligence";
  return `<div class="card mb"><div class="card-header"><div><h3>Choose where this pipeline runs</h3><p>Keep processing local or connect your existing Azure services.</p></div>${badge(cloud ? "AZURE CLOUD" : "LOCAL WORKSPACE", cloud ? "green" : "")}</div>${selectField(
    "Processing workflow",
    "workflow",
    [
      ["local", "Local extraction & vector storage"],
      ["azure", "Azure Layout → chunking → Azure AI Search"],
    ],
    cloud ? "azure" : "local",
  )}${cloud ? `<div class="field"><label for="azure_profile_id">Azure workspace connection</label><select id="azure_profile_id" name="azure_profile_id"><option value="">Choose an Azure connection</option>${(state.azure_profiles || []).map((p) => `<option value="${p.id}" ${p.id === config.azure_profile_id ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select><small>Add endpoints and sign in from Azure workspace.</small></div><div class="note mb"><b>Azure Document Intelligence · prebuilt-layout</b> detects entities. Azure AI Search stores the reviewed chunks and vectors. Each publication creates a separate index inside your existing service.</div><div class="grid two">${inputField("Pages to extract (optional)", "azure_pages", config.azure_pages || "", "text", "Example: 1-5,8. Blank requests the full supported document.")}<div class="field"><label>Optional Layout features</label>${["ocrHighResolution", "formulas", "styleFont", "barcodes", "languages", "keyValuePairs"].map((f) => `<label class="check"><input name="azure_features" type="checkbox" value="${f}" ${(config.azure_features || []).includes(f) ? "checked" : ""}>${esc({ ocrHighResolution: "High-resolution OCR", formulas: "Mathematical formulas", styleFont: "Font and style details", barcodes: "Barcodes", languages: "Language detection", keyValuePairs: "Key-value pairs" }[f])}</label>`).join("")}</div></div>${check("Use Azure semantic reranking (requires service support; may add charges)", "azure_semantic_rerank", config.azure_semantic_rerank)}<div class="note warn section-space">Supported: PDF, images, DOCX, XLSX, PPTX and HTML. Embedded Office visuals and some spreadsheet structure are limited; export to PDF for visual extraction. F0 returns at most two pages. Files are sent only when you start extraction or indexing.</div><div class="actions section-space"><button type="button" class="btn small" data-action="nav" data-page="azure">Manage Azure connections →</button></div>` : ""}</div>`;
}
function azureWorkspace() {
  const ps = state.azure_profiles || [],
    c = azureDraft ||
      ps.find((p) => p.id === editAzure) || {
        name: "",
        auth_mode: "api-key",
        tenant_id: "organizations",
        client_id: "",
        document_tier: "unknown",
        index_prefix: "agentic-rag",
        blob_container: "agentic-rag-sources",
        timeout_seconds: 900,
      },
    keyMode = c.auth_mode === "api-key";
  return (
    header(
      "Your Azure. One workspace.",
      "Connect existing services, review the extraction, then publish searchable evidence.",
    ) +
    `<div class="flow mb">${["Connect services", "Extract with Layout", "Review & chunk", "Publish to Search"].map((x, i) => `<div class="flow-step"><span class="step-number">${i + 1}</span>${x}</div>`).join("")}</div><div class="note mb">Agentic RAG connects to resources you already own. It creates new Search indexes inside your existing service. Resource setup, access roles and billing stay with your Azure account. Your app, memory and traces run on this desktop.</div><div class="grid two mb"><div class="card"><div class="card-header"><div><h3>Microsoft sign-in</h3><p>For Microsoft Entra authentication. Service keys can be used independently.</p></div>${badge("ACCOUNT ACCESS")}</div><form id="azure-signin-form">${inputField("Tenant ID or domain", "signin_tenant_id", c.tenant_id || "organizations", "text", "Use your organization tenant for work accounts.")}${inputField("Public-client application ID (optional)", "signin_client_id", c.client_id || "", "text", "Your tenant may require an approved app with device-code flow. Blank uses Microsoft’s developer client.")}<button class="btn primary" type="submit">Sign in with Microsoft →</button></form><div id="azure-signin-status" class="section-space">${signInView()}</div><div class="divider"></div>${(state.azure_accounts || []).map((a) => `<div class="doc-row"><div class="grow"><b>${esc(a.username)}</b><div class="doc-meta">Tenant ${esc(a.tenant_id)} · ${date(a.signed_in)}</div></div>${badge("signed in", "green")}</div>`).join("")}<p class="footer-note">Tokens use the operating system’s encrypted credential cache. The Azure CLI option uses an existing signed-in CLI session. Microsoft sign-in starts here and completes on Microsoft’s page.</p></div><div class="card"><div class="card-header"><div><h3>Connected Azure workspaces</h3><p>Each profile ties together your extraction, search and optional storage services.</p></div><button class="btn small" data-action="azure-new">＋ Add</button></div>${ps.map((p) => `<div class="provider-card"><div class="card-header"><div><h3>${esc(p.name)}</h3><p>${esc(p.auth_mode)} · prebuilt-layout</p></div>${badge(p.last_check?.results?.document?.ready && p.last_check?.results?.search?.ready ? "resource reads verified" : "not verified", p.last_check?.results?.document?.ready && p.last_check?.results?.search?.ready ? "green" : "amber")}</div><p class="small break">${esc(p.document_endpoint)}<br>${esc(p.search_endpoint)}</p><div class="actions section-space"><button class="btn small" data-action="azure-edit" data-id="${p.id}">Edit</button><button class="btn small" data-action="azure-test" data-id="${p.id}">Check access</button><button class="btn primary small" data-action="azure-use" data-id="${p.id}">Use in Processing →</button></div>${p.last_check ? `<details class="section-space"><summary>Last access check</summary><div><pre>${json(p.last_check.results)}</pre></div></details>` : ""}</div>`).join("") || empty("Connect your services.", "Enter existing endpoints below, then choose this workspace in Processing.")}<div class="note section-space">An access check reads service metadata. Upload and index-write permissions are verified during processing. Azure OpenAI is tested separately in Connections & settings.</div></div></div><div class="card mb"><div class="card-header"><div><h3>${editAzure ? "Edit Azure connection" : "Connect existing Azure resources"}</h3><p>Keys are write-only and encrypted in local storage. Leave a saved key blank to retain it.</p></div>${badge("EXISTING RESOURCES ONLY")}</div><form id="azure-profile-form"><div class="grid two">${inputField("Workspace name", "name", c.name, "text", "", 'required maxlength="80"')}${selectField(
      "Authentication method",
      "auth_mode",
      [
        ["api-key", "Service keys"],
        ["entra", "Microsoft sign-in"],
        ["azure-cli", "Existing Azure CLI session"],
      ],
      c.auth_mode,
    )}${inputField("Tenant ID or domain", "tenant_id", c.tenant_id || "organizations")}${inputField("Public-client application ID (optional)", "client_id", c.client_id || "")}</div><div class="grid two"><div><h3 class="mb">Document Intelligence</h3>${inputField("Document Intelligence endpoint", "document_endpoint", c.document_endpoint || "", "url", "https://your-resource.cognitiveservices.azure.com", "required")}${keyMode ? inputField("Document Intelligence key", "document_key", "", "password", c.has_document_key ? "Saved key will be retained." : "Resource key, not an Azure OpenAI key.", 'autocomplete="new-password"') : ""}${selectField(
      "Document Intelligence pricing tier",
      "document_tier",
      [
        ["unknown", "Unknown · inspect returned coverage"],
        ["F0", "F0 · free tier, first 2 pages only"],
        ["S0", "S0 · paid tier"],
      ],
      c.document_tier || "unknown",
    )}<div class="note">Extractor is fixed to <b>prebuilt-layout</b>. Raw JSON, reading order, paragraphs, tables, figures, roles and source geometry remain inspectable.</div></div><div><h3 class="mb">Azure AI Search</h3>${inputField("Search service endpoint", "search_endpoint", c.search_endpoint || "", "url", "https://your-search.search.windows.net", "required")}${keyMode ? inputField("Search admin key", "search_key", "", "password", c.has_search_key ? "Saved key will be retained." : "An admin key is needed to create an index.", 'autocomplete="new-password"') : ""}${inputField("New index name prefix", "index_prefix", c.index_prefix || "agentic-rag", "text", "Each build uses a new unique index name. Existing indexes are never overwritten.", 'required pattern="[a-z][a-z0-9-]{1,30}"')}<div class="field"><label for="openai_connection_id">Azure OpenAI answer / text embedding connection</label><select id="openai_connection_id" name="openai_connection_id">${options(
      state.connections.filter((x) => x.provider === "azure"),
      c.openai_connection_id || "",
      "Configure later in Connections & settings",
    )}</select><small>Enter your model and embedding deployment IDs in Connections & settings.</small></div><button class="btn small" type="button" data-action="nav" data-page="settings">Configure Azure OpenAI →</button></div></div><details class="section-space"><summary>Optional native visual embeddings & private source storage</summary><div class="grid two section-space"><div><h3 class="mb">Azure Vision</h3>${inputField("Azure Vision endpoint", "vision_endpoint", c.vision_endpoint || "", "url", "Required only for the Azure Vision embedding engine.")}${keyMode ? inputField("Azure Vision key", "vision_key", "", "password", "Image and text retrieval vectors share a pinned model version.", 'autocomplete="new-password"') : ""}<div class="note">Azure OpenAI text embeddings use visual descriptions. For pixel embeddings choose Azure Vision, local CLIP or Gemini multimodal explicitly in Processing.</div></div><div><h3 class="mb">Private Blob Storage</h3>${inputField("Storage account endpoint", "blob_endpoint", c.blob_endpoint || "", "url", "https://your-account.blob.core.windows.net")}${keyMode ? inputField("Storage account key", "blob_key", "", "password", "", 'autocomplete="new-password"') : ""}${inputField("Existing private container", "blob_container", c.blob_container || "agentic-rag-sources")}${check("Upload source originals, Layout JSON and visual references when publishing", "publish_assets", c.publish_assets)}<p class="footer-note">The container must already exist. Agentic RAG never enables public access or creates a storage account. With this off, visual references remain on this desktop.</p></div></div></details><details class="section-space"><summary>Cost estimates & service limits</summary><div class="note section-space mb">Enter your applicable all-in rates. Unpriced operations stay unknown. Search index creation and uploads use your existing service capacity; its hourly bill is separate. Semantic reranking and Blob operations may add charges.</div><div class="grid two">${inputField("Layout / 1,000 returned pages (USD)", "document_price_per_1000_pages", c.document_price_per_1000_pages ?? "", "number", "Include applicable selected feature rates. Billing page definitions may differ.", 'min="0" step="any"')}${inputField("Vision / 1,000 embedding requests (USD)", "vision_price_per_1000_requests", c.vision_price_per_1000_requests ?? "", "number", "", 'min="0" step="any"')}${inputField("Search / 1,000 queries, incl. reranking (USD)", "search_price_per_1000_queries", c.search_price_per_1000_queries ?? "", "number", "Query marginal estimate; excludes service capacity.", 'min="0" step="any"')}${inputField("Existing Search service / hour (USD)", "search_hourly_estimate", c.search_hourly_estimate ?? "", "number", "Reference rate only; Agentic RAG cannot allocate your shared service bill.", 'min="0" step="any"')}${inputField("Layout polling timeout (seconds)", "timeout_seconds", c.timeout_seconds || 900, "number", "", 'min="30" max="3600"')}</div></details><button class="btn primary section-space" type="submit">Save Azure connection →</button></form></div>${azurePublications()}`
  );
}
function azurePublications() {
  return `<div class="card"><div class="card-header"><div><h3>Cloud publications & analyses</h3><p>Versioned indexes, failed candidates and returned Layout JSON.</p></div></div>${(state.azure_publications || []).map((x) => `<details class="source-card"><summary>${esc(x.search_index)} ${badge(x.status, x.status === "failed" ? "red" : "green")}</summary><div><p>${esc(x.error || "Publication verified before activation.")}</p><p class="small">${esc(x.profile.search_endpoint)} · ${date(x.created)}<br>${esc(x.cleanup_note || "Cloud indexes remain until you remove them from your Azure service.")}</p><button class="btn small" data-action="trace" data-id="${x.run_id}">View trace</button></div></details>`).join("") || '<p class="muted small">No Search indexes published yet.</p>'}${(state.azure_analyses || []).map((x) => `<div class="doc-row"><div class="grow"><b>Layout analysis ${esc(short(x.id))}</b><div class="doc-meta">${esc(x.status)} · ${date(x.created)}</div></div>${x.raw_json_asset ? `<a class="btn small" href="${fileURL(x.raw_json_asset)}">Raw JSON ↓</a>` : ""}<button class="btn small" data-action="trace" data-id="${x.run_id}">Trace</button></div>`).join("")}</div>`;
}
function signInView() {
  const x = signInState;
  if (!x) return "";
  if (x.status === "waiting")
    return `<div class="note"><b>Finish signing in with Microsoft</b><p>Enter this one-time code on Microsoft’s page:</p><code class="signin-code">${esc(x.user_code)}</code><div class="actions section-space"><a class="btn primary" href="${esc(x.verification_uri)}" target="_blank" rel="noopener noreferrer">Open Microsoft sign-in ↗</a></div><p class="small section-space">This panel updates when sign-in completes.</p></div>`;
  return `<div class="note ${x.status === "failed" ? "error" : ""}">${esc(x.status === "completed" ? "Microsoft sign-in completed. Choose Microsoft sign-in in your Azure connection." : x.error || "Starting Microsoft sign-in…")}</div>`;
}
async function signInAzure(obj) {
  signInState = await post("/api/azure/sign-in", {
    tenant_id: obj.signin_tenant_id,
    client_id: obj.signin_client_id || "",
  });
  render();
  clearTimeout(signInTimer);
  pollSignIn(signInState.id);
}
async function pollSignIn(id) {
  try {
    signInState = await api("/api/azure/sign-in/" + id);
    const panel = $("#azure-signin-status");
    if (panel) panel.innerHTML = signInView();
    if (["completed", "failed"].includes(signInState.status)) {
      await refresh();
      if (page === "azure") render();
      return;
    }
    signInTimer = setTimeout(() => pollSignIn(id), 2000);
  } catch (e) {
    toast(e.message, true);
  }
}
async function saveAzureForm(obj, data) {
  for (const k of [
    "document_price_per_1000_pages",
    "vision_price_per_1000_requests",
    "search_price_per_1000_queries",
    "search_hourly_estimate",
  ])
    obj[k] = obj[k] === "" || obj[k] == null ? null : Number(obj[k]);
  obj.timeout_seconds = Number(obj.timeout_seconds);
  obj.publish_assets = data.has("publish_assets");
  const saved = await api(
    "/api/azure/profiles" + (editAzure ? "/" + editAzure : ""),
    { method: editAzure ? "PUT" : "POST", body: JSON.stringify(obj) },
  );
  config.azure_profile_id = saved.id;
  editAzure = "";
  azureDraft = null;
  await refresh();
  render();
  toast("Azure connection saved. Check access, then open Processing.");
}
function showCloudPlan(p) {
  modal(
    `<h2>${p.stage === "extract" ? "Review Azure extraction" : "Review Azure index publication"}</h2><p class="section-space"><b>${esc(p.source)}</b> · ${bytes(p.size)}${p.pages ? " · " + p.pages + " source pages" : ""}</p><p class="small break">Destination: ${esc(p.destination)}<br>Target: <code>${esc(p.target)}</code></p><div class="list section-space">${p.actions.map((x) => "<p>• " + esc(x) + "</p>").join("")}</div>${p.warnings.map((x) => '<div class="note warn section-space">' + esc(x) + "</div>").join("")}${p.stage === "index" ? '<details class="section-space"><summary>Index field configuration</summary><div><pre>' + json(p.index_fields) + "</pre></div></details>" : ""}<details class="section-space"><summary>Configured service rates</summary><div><pre>${json(p.rates)}</pre><p class="small">Unknown rates stay unpriced. Search hourly capacity is billed on your existing service and is excluded from per-run estimates.</p></div></details><div class="actions section-space"><button class="btn primary" data-action="azure-confirm-plan">${p.stage === "extract" ? "Send to Azure Layout" : "Create and publish new index"} →</button><button class="btn" data-action="close-modal">Back</button></div>`,
  );
}
async function azureAction(a, id, button) {
  if (a === "azure-new") {
    editAzure = "";
    azureDraft = null;
    render();
    return;
  }
  if (a === "azure-edit") {
    editAzure = id;
    azureDraft = null;
    render();
    $("#azure-profile-form").scrollIntoView({
      block: "start",
      behavior: "smooth",
    });
    return;
  }
  if (a === "azure-test") {
    await startJob(
      "/api/azure/profiles/" + id + "/test",
      {},
      "Azure connection check",
    );
    return;
  }
  if (a === "azure-use") {
    config.azure_profile_id = id;
    config.extraction_backend = "azure-document-intelligence";
    config.index_backend = "azure-ai-search";
    const p = state.azure_profiles.find((x) => x.id === id);
    if (p?.openai_connection_id) {
      config.connection_id = p.openai_connection_id;
      config.embedding_connection_id = p.openai_connection_id;
    }
    localStorage.setItem("agentic-rag-pipeline", JSON.stringify(config));
    await navigate("processing");
    return;
  }
  if (a === "azure-confirm-plan") {
    if (!cloudPlan) throw Error("Review the cloud operation again.");
    const p = cloudPlan;
    cloudPlan = null;
    const c = { ...config, azure_plan_id: p.id };
    $("#modal").close();
    await startJob(
      "/api/documents/" + p.document_id + "/" + p.stage,
      c,
      p.stage === "extract" ? "extraction" : "indexing",
    );
    return;
  }
  if (a === "azure-json") {
    const ex = detail.extraction,
      raw = await api(fileURL(ex.raw_json_asset));
    modal(
      `<h2>Azure Layout result</h2><p class="small section-space">Raw service output; source content is data. The preview shows up to 300,000 characters.</p><a class="btn section-space" href="${fileURL(ex.raw_json_asset)}">Download complete JSON ↓</a><pre>${esc(JSON.stringify(raw, null, 2).slice(0, 300000))}</pre>`,
    );
    return;
  }
}
function cloudMonitoring(m) {
  const cs = m.cloud_calls || [],
    sum = m.cloud_summary || {};
  return `<div class="card mb"><div class="card-header"><div><h3>Azure service activity</h3><p>Layout analysis and polls, visual embeddings, Search publishing and retrieval, private source uploads.</p></div>${badge((sum.calls || 0) + " REQUESTS")}</div><div class="doc-meta"><span>${sum.failed || 0} failed</span><span>${sum.unpriced || 0} unpriced</span><span>${price(sum.known_cost)} known estimate</span></div><div class="note section-space mb">${(
    state.azure_profiles || []
  )
    .filter((p) => p.search_hourly_estimate != null)
    .map(
      (p) =>
        esc(p.name) +
        ": existing Search capacity reference " +
        price(p.search_hourly_estimate) +
        "/hour. ",
    )
    .join(
      "",
    )}Per-run totals include available model and Azure operation estimates. Existing Search capacity, Blob storage retention and unconfigured charges are excluded. Read-only status polls are logged separately from analysis submissions.</div>${
    cs.length
      ? `<div class="table-wrap"><table><thead><tr><th>Service</th><th>Operation</th><th>Status</th><th>Units</th><th>Time</th><th>Estimate</th><th></th></tr></thead><tbody>${cs
          .slice(0, 80)
          .map(
            (c) =>
              `<tr><td>${esc(c.service)}</td><td class="small break">${esc(c.operation)}</td><td>${badge(c.status, c.status === "failed" ? "red" : "")}</td><td>${c.units ?? "?"} ${esc(c.unit)}</td><td>${c.duration?.toFixed(1) || "…"}s</td><td>${price(c.cost_usd)}</td><td><button class="btn small" data-action="trace" data-id="${c.run_id}">Trace</button></td></tr>`,
          )
          .join("")}</tbody></table></div>`
      : empty(
          "No Azure requests yet.",
          "Connect resources in Azure workspace and start processing to see service activity.",
        )
  }</div>`;
}

function indexFieldControls() {
  const schema = state.index_schema;
  if (!schema) return "";
  const flags = ["searchable", "filterable", "sortable", "retrievable"];
  return `<div class="card mb"><div class="card-header"><div><h3>Configure your index fields</h3><p>Choose how each field behaves before building a new index version.</p></div><button type="button" class="btn small" data-action="reset-index-fields">Restore defaults</button></div><div class="note mb"><b>Searchable</b>: keyword matching. <b>Filterable</b>: exact values and ranges. <b>Sortable</b>: service-side ordering. <b>Retrievable</b>: included in search responses. Collection fields cannot be sorted. Text and source identifiers required for grounded answers stay enabled.</div><div class="table-wrap index-fields-scroll" role="region" aria-label="Index field settings" tabindex="0"><table><thead><tr><th>Field</th>${flags.map((f) => "<th>" + f[0].toUpperCase() + f.slice(1) + "</th>").join("")}</tr></thead><tbody>${schema.fields
    .map((f) => {
      const settings = { ...f.defaults, ...config.index_fields?.[f.name] };
      return `<tr><td><b>${esc(f.label)}</b><br><code>${esc(f.name)}</code><small class="muted"> · ${esc(f.type.replace("Edm.", ""))}</small></td>${flags
        .map((flag) => {
          const required = Object.hasOwn(f.required, flag);
          return `<td><input type="checkbox" aria-label="${esc(f.label)} ${flag}" data-schema-field="${f.name}" data-schema-flag="${flag}" ${settings[flag] ? "checked" : ""} ${!f.allowed.includes(flag) || required ? "disabled" : ""} title="${required ? "Required for grounded answers" : !f.allowed.includes(flag) ? "Unsupported for this field type" : flag}"></td>`;
        })
        .join("")}</tr>`;
    })
    .join(
      "",
    )}</tbody></table></div>${inputField("Index tags (comma separated, optional)", "metadata_tags", (config.metadata_tags || []).join(", "), "text", "For example: finance, reviewed, training. Tags belong to this index version.")}<details><summary>Required system fields and vector storage</summary><div><pre>${json(schema.system_fields)}</pre><p class="small">The vector field keeps its pinned dimensions and embedding space. Azure applies these attributes to the published index. Local search honors searchable/filterable choices; service-side sorting is an Azure feature. Originals remain inspectable in Agentic RAG. Changing attributes requires a new index build.</p></div></details></div>`;
}
function retrievalControls() {
  const c = detail?.filter_catalog || {},
    f = chatOptions.filters || {},
    fields = c.fields || {},
    connection = state.connections.find(
      (x) =>
        x.id ===
        (chatOptions.connection_id ?? state.settings.active_connection),
    );
  const available = (k) => fields[k]?.values || [];
  const multi = (key, label) =>
    available(key).length
      ? `<div class="field"><label for="filter-${key}">${label}</label><select id="filter-${key}" name="filter:${key}" multiple size="3">${available(
          key,
        )
          .map(
            (v) =>
              `<option value="${esc(v.value)}" ${(f[key] || []).includes(v.value) ? "selected" : ""}>${esc(v.value)} (${v.count})</option>`,
          )
          .join(
            "",
          )}</select><small>Select multiple to match any of these values.</small></div>`
      : "";
  return `<details class="card section-space"><summary>Hybrid search, metadata filters & context</summary><div><div class="note section-space mb">Keyword matching + vector similarity are combined by default. Filters apply to both search paths before ranking. Your selected filters stay in force during agent refinements.</div>${c.requires_rebuild ? '<div class="note warn mb">This Azure index uses an earlier field schema. Build a new version to use the richer metadata filters.</div>' : ""}<div class="grid two">${selectField(
    "Retrieval method",
    "search_mode",
    [
      ["hybrid", "Hybrid · keyword + vector similarity"],
      ["keyword", "Keyword · exact terms / BM25"],
      ["vector", "Vector · semantic similarity"],
    ],
    chatOptions.search_mode,
  )}${inputField("Keyword terms (optional)", "keyword_query", chatOptions.keyword_query, "text", "Pins the keyword side while the agent refines semantic queries.")}<div class="field"><label for="research-effort">Investigation effort</label><select id="research-effort" name="effort">${["low", "medium", "high"].map((v) => `<option ${chatOptions.effort === v ? "selected" : ""} value="${v}">${v[0].toUpperCase() + v.slice(1)} effort</option>`).join("")}</select><small>Bounds searches, passes, model calls and visual inputs. Independent of native model reasoning.</small></div>${inputField("Overall text input cap (characters)", "question_context_chars", chatOptions.context_chars ?? "", "number", "Blank uses the answer connection limit" + (connection ? " (" + fmt(connection.context_chars) + " characters)" : "") + ". Agentic RAG budgets instructions, question, memory, metadata and evidence together.", 'min="8000" max="200000" step="1000"')}${fields.pages ? inputField("From page", "filter_page_from", f.page_from ?? "", "number", "", 'min="1"') : ""}${fields.pages ? inputField("To page", "filter_page_to", f.page_to ?? "", "number", "", 'min="1"') : ""}${multi("kinds", "Element types")}${multi("sections", "Sections")}${multi("source_names", "Source files")}${multi("source_types", "File types")}${multi("source_paths", "Repository paths")}${multi("sheets", "Workbook sheets")}${multi("tags", "Index tags")}${
    c.has_visual_filterable
      ? selectField(
          "Visual content",
          "filter_has_visual",
          [
            ["", "Any content"],
            ["true", "Only chunks with visuals"],
            ["false", "Only chunks without visuals"],
          ],
          f.has_visual == null ? "" : String(f.has_visual),
        )
      : ""
  }${c.has_timestamps ? inputField("Recording from (seconds)", "filter_time_from", f.time_from ?? "", "number", "", 'min="0" step="any"') : ""}${c.has_timestamps ? inputField("Recording to (seconds)", "filter_time_to", f.time_to ?? "", "number", "", 'min="0" step="any"') : ""}<div class="field"><label for="exact-filter-field">Exact field match (optional)</label><select id="exact-filter-field" name="exact_filter_field"><option value="">No extra exact match</option>${(c.scalar_fields || []).map((x) => `<option value="${x.name}" ${Object.keys(f.equals || {})[0] === x.name ? "selected" : ""}>${esc(x.label)}</option>`).join("")}</select></div>${inputField("Exact value", "exact_filter_value", Object.values(f.equals || {})[0] ?? "", "text", "Uses the field type: true/false for booleans, a number for numeric fields.")}</div>${check("Let the agent add narrower filters explicitly requested in my question", "use_agent_filters", chatOptions.use_agent_filters)}<p class="footer-note">Context limits are text-character limits, not advertised model token windows. Output tokens are capped separately. Visual token use is model-specific. Retrieved coverage and context trimming appear in the run trace.</p></div></details>`;
}
function readResearchOptions(form) {
  const data = new FormData(form),
    filters = {};
  for (const key of [
    "kinds",
    "sections",
    "source_names",
    "source_types",
    "source_paths",
    "sheets",
    "tags",
  ]) {
    const values = data.getAll("filter:" + key);
    if (values.length) filters[key] = values;
  }
  for (const key of ["page_from", "page_to", "time_from", "time_to"]) {
    const value = data.get("filter_" + key);
    if (value !== null && value !== "") filters[key] = Number(value);
  }
  const visual = data.get("filter_has_visual");
  if (visual) filters.has_visual = visual === "true";
  const key = data.get("exact_filter_field"),
    value = data.get("exact_filter_value");
  if (key && value !== "") {
    const type = (detail?.filter_catalog?.scalar_fields || []).find(
      (x) => x.name === key,
    )?.type;
    if (type === "Edm.Boolean" && !["true", "false"].includes(value))
      throw Error("Use true or false for an exact boolean value.");
    if (
      type !== "Edm.String" &&
      type !== "Edm.Boolean" &&
      !Number.isFinite(Number(value))
    )
      throw Error("Enter a numeric exact value for this field.");
    filters.equals = {
      [key]:
        type === "Edm.Boolean"
          ? value === "true"
          : type === "Edm.String"
            ? value
            : Number(value),
    };
  }
  Object.assign(chatOptions, {
    filters,
    search_mode: data.get("search_mode") || "hybrid",
    keyword_query: data.get("keyword_query") || "",
    use_agent_filters: data.has("use_agent_filters"),
    effort: data.get("effort") || "medium",
    context_chars: data.get("question_context_chars")
      ? Number(data.get("question_context_chars"))
      : null,
    connection_id: data.get("connection_id") || "",
    max_passes: Number(data.get("max_passes") || 2),
    preview: data.has("preview"),
    generate_image: data.has("generate_image"),
  });
  return chatOptions;
}
function localEmbeddingMonitoring(m) {
  const rows = m.local_calls || [];
  if (!rows.length) return "";
  return `<div class="card mb"><div class="card-header"><div><h3>Local text embedding activity</h3><p>EmbeddingGemma and Qwen3 run through your local Ollama service.</p></div>${badge(rows.length + " RECENT CALLS")}</div><div class="note mb">Local API fees: $0. Hardware, electricity and model downloads are excluded. Failures never trigger a cloud embedding fallback.</div><div class="table-wrap"><table><thead><tr><th>Model</th><th>Operation</th><th>Status</th><th>Dimensions</th><th>Time</th></tr></thead><tbody>${rows.map((r) => `<tr><td>${esc(r.model)}</td><td>${esc(r.operation)}</td><td>${badge(r.status, r.status === "failed" ? "red" : "")}</td><td>${r.dimension ?? "—"}</td><td>${r.duration?.toFixed(2) || "…"}s</td></tr>`).join("")}</tbody></table></div></div>`;
}
