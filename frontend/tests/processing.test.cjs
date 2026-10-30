const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function app() {
  const storage = new Map();
  const context = vm.createContext({
    localStorage: {
      getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: (key) => storage.delete(key),
    },
    location: { hash: "#processing" },
    document: {
      addEventListener() {},
      querySelector() {
        return null;
      },
      querySelectorAll() {
        return [];
      },
    },
    window: { addEventListener() {}, scrollTo() {} },
    setInterval() {},
    setTimeout() {},
    clearTimeout() {},
    console,
  });
  const source = fs
    .readFileSync(path.join(__dirname, "..", "app.js"), "utf8")
    .replace(/\(async \(\) => \{[\s\S]*?\n\}\)\(\);/, "");
  vm.runInContext(source, context);
  vm.runInContext(
    'docId="document-a"; state={jobs:[]}; updatePipelineStatus=()=>{};',
    context,
  );
  return context;
}
const run = (context, code) => vm.runInContext(code, context);

test("a newly discovered running job is attached to its inline stage without a top banner", async () => {
  const context = app();
  run(
    context,
    'api=async()=>({jobs:[{id:"running",scope:docId,kind:"extraction",status:"running",created:10,progress:{percent:32.5,completed:2,total:4,unit:"pages"}}]}); pollJob=()=>{};',
  );
  await run(context, "syncPipelineJobs()");
  assert.equal(run(context, "pipelineBusy()"), true);
  assert.equal(run(context, 'pipelineJob("extract").id'), "running");
  assert.doesNotMatch(run(context, "banners()"), /run-banner/);
  assert.match(run(context, 'pipelineStatus("extract")'), /value="32"/);
});

test("a stale duplicate running record cannot override the same completed job", () => {
  const context = app();
  run(
    context,
    'state.jobs=[{id:"same",scope:docId,kind:"extraction",status:"running",created:10}]; pipelineRuns.set("document-a:extraction",{...state.jobs[0],status:"completed",result:{count:5}});',
  );
  assert.equal(run(context, "pipelineBusy()"), false);
  assert.match(run(context, 'pipelineStatus("extract")'), /value="100"/);
});

test("a submission conflict reconnects to the real job instead of leaving a toast-only failure", async () => {
  const context = app();
  run(
    context,
    'let conflict=false; api=async(url,options={})=>{if(options.method==="POST"){conflict=true;throw Error("A job is already running");} return {jobs:conflict?[{id:"actual",scope:docId,kind:"extraction",status:"running",created:10}]:[]};}; pollJob=()=>{};',
  );
  await run(
    context,
    'startJob("/api/documents/document-a/index",{},"indexing")',
  );
  assert.equal(run(context, 'pipelineJob("extract").id'), "actual");
  assert.equal(run(context, "pipelineBusy()"), true);
  assert.equal(run(context, 'pipelineRuns.has("document-a:indexing")'), false);
});

test("quota waits are visible inside the operation and do not invent progress", () => {
  const context = app();
  run(
    context,
    'pipelineRuns.set("document-a:extraction",{id:"wait",scope:docId,kind:"extraction",status:"running",created:10,progress:{percent:65,message:"Describing visuals"},rate_wait:{provider:"gemini",until:Date.now()/1000+25}});',
  );
  const html = run(context, 'pipelineStatus("extract")');
  assert.match(html, /before the next gemini request/);
  assert.match(html, /value="65"/);
});

test("field configuration precedes the single index-build button", () => {
  const context = app();
  run(
    context,
    "state={documents:[{id:docId}],connections:[],jobs:[],settings:{},index_schema:{fields:[],system_fields:[]}}; detail={indexes:[]};",
  );
  const html = run(context, "processing()");
  assert.equal((html.match(/data-stage="index"/g) || []).length, 1);
  assert(
    html.indexOf("Configure your index fields") <
      html.indexOf("Build your vector index"),
  );
  assert.match(html, /index-fields-scroll/);
});

test("every chunk is reachable and the inspector shows saved searchable fields with escaped visual descriptions", () => {
  const context = app();
  run(
    context,
    `const rows=Array.from({length:80},(_,i)=>({id:'c'+String(i+1).padStart(5,'0'),title:'Topic',text:'Exact indexed text '+i,element_ids:['visual'],pages:[1],kinds:['image'],searchable_values:{title:'Topic',content:'Exact indexed text '+i},keyword_text:'Topic\\nExact indexed text '+i,elements:[{id:'visual',kind:'image',asset:'assets/visual.png',description:'<script>untrusted source</script>'}]})); detail={active_index:'index-a',indexes:[{id:'index-a',chunks:rows}]}; chunkInspection={target:'index:index-a',fields:[{name:'title',label:'Chunk title',searchable:true},{name:'content',label:'Chunk text',searchable:true}],chunks:rows}; chunkPage=3;`,
  );
  const html = run(context, "chunksView()");
  assert.match(html, /c00080/);
  assert.match(html, /Searchable field values/);
  assert.match(html, /assets\/visual.png/);
  assert.match(html, /&lt;script&gt;untrusted source&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>untrusted source/);
  run(context, 'chunkSearch="c00080"; chunkPage=0;');
  assert.match(run(context, "chunksView()"), /1 matching chunks/);
});
