"""Loopback-only local API and frontend."""
from __future__ import annotations
import hashlib, ipaddress, json, os, shutil, socket, threading, time
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse,urljoin
import httpx
from fastapi import FastAPI, File, UploadFile, Request, HTTPException, Form
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel,Field
from . import store as s, providers as p
from .schemas import Connection, Pipeline, Question, Review, Strict, AzureProfile, AzureSignIn, AzurePlanRequest
from . import azure_cloud, azure_auth, retrieval, index_schema
from .extraction import supported,FORMATS
from .indexing import extract_document,build_index,preview_chunks
from .agent import answer,SKILLS,TOOLS
from .evaluation import parse_dataset,run_evaluation

p.bootstrap()
@asynccontextmanager
async def lifespan(app):
    for job in s.rows('jobs'):
        if job['status'] in {'running','queued'}:
            s.patch('jobs',job['id'],status='failed',error='App restarted before this job completed. Rerun the operation.',finished=s.now())
    for evaluation in s.rows('evaluations'):
        if evaluation.get('status')=='running': s.patch('evaluations',evaluation['id'],status='failed',error='App restarted before evaluation completed. Completed cases were preserved.')
    yield
    for job in s.rows('jobs'):
        if job.get('owner_pid')==os.getpid() and job['status'] in {'queued','running'}: s.patch('jobs',job['id'],cancel=True)

app=FastAPI(lifespan=lifespan,title='Agentic RAG · Document Knowledge Studio',version='1.0.0',docs_url='/api/docs')
POOL=ThreadPoolExecutor(max_workers=2,thread_name_prefix='agentic-rag-job')
JOB_LOCK=threading.RLock()
BROWSE_ROOTS=[Path.home()/x for x in ['Desktop','Documents','Downloads']]
SKIP_DIRS={'.git','.venv','.venv-evaluation','venv','node_modules','__pycache__','.cache','data','dist','build','.next','.pnpm-store','target','.idea','.vscode'}
SECRET_NAMES={'.env','.secret-key','.gemini-bootstrap','id_rsa','id_ed25519','credentials.json','service-account.json'}

@app.middleware('http')
async def local_only(request:Request,call_next):
    host=request.headers.get('host','').split(':')[0]
    if host not in {'127.0.0.1','localhost','testserver'}: return JSONResponse({'detail':'Open this app through localhost.'},status_code=403)
    origin=request.headers.get('origin')
    if request.method not in {'GET','HEAD','OPTIONS'}:
        if request.headers.get('x-agentic-rag-client')!='local-workspace': return JSONResponse({'detail':'Missing local workspace header.'},status_code=403)
        if origin and origin not in {f'http://127.0.0.1:{request.url.port}',f'http://localhost:{request.url.port}','http://testserver'}: return JSONResponse({'detail':'Cross-origin request rejected.'},status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    response.headers['Cache-Control']='no-store'
    return response

@app.exception_handler(RequestValidationError)
async def validation_error(request,exc):
    # Do not echo submitted keys or other request values in validation errors.
    return JSONResponse({'detail':[{'loc':e['loc'],'msg':e['msg'],'type':e['type']} for e in exc.errors()]},status_code=422)

@app.exception_handler(ValueError)
async def value_error(request,exc): return JSONResponse({'detail':str(exc)},status_code=422)

@app.get('/api/health')
def health(): return {'app':'agentic-rag','version':'1.0.0','pid':os.getpid()}

@app.exception_handler(httpx.HTTPError)
async def source_network_error(request,exc):
    return JSONResponse({'detail':'Could not fetch the webpage. Check its public URL and network access.'},status_code=422)

@app.get('/')
def home(): return FileResponse(s.ROOT/'static/index.html')

@app.get('/api/state')
def state():
    return {'provider_catalog':p.CATALOG,'index_schema':index_schema.info(),'azure_profiles':[azure_cloud.public(x) for x in s.rows('azure_profiles')],'azure_accounts':azure_auth.accounts(),'azure_publications':s.rows('azure_publications')[:100],'azure_analyses':s.rows('azure_analyses')[:100],'documents':s.rows('documents'),'connections':[p.public(x) for x in s.rows('connections')],'settings':s.get('settings','main'),'jobs':s.rows('jobs')[:100],'datasets':s.rows('datasets'),'evaluations':[{k:v for k,v in x.items() if k!='results'} for x in s.rows('evaluations')],'storage':str(s.DATA),'roots':[str(x) for x in BROWSE_ROOTS if x.exists()],'formats':sorted(FORMATS),'skills':SKILLS,'tools':TOOLS}

@app.post('/api/azure/profiles')
def azure_save(body:AzureProfile): return azure_cloud.save(body.model_dump())
@app.put('/api/azure/profiles/{id}')
def azure_update(id:str,body:AzureProfile): return azure_cloud.save(body.model_dump(),id)
@app.post('/api/azure/profiles/{id}/test')
def azure_test(id:str): return submit('Azure connection check',azure_cloud.test_profile,id)
@app.post('/api/azure/sign-in')
def azure_sign_in(body:AzureSignIn): return azure_auth.start(body.model_dump())
@app.get('/api/azure/sign-in/{id}')
def azure_sign_in_status(id:str): return azure_auth.status(id)
@app.post('/api/azure/plan')
def azure_plan(body:AzurePlanRequest): return azure_cloud.plan(body.document_id,body.stage,body.config.model_dump())
@app.get('/api/azure/assets/{index_id}/{asset_id}')
def azure_asset(index_id:str,asset_id:str):
    # Only asset references recorded during this app's publication can be fetched.
    index=s.get('indexes',index_id,True)
    matches=[x for x in index.get('blob_assets',[]) if s.digest(x['local_asset'])[:16]==asset_id]
    if len(matches)!=1: raise ValueError('Cloud asset not found in this index snapshot.')
    item=matches[0]; profile=azure_cloud.resolve(index['azure_profile']['id'],index['azure_profile'])
    if item['endpoint']!=profile['blob_endpoint']: raise ValueError('Cloud asset endpoint changed.')
    from azure.storage.blob import BlobServiceClient
    client=BlobServiceClient(account_url=item['endpoint'],credential=profile['blob_key'] if profile.get('auth_mode','api-key')=='api-key' else azure_auth.credential(profile),retry_total=0)
    try:
        raw=client.get_blob_client(container=item['container'],blob=item['blob_name']).download_blob(max_concurrency=1).readall()
        import mimetypes
        mime=mimetypes.guess_type(item['local_asset'])[0] or 'application/octet-stream'
        inline=mime.startswith(('image/','audio/','video/')) or mime=='application/pdf'
        return Response(raw,media_type=mime,headers={'Content-Disposition':('inline' if inline else 'attachment')+'; filename="'+Path(item['local_asset']).name.replace('"','')+'"'})
    except Exception: raise ValueError('Could not retrieve the private cloud reference. Check Blob data access.') from None
    finally: client.close()

class Settings(Strict):
    active_connection:str=''
    guidance:str=Field(max_length=12000)
    memory_enabled:bool=True
@app.put('/api/settings')
def settings(body:Settings): return s.put('settings','main',body.model_dump())

@app.post('/api/connections')
def connection(body:Connection,copy_from:str=''):
    if copy_from and s.get('connections',copy_from,True)['provider']!=body.provider:raise ValueError('A saved key can only be reused with the same provider.')
    data=p.prepare(body.model_dump(),copy_from) if copy_from else p.prepare(body.model_dump())
    return p.public(s.put('connections',s.uid(),data))
@app.put('/api/connections/{id}')
def update_connection(id:str,body:Connection): return p.save(body.model_dump(),id)
@app.delete('/api/connections/{id}')
def delete_connection(id:str): s.delete('connections',id); return {'deleted':True}
@app.post('/api/connections/{id}/test')
def test_connection(id:str):
    c=p.resolve(id); run=s.uid(); budget=p.Budget(run,2)
    text,_=p.generate(c,budget,'You are a connection test.','Reply with exactly: Connection ready.')
    vision=False
    if c.get('vision'):
        from PIL import Image,ImageDraw
        from .extraction import asset
        import io
        image=Image.new('RGB',(200,100),'white'); d=ImageDraw.Draw(image); d.rectangle((10,10,90,90),fill='red'); d.rectangle((110,10,190,90),fill='blue')
        buff=io.BytesIO();image.save(buff,format='PNG'); a=asset('_system','vision-test.png',buff.getvalue())
        seen,_=p.generate(c,budget,'You are testing vision.','Name the two rectangle colors.',[s.asset_path(a)])
        vision='red' in seen.lower() and 'blue' in seen.lower()
    with s.LOCK:
        current=s.get('connections',id,True)
        if any(current.get(k)!=c.get(k) for k in ['provider','model','endpoint','auth_mode','tenant_id','client_id','secret','vision']):raise ValueError('This connection changed during its test. Test the current model and credentials again.')
        s.patch('connections',id,tested_text=True,tested_vision=vision,tested_at=s.now())
    return {'ready':True,'text':text,'vision_verified':vision,'run_id':run}
@app.get('/api/connections/{id}/models')
def models(id:str):
    return p.list_models(p.resolve(id))

@app.post('/api/model-options')
def discover_models(body:Connection,connection_id:str=''):
    c=p.prepare(body.model_dump(),connection_id or None)
    c['id']=connection_id or 'model-discovery'
    c['key']=p.cipher().decrypt(c['secret'].encode()).decode() if c.get('secret') else ''
    return p.list_models(c)

def submit(kind,fn,*args,scope=''):
    with JOB_LOCK:
        if scope and any(x.get('scope')==scope and x['status'] in {'queued','running'} for x in s.rows('jobs')): raise ValueError('A job is already running for this document. Wait or cancel it first.')
        id=s.uid(); s.put('jobs',id,{'kind':kind,'status':'queued','created':s.now(),'scope':scope,'cancel':False,'owner_pid':os.getpid()})
    def worker():
        s.patch('jobs',id,status='running',started=s.now()); s.event(id,'start',f'{kind} started')
        try:
            result=fn(*args,id)
            if s.get('jobs',id).get('cancel'): raise ValueError('Cancelled by user.')
            s.patch('jobs',id,status='completed',finished=s.now(),result=result,error=None); s.event(id,'complete',f'{kind} completed')
        except Exception as exc:
            message=p.safe_error(exc); s.patch('jobs',id,status='cancelled' if s.get('jobs',id).get('cancel') else 'failed',error=message,finished=s.now()); s.event(id,'error',message)
            if kind=='evaluation' and s.get('evaluations',id): s.patch('evaluations',id,status='failed',error=message)
    POOL.submit(worker); return {'job_id':id}

@app.get('/api/jobs/{id}')
def job(id:str):
    j=s.get('jobs',id,True); j['events']=sorted([e for e in s.rows('events') if e['run_id']==id],key=lambda x:x['time']); return j
@app.post('/api/jobs/{id}/cancel')
def cancel(id:str): return s.patch('jobs',id,cancel=True)

def allowed_path(raw,folder=False):
    path=Path(raw).expanduser().resolve(strict=True)
    if not any(path.is_relative_to(root.resolve()) for root in BROWSE_ROOTS): raise ValueError('Choose a path within Desktop, Documents or Downloads.')
    if any(part.startswith('.') or part in SKIP_DIRS for part in path.parts[len(Path.home().parts):]) or path.name in SECRET_NAMES: raise ValueError('Hidden files, secrets and runtime folders are excluded.')
    if folder and not path.is_dir(): raise ValueError('Choose a folder.')
    return path

@app.get('/api/browse')
def browse(path:str=''):
    if not path: return {'path':'','entries':[{'name':p.name,'path':str(p),'directory':True} for p in BROWSE_ROOTS if p.exists()]}
    folder=allowed_path(path,True)
    entries=[]
    for pth in sorted(folder.iterdir(),key=lambda x:(not x.is_dir(),x.name.lower())):
        if pth.name.startswith('.') or pth.name in SKIP_DIRS or pth.name in SECRET_NAMES or pth.is_symlink(): continue
        if pth.is_dir() or supported(pth): entries.append({'name':pth.name,'path':str(pth),'directory':pth.is_dir(),'size':pth.stat().st_size if pth.is_file() else None})
        if len(entries)>=500: break
    parent=str(folder.parent) if any(folder.parent.is_relative_to(r) for r in BROWSE_ROOTS) else ''
    return {'path':str(folder),'parent':parent,'entries':entries}

def register(name,raw,origin='upload'):
    if not supported(Path(name)): raise ValueError('Unsupported format. Choose a supported document, text, image or media file.')
    if len(raw)>250*1024*1024: raise ValueError('Single files are limited to 250 MB.')
    if not raw: raise ValueError('The file is empty.')
    id=s.uid(); safe=Path(name).name; relative=f'originals/{id}/{safe}'; dest=s.DATA/relative; dest.parent.mkdir();dest.write_bytes(raw)
    return s.put('documents',id,{'name':safe,'path':relative,'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw),'origin':origin,'status':'stored','created':s.now(),'active_index':'','extraction_id':''})

@app.post('/api/documents/upload')
async def upload(file:UploadFile=File(...)):
    raw=await file.read(250*1024*1024+1); return register(file.filename or 'document.txt',raw)
class ImportPath(Strict): path:str
@app.post('/api/documents/import')
def import_path(body:ImportPath):
    path=allowed_path(body.path)
    if path.is_file(): return register(path.name,path.read_bytes(),str(path))
    files=[]; total=0
    for root,dirs,names in os.walk(path,followlinks=False):
        dirs[:]=[d for d in dirs if not d.startswith('.') and d not in SKIP_DIRS and not (Path(root)/d).is_symlink()]
        for name in sorted(names):
            file=Path(root)/name
            if file.is_symlink() or name in SECRET_NAMES or name.startswith('.') or not supported(file): continue
            if file.stat().st_size>5*1024*1024: continue
            if len(files)>=2000: raise ValueError('Folder exceeds 2000 supported files. Choose a smaller folder.')
            raw=file.read_bytes();total+=len(raw)
            if total>250*1024*1024: raise ValueError('Folder import exceeds 250 MB.')
            files.append((str(file.relative_to(path)),raw))
    if not files: raise ValueError('No supported files in this folder.')
    id=s.uid(); folder=s.DATA/'originals'/id;folder.mkdir()
    manifest=[]
    for name,raw in files:
        target=folder/'files'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw);manifest.append({'name':name,'path':str(target.relative_to(s.DATA))})
    relative=f'originals/{id}/repository.repo.json';(s.DATA/relative).write_text(json.dumps(manifest))
    return s.put('documents',id,{'name':path.name+' (folder)','path':relative,'is_bundle':True,'sha256':s.digest([(n,hashlib.sha256(r).hexdigest()) for n,r in files]),'size':total,'origin':str(path),'status':'stored','created':s.now(),'active_index':'','extraction_id':'','file_count':len(files)})

class ImportURL(Strict): url:str=Field(max_length=2000)
def validate_url(url):
    u=urlparse(url)
    if u.scheme not in {'http','https'} or not u.hostname or u.username or u.password or u.port not in {None,80,443}: raise ValueError('Enter a public HTTP(S) webpage URL.')
    addresses=socket.getaddrinfo(u.hostname,u.port or (443 if u.scheme=='https' else 80),type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses): raise ValueError('Private/internal URLs cannot be imported.')
@app.post('/api/documents/url')
def import_url(body:ImportURL):
    url=body.url
    with httpx.Client(timeout=30,follow_redirects=False,trust_env=False) as client:
        for _ in range(4):
            validate_url(url)
            with client.stream('GET',url,headers={'User-Agent':'Agentic RAG-Local-RAG/1.0'}) as response:
                if response.is_redirect: url=urljoin(url,response.headers['location']);continue
                response.raise_for_status()
                if not any(t in response.headers.get('content-type','') for t in ['text/html','text/plain']): raise ValueError('URL must return an HTML or text webpage.')
                raw=bytearray()
                for packet in response.iter_bytes():
                    raw.extend(packet)
                    if len(raw)>10*1024*1024: raise ValueError('Webpage exceeds 10 MB.')
                return register((urlparse(url).hostname or 'webpage')+'.html',bytes(raw),url)
    raise ValueError('Too many webpage redirects.')

@app.get('/api/documents/{id}')
def document(id:str):
    doc=s.get('documents',id,True);return {**doc,'extraction':s.get('extractions',doc.get('extraction_id','')),'chunk_preview':s.get('chunk_previews',doc.get('chunk_preview','')),'indexes':[x for x in s.rows('indexes') if x['document_id']==id]}
@app.post('/api/documents/{id}/extract')
def extract(id:str,body:Pipeline): return submit('extraction',extract_document,id,body.model_dump(),scope=id)
@app.post('/api/documents/{id}/chunks')
def chunks(id:str,body:Pipeline): return submit('chunking',preview_chunks,id,body.model_dump(),scope=id)
@app.post('/api/documents/{id}/index')
def index(id:str,body:Pipeline): return submit('indexing',build_index,id,body.model_dump(),scope=id)
@app.get('/api/indexes/{id}')
def get_index(id:str): return s.get('indexes',id,True)
@app.get('/api/indexes/{id}/filters')
def index_filters(id:str): return retrieval.catalog(s.get('indexes',id,True))
@app.get('/api/index-schema')
def get_index_schema(): return index_schema.info()
@app.post('/api/chat')
def chat(body:Question): return submit('chat',answer,body.model_dump())
@app.get('/api/sessions')
def sessions(document_id:str): return [x for x in s.rows('sessions') if x['document_id']==document_id and not x.get('isolated')]
@app.get('/api/sessions/{id}')
def session_detail(id:str):
    session=s.get('sessions',id,True)
    candidates=[x for x in s.rows('answers') if x.get('session_id')==id]
    return {**session,'latest_answer':candidates[0] if candidates else None}
@app.get('/api/memory')
def memories(document_id:str): return [x for x in s.rows('memory') if x['document_id']==document_id]
class Memory(Strict):
    document_id:str
    text:str=Field(min_length=1,max_length=3000)
@app.post('/api/memory')
def remember(body:Memory):
    s.get('documents',body.document_id,True);return s.put('memory',s.uid(),{**body.model_dump(),'type':'user_preference','updated':s.now()})
@app.delete('/api/memory/{id}')
def forget(id:str): s.delete('memory',id);return {'deleted':True}
@app.delete('/api/sessions/{id}')
def forget_session(id:str):
    s.delete('sessions',id);s.delete('memory','summary-'+id);return {'deleted':True}
@app.get('/api/monitor')
def monitor():
    calls=s.rows('calls');cloud=s.rows('cloud_calls');known=[c['cost_usd'] for c in calls+cloud if c.get('cost_usd') is not None]
    return {'local_calls':s.rows('local_calls')[:100],'cloud_calls':cloud[:300],'cloud_summary':{'calls':len(cloud),'unpriced':sum(c.get('cost_usd') is None for c in cloud),'failed':sum(c.get('status')=='failed' for c in cloud),'known_cost':sum(c['cost_usd'] for c in cloud if c.get('cost_usd') is not None)},'jobs':s.rows('jobs')[:100],'events':s.rows('events')[:300],'calls':calls[:300],'answers':s.rows('answers')[:100],'summary':{'calls':len(calls),'input_tokens':sum(c.get('input_tokens') or 0 for c in calls),'output_tokens':sum(c.get('output_tokens') or 0 for c in calls),'estimated_known_cost':sum(known) if known else None,'unpriced_calls':sum(c.get('cost_usd') is None for c in calls+cloud),'failed_calls':sum(c.get('status')=='failed' for c in calls)}}
@app.get('/api/monitor/{run}')
def trace(run:str):
    return {'local_calls':[e for e in s.rows('local_calls') if e['run_id']==run],'cloud_calls':[e for e in s.rows('cloud_calls') if e['run_id']==run],'events':[e for e in s.rows('events') if e['run_id']==run],'calls':[e for e in s.rows('calls') if e['run_id']==run],'answer':s.get('answers',run),'job':s.get('jobs',run)}
@app.post('/api/reviews/{id}')
def review(id:str,body:Review): return s.put('reviews',id,{**body.model_dump(),'updated':s.now()})
@app.get('/api/reviews/{id}')
def get_review(id:str): return s.get('reviews',id)
@app.post('/api/datasets')
async def dataset(file:UploadFile=File(...),document_id:str=Form(...),index_id:str=Form(...)):
    return parse_dataset(await file.read(3*1024*1024+1),file.filename or 'dataset.json',document_id,index_id)
@app.get('/api/datasets/{id}')
def dataset_get(id:str): return s.get('datasets',id,True)
class Evaluation(Strict):
    dataset_id:str
    connection_ids:list[str]=Field(min_length=1,max_length=4)
    judge_id:str=''
    max_calls:int=Field(default=10,ge=1,le=30)
    max_passes:int=Field(default=2,ge=1,le=4)
@app.post('/api/evaluations')
def evaluation(body:Evaluation):
    def run(id): return run_evaluation(body.dataset_id,body.connection_ids,id,body.max_calls,body.judge_id,body.max_passes)
    return submit('evaluation',run)
@app.get('/api/evaluations/{id}')
def get_evaluation(id:str):
    obj=s.get('evaluations',id,True)
    obj['reviews']={x['run_id']:s.get('reviews',x['run_id']) for x in obj.get('results',[])};return obj
@app.get('/api/files/{relative:path}')
def file(relative:str):
    path=s.asset_path(relative);ext=path.suffix.lower()
    inline=ext in {'.png','.jpg','.jpeg','.webp','.pdf','.mp3','.mp4','.wav','.m4a','.ogg','.webm','.mov'}
    return FileResponse(path,filename=path.name,content_disposition_type='inline' if inline else 'attachment')
@app.get('/api/examples/{name}')
def example(name:str):
    if name not in {'ground-truth-template.csv','ground-truth-template.json'}: raise ValueError('Example not found.')
    return FileResponse(s.ROOT/'examples'/name,filename=name)
app.mount('/static',StaticFiles(directory=s.ROOT/'static'),name='static')
