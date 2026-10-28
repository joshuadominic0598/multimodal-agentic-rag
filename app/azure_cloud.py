"""Existing Azure resources only; immutable index publication and audited service calls."""
from __future__ import annotations
import json, re, time
from pathlib import Path
from urllib.parse import urlparse
import httpx
import numpy as np
from . import store as s, providers as p, azure_auth as auth, retrieval as rt, index_schema as schema

DI_VERSION='2024-11-30'; SEARCH_VERSION='2025-09-01'
KEYS=('document_key','search_key','vision_key','blob_key')
SUFFIXES={'document':('.cognitiveservices.azure.com','.services.ai.azure.com'), 'search':('.search.windows.net',),
          'vision':('.cognitiveservices.azure.com','.api.cognitive.microsoft.com'), 'blob':('.blob.core.windows.net',)}
SUPPORTED={'.pdf','.png','.jpg','.jpeg','.bmp','.tiff','.tif','.heif','.docx','.xlsx','.pptx','.html','.htm'}

def endpoint(value,service):
    if not value: return ''
    u=urlparse(value)
    if u.scheme!='https' or not u.hostname or not u.hostname.endswith(SUFFIXES[service]) or u.username or u.password or u.query or u.fragment or u.port not in {None,443} or u.path not in {'','/'}:
        raise ValueError(f'Enter the HTTPS {service} resource endpoint without a path, query or credentials. Public Azure endpoints are supported.')
    return value.rstrip('/')

def public(profile):
    return {k:v for k,v in profile.items() if not k.endswith('_secret') and k not in KEYS} | {f'has_{k}':bool(profile.get(k+'_secret')) for k in KEYS}

def save(data,id=None):
    data=dict(data); old=s.get('azure_profiles',id,True) if id else {}; auth.identity(data)
    for service in SUFFIXES: data[service+'_endpoint']=endpoint(data.get(service+'_endpoint',''),service)
    if data.get('publish_assets') and not data.get('blob_endpoint'): raise ValueError('Add an existing private Blob Storage account to publish source assets.')
    if data.get('openai_connection_id'):
        c=s.get('connections',data['openai_connection_id'],True)
        if c['provider']!='azure': raise ValueError('Select an Azure OpenAI model connection.')
    for key in KEYS:
        raw=data.pop(key,'').strip(); data[key+'_secret']=p.cipher().encrypt(raw.encode()).decode() if raw else old.get(key+'_secret','')
    if data['auth_mode']=='api-key':
        for service in ('document','search')+ (('vision',) if data.get('vision_endpoint') else ()) + (('blob',) if data.get('publish_assets') else ()):
            if not data.get(service+'_key_secret'): raise ValueError(f'Enter the {service} service key.')
    data['created']=old.get('created',s.now()); data['updated']=s.now()
    return public(s.put('azure_profiles',id or s.uid(),data))

def resolve(id,snapshot=None):
    cfg=s.get('azure_profiles',id,True)
    # Pin resource identity, auth mode, rates and API settings. Only rotate secrets in place.
    if snapshot:
        for key in ['document_endpoint','search_endpoint','vision_endpoint','blob_endpoint','auth_mode','tenant_id','client_id']:
            if cfg.get(key,'')!=snapshot.get(key,''): raise ValueError('Azure resource identity changed since this index was built. Restore its connection or build a new index.')
        cfg={**cfg,**snapshot}
    for key in KEYS: cfg[key]=p.cipher().decrypt(cfg[key+'_secret'].encode()).decode() if cfg.get(key+'_secret') else ''
    return cfg

def canonical(config): return {k:v for k,v in config.items() if k!='azure_plan_id'}

def source_info(doc,cfg,profile):
    ext=Path(doc['path']).suffix.lower()
    if doc.get('is_bundle') or ext not in SUPPORTED: raise ValueError('Azure Layout supports PDF, supported images, DOCX, XLSX, PPTX and HTML. Export legacy Office files to a supported format. Code, text and recordings use the local workflow.')
    limit=4 if profile['document_tier']=='F0' else 250
    if doc['size']>limit*1024*1024: raise ValueError(f'This document exceeds the {limit} MB limit for this connection.')
    pages=None; warnings=[]
    if ext=='.pdf':
        import pymupdf
        with pymupdf.open(s.asset_path(doc['path'])) as pdf:
            if pdf.is_encrypted: raise ValueError('Unlock the PDF before Azure extraction.')
            pages=len(pdf)
            if pages>2000: raise ValueError('Azure Layout supports up to 2,000 PDF pages. Split this document first.')
    if ext in {'.docx','.xlsx','.pptx','.html','.htm'}:
        warnings.append('Layout extracts Office/HTML text and structure but does not extract embedded Office images. XLSX tables have limited support. Export to PDF for visual layout extraction.')
    if profile['document_tier']=='F0': warnings.append('Azure F0 returns at most two pages. The result is partial for larger documents; Agentic RAG will label its coverage.')
    if profile['document_tier']=='unknown': warnings.append('Service tier is unknown. Free-tier truncation may apply; returned page coverage will be shown.')
    if cfg.azure_pages: warnings.append('Only the selected page range will be extracted; this is a partial document view.')
    return {'format':ext,'source_pages':pages,'warnings':warnings}

def plan(doc_id,stage,config):
    from .schemas import Pipeline
    cfg=Pipeline(**config); schema.configure(cfg.index_fields); doc=s.get('documents',doc_id,True); profile=resolve(cfg.azure_profile_id)
    info=source_info(doc,cfg,profile) if stage=='extract' else {'warnings':[]}
    ext=s.get('extractions',doc.get('extraction_id',''))
    if stage=='index' and (not ext or ext.get('backend')!='azure-document-intelligence'): raise ValueError('Extract this document with Azure Document Intelligence before publishing an Azure index.')
    if cfg.embedding=='azure-vision' and not profile.get('vision_endpoint'): raise ValueError('Add Azure Vision to this connection before choosing native Azure visual embeddings.')
    target=f"{profile['index_prefix']}-{doc_id[:8]}-{s.uid()[:8]}" if stage=='index' else 'prebuilt-layout'
    id=s.uid(); pub=public(profile)
    record={'document_id':doc_id,'source_hash':doc['sha256'],'extraction_id':doc.get('extraction_id',''),'stage':stage,
        'config_hash':s.digest(canonical(config)),'profile_hash':s.digest(pub),'profile_id':profile['id'],'target':target,'created':s.now(),'expires':s.now()+3600,
        'destination':profile['document_endpoint' if stage=='extract' else 'search_endpoint'],'warnings':info['warnings'],
        'index_fields':schema.configure(cfg.index_fields),'source':doc['name'],'size':doc['size'],'pages':info.get('source_pages'),
        'actions':(['Send this file to Azure Document Intelligence prebuilt-layout','Save the returned raw JSON and extracted elements locally'] if stage=='extract' else
            ['Embed the reviewed chunks using the selected embedding engine','Create a new index inside your existing Azure AI Search service','Upload chunks and vectors; activate only after complete verification'] + (['Upload originals, JSON and visual assets to your private Blob container'] if profile.get('publish_assets') else ['Source originals and visual assets remain on this desktop'])),
        'rates':{k:profile.get(k) for k in ['document_price_per_1000_pages','vision_price_per_1000_requests','search_price_per_1000_queries','search_hourly_estimate']}}
    if cfg.connection_id:
        model=s.get('connections',cfg.connection_id,True)
        if stage=='extract' and cfg.describe_visuals: record['actions'].append(f"After Layout extraction, send visual crops and nearby text to {model['provider']} / {model['model']} for optional descriptions")
        if stage=='index' and cfg.strategy=='agentic': record['actions'].append(f"Send source text units to {model['provider']} / {model['model']} to plan chunk boundaries")
    if stage=='index': record['actions'].append('Embedding engine: '+cfg.embedding)
    return s.put('azure_plans',id,record)

def consume_plan(doc,cfg,stage,run):
    profile=resolve(cfg.azure_profile_id); plan=s.get('azure_plans',cfg.azure_plan_id,True)
    with s.LOCK:
        current=s.get('azure_plans',plan['id'],True)
        if current.get('used_by'): raise ValueError('This cloud operation was already started. Review a new plan to run again.')
        if plan['expires']<s.now() or plan['stage']!=stage or plan['document_id']!=doc['id'] or plan['source_hash']!=doc['sha256'] or plan['config_hash']!=s.digest(canonical(cfg.model_dump())) or plan['profile_hash']!=s.digest(public(profile)) or (stage=='index' and plan['extraction_id']!=doc.get('extraction_id')):
            raise ValueError('The cloud plan is stale. Review the current document and settings again.')
        s.patch('azure_plans',plan['id'],used_by=run)
    return profile,plan

def check(run):
    job=s.get('jobs',run)
    if job and job.get('cancel'): raise ValueError('Cancelled. The previous active index and extraction were preserved.')

def service_error(exc):
    if isinstance(exc,httpx.HTTPStatusError):
        code=exc.response.status_code
        return {401:'Azure rejected authentication. Check keys or sign in again.',403:'Azure denied access. Check service roles, firewall and resource permissions.',404:'Azure resource or API route was not found.',409:'This Azure index already exists. It was not overwritten.',429:'Azure quota or rate limit reached. No automatic retry was made.'}.get(code,f'Azure returned HTTP {code}. Check resource settings, API support and document limits.')
    if isinstance(exc,httpx.HTTPError): return 'Azure request failed or timed out. No automatic retry was made.'
    return str(exc)[:600] if isinstance(exc,ValueError) else 'Azure operation failed. Check authentication, resource access and supported settings.'

def request(profile,service,method,path,budget,body=None,content=None,billable=True,units=1,unit='requests',cost=None):
    check(budget.run)
    if billable: budget.check(cost)
    id=s.uid(); start=s.now(); url=profile[service+'_endpoint']+path
    s.put('cloud_calls',id,{'run_id':budget.run,'profile_id':profile['id'],'service':service,'operation':method+' '+path.split('?')[0],
        'endpoint':profile[service+'_endpoint'],'api_version':DI_VERSION if service=='document' else SEARCH_VERSION if service=='search' else '2024-02-01',
        'rate_snapshot':{k:v for k,v in profile.items() if k.endswith('_price_per_1000_pages') or k.endswith('_price_per_1000_requests') or k.endswith('_price_per_1000_queries')},'status':'running','start':start,'units':units if billable else 0,'unit':unit,'cost_usd':cost if billable else 0,'price_status':'estimated' if cost is not None or not billable else 'unpriced'})
    try:
        headers=auth.headers(profile,service,profile.get(service+'_key',''))
        if content is not None: headers['Content-Type']='application/octet-stream'
        with httpx.Client(timeout=httpx.Timeout(90,connect=20),trust_env=False,follow_redirects=False) as client:
            r=client.request(method,url,headers=headers,json=body,content=content)
            r.raise_for_status()
            if r.is_redirect: raise ValueError('Azure returned a redirect. Credentials were not forwarded.')
        s.patch('cloud_calls',id,status='completed',duration=s.now()-start,http_status=r.status_code)
        return r,id
    except Exception as exc:
        message=service_error(exc); s.patch('cloud_calls',id,status='failed',duration=s.now()-start,error=message,cost_usd=None,price_status='unknown after failure')
        raise ValueError(message) from None

def test_profile(id,run):
    cfg=resolve(id); budget=p.Budget(run,4); results={}
    # Resource reads only. No document submission, index creation or model generation.
    for service,path in [('document','/documentintelligence/documentModels/prebuilt-layout?api-version='+DI_VERSION),('search','/servicestats?api-version='+SEARCH_VERSION)]:
        try:
            request(cfg,service,'GET',path,budget,billable=False); results[service]={'ready':True,'check':'Resource read succeeded; data-plane write permission is checked when processing.'}
        except ValueError as exc: results[service]={'ready':False,'error':str(exc)}
    s.patch('azure_profiles',id,last_check={'time':s.now(),'results':results})
    return results

def vision_vectors(texts,assets,profile,budget):
    from .indexing import normalize
    if not profile.get('vision_endpoint'): raise ValueError('Add Azure Vision to this workspace for native image and text embeddings.')
    result=[]
    for text,a in zip(texts,assets):
        packets=[None] if a else [' '.join(text.split()[i:i+60]) for i in range(0,len(text.split()),60)] or ['document']
        values=[]
        for packet in packets:
            path='/computervision/retrieval:vectorize'+('Image' if a else 'Text')+'?api-version=2024-02-01&model-version=2023-04-15'
            rate=profile.get('vision_price_per_1000_requests'); cost=rate/1000 if rate is not None else None
            r,_=request(profile,'vision','POST',path,budget,body={'text':packet} if not a else None,content=s.asset_path(a).read_bytes() if a else None,cost=cost)
            obj=r.json()
            if obj.get('modelVersion','2023-04-15')!='2023-04-15': raise ValueError('Azure Vision returned a different embedding model version.')
            values.append(normalize(obj['vector']))
        result.append(normalize(np.mean(values,axis=0)))
    return result

def fields(dimension,options=None):
    return schema.SYSTEM_FIELDS+schema.fields(options)+[{'name':'content_vector','type':'Collection(Edm.Single)','searchable':True,'retrievable':False,'dimensions':dimension,'vectorSearchProfile':'agentic-rag-vector'}]

def capsule(chunk):return {'chunk_id':chunk['id'],'chunk_hash':s.digest(chunk),'element_ids':chunk['element_ids']}

def publish(index,all_vec,profile,plan,budget):
    name=plan['target']; dimension=index['dimension']; id=index['id']
    candidate={'document_id':index['document_id'],'index_id':id,'profile':public(profile),'search_index':name,'status':'creating','created':s.now(),'run_id':budget.run}
    s.put('azure_publications',id,candidate)
    try:
        index_definition={'name':name,'fields':fields(dimension,index['config'].get('index_fields',{})),'vectorSearch':{'algorithms':[{'name':'agentic-rag-hnsw','kind':'hnsw','hnswParameters':{'metric':'cosine'}}],'profiles':[{'name':'agentic-rag-vector','algorithm':'agentic-rag-hnsw'}]}}
        if index['config'].get('azure_semantic_rerank'):
            names=schema.searchable_fields(index['config'].get('index_fields',{}))
            index_definition['semantic']={'configurations':[{'name':'agentic-rag-semantic','prioritizedFields':{'prioritizedContentFields':[{'fieldName':name} for name in names[:10]]}}]}
        s.event(budget.run,'azure-index','Creating a new index in the existing Search service',index=name)
        request(profile,'search','POST','/indexes?api-version='+SEARCH_VERSION,budget,body=index_definition,cost=0,unit='index creations')
        s.patch('azure_publications',id,status='uploading',created_remote=True)
        documents=[{'@search.action':'upload','id':c['id'],'document_id':index['document_id'],'snapshot_id':id,'source_hash':index['source_hash'],
            'ordinal':n,**schema.values(c),'metadata':json.dumps(capsule(c),ensure_ascii=False),'content_vector':[float(v) for v in vector]} for n,(c,vector) in enumerate(zip(index['chunks'],all_vec))]
        batch=[]; size=0
        def upload(packet):
            check(budget.run)
            r,_=request(profile,'search','POST',f'/indexes/{name}/docs/index?api-version='+SEARCH_VERSION,budget,body={'value':packet},cost=0,units=len(packet),unit='documents uploaded')
            result=r.json().get('value',[])
            if len(result)!=len(packet) or {x.get('key') for x in result}!={x['id'] for x in packet} or any(x.get('status') is not True for x in result): raise ValueError('Azure Search rejected part of the upload. This candidate was not activated; inspect the publication in Azure workspace.')
            s.event(budget.run,'azure-upload',f'Uploaded {len(packet)} chunks',index=name)
        for obj in documents:
            length=len(json.dumps(obj,ensure_ascii=False).encode())
            if length>8_000_000: raise ValueError('A chunk exceeds the Azure upload packet limit. Reduce chunk size.')
            if batch and (len(batch)>=100 or size+length>8_000_000): upload(batch);batch=[];size=0
            batch.append(obj);size+=length
        if batch: upload(batch)
        s.patch('azure_publications',id,status='verifying')
        # Search visibility is eventually consistent. These are bounded read-only polls.
        visible=False
        for _ in range(30):
            check(budget.run)
            r,_=request(profile,'search','POST',f'/indexes/{name}/docs/search?api-version='+SEARCH_VERSION,budget,body={'search':'*','filter':scope(index),'count':True,'top':0},billable=False)
            if r.json().get('@odata.count')==len(documents): visible=True; break
            time.sleep(1)
        if not visible: raise ValueError('Search visibility verification timed out. The previous active index was preserved; this candidate remains in Azure.')
        blobs=publish_assets(index,profile,budget) if profile.get('publish_assets') else []
        s.patch('azure_publications',id,status='verified',chunks=len(documents),blob_assets=blobs)
        return {'backend':'azure-ai-search','azure_profile':public(profile),'search_index':name,'blob_assets':blobs,'search_api_version':SEARCH_VERSION}
    except Exception as exc:
        s.patch('azure_publications',id,status='failed',error=service_error(exc),cleanup_note='Candidate resources are retained. Remove only this Agentic RAG-created index after review.')
        raise ValueError(service_error(exc)) from None

def scope(index): return f"document_id eq '{index['document_id']}' and snapshot_id eq '{index['id']}' and source_hash eq '{index['source_hash']}'"

def query(index,vector,query_text,budget,k=6,page=None,filters=None,search_mode='hybrid'):
    if search_mode not in {'hybrid','keyword','vector'}:raise ValueError('Unsupported retrieval mode.')
    effective=rt.groups(filters)+([{'pages':[int(page)]}] if page is not None else [])
    rt.validate_fields(index,effective)
    profile=resolve(index['azure_profile']['id'],index['azure_profile']); name=index['search_index']
    extra=rt.odata(effective);options=index['config'].get('index_fields',{})
    selected=['id','document_id','snapshot_id','source_hash','metadata']+schema.retrievable_fields(options)
    # Legacy indexes have the original small schema and a full chunk metadata payload.
    if index.get('retrieval_schema_version',0)<rt.VERSION:selected=['id','document_id','snapshot_id','source_hash','content','title','pages','metadata']
    body={'filter':scope(index)+(' and ('+extra+')' if extra else ''),'select':','.join(selected),'top':k}
    if page is not None:
        body.update(search='*')
        if schema.configure(options)['ordinal']['sortable']:body['orderby']='ordinal asc'
    else:
        if search_mode!='vector':body.update(search=query_text,queryType='simple',searchFields=','.join(schema.searchable_fields(options)))
        if search_mode!='keyword':body.update(vectorQueries=[{'kind':'vector','vector':[float(v) for v in vector],'fields':'content_vector','k':max(k,50)}],vectorFilterMode='preFilter')
        if index['config'].get('azure_semantic_rerank') and search_mode!='vector':body.update(queryType='semantic',semanticConfiguration='agentic-rag-semantic')
    rate=profile.get('search_price_per_1000_queries'); cost=rate/1000 if rate is not None else None
    r,_=request(profile,'search','POST',f'/indexes/{name}/docs/search?api-version='+SEARCH_VERSION,budget,body=body,cost=cost,unit='queries')
    known={c['id']:c for c in index['chunks']};eligible={c['id']:c for c in rt.indexed_chunks(index)}; result=[]
    for row in r.json().get('value',[]):
        c=known.get(row.get('id'));meta=json.loads(row.get('metadata','{}'));expected=capsule(c) if c and index.get('retrieval_schema_version',0)>=rt.VERSION else c
        if not c or any(row.get(field)!=index[field if field!='snapshot_id' else 'id'] for field in ('document_id','snapshot_id','source_hash')) or s.digest(meta)!=s.digest(expected) or row.get('content')!=c['text']:
            raise ValueError('Azure returned evidence that differs from this immutable index snapshot. Rebuild or restore the index before answering.')
        if not rt.matches(eligible[c['id']],effective):raise ValueError('Azure returned evidence outside the requested metadata filters.')
        result.append({**eligible[c['id']],'score':row.get('@search.score',0),'rank':len(result)+1,'retrieval_backend':'azure-ai-search','search_mode':search_mode,'reranker_score':row.get('@search.rerankerScore')})
    s.event(budget.run,'retrieval','Azure Search page inspection' if page is not None else 'Azure filtered '+search_mode+' retrieval',query=query_text,index_id=index['id'],search_index=name,filters=effective,search_mode=search_mode,rank_fusion='RRF' if search_mode=='hybrid' and page is None else None,hits=[{'id':c['id'],'score':c['score']} for c in result])
    return result

def publish_assets(index,profile,budget):
    from azure.storage.blob import BlobServiceClient
    check(budget.run)
    client=BlobServiceClient(account_url=profile['blob_endpoint'],credential=profile['blob_key'] if profile.get('auth_mode','api-key')=='api-key' else auth.credential(profile),retry_total=0)
    container=client.get_container_client(profile['blob_container']); result=[]
    doc=s.get('documents',index['document_id'],True); extraction=s.get('extractions',index['extraction_id'],True)
    paths={doc['path'],*[e['asset'] for e in extraction['elements'] if e.get('asset')]}
    if extraction.get('raw_json_asset'): paths.add(extraction['raw_json_asset'])
    try:
        # The account/container must already exist; Agentic RAG never provisions a storage account.
        container.get_container_properties()
        for relative in sorted(paths):
            check(budget.run); budget.check(None)
            name=f"agentic-rag/{doc['id']}/{index['id']}/{s.digest(relative)[:12]}-{Path(relative).name}"
            start=s.now(); call_id=s.uid()
            s.put('cloud_calls',call_id,{'run_id':budget.run,'profile_id':profile['id'],'service':'blob','operation':'upload private asset','endpoint':profile['blob_endpoint'],'rate_snapshot':{k:v for k,v in profile.items() if k.endswith('_price_per_1000_pages') or k.endswith('_price_per_1000_requests') or k.endswith('_price_per_1000_queries')},'status':'running','start':start,'units':1,'unit':'objects uploaded','cost_usd':None,'price_status':'unpriced'})
            try:
                with s.asset_path(relative).open('rb') as f: container.upload_blob(name=name,data=f,overwrite=False)
                s.patch('cloud_calls',call_id,status='completed',duration=s.now()-start)
            except Exception:
                s.patch('cloud_calls',call_id,status='failed',duration=s.now()-start,error='Private Blob upload failed. Check account access, container and permissions.')
                raise
            result.append({'local_asset':relative,'blob_name':name,'container':profile['blob_container'],'endpoint':profile['blob_endpoint']})
        return result
    except Exception: raise ValueError('Private Blob upload failed. Confirm that the container exists and the identity has Blob data access. Earlier uploaded objects are retained.') from None
    finally: client.close()
