"""Explicit provider adapters. No paid fallback or automatic retries."""
from __future__ import annotations
import base64, json, mimetypes, os, re, threading, time
from urllib.parse import urlparse
from pathlib import Path
import httpx
from cryptography.fernet import Fernet
from . import store as s
from .model_catalog import CATALOG, defaults

class ProviderError(ValueError): pass

SECRET_LOCK = threading.RLock()
def cipher():
    p=s.DATA/'.secret-key'
    with SECRET_LOCK:
        if not p.exists():
            fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as f: f.write(Fernet.generate_key())
    return Fernet(p.read_bytes())

def public(c): return {k:v for k,v in c.items() if k not in {'secret','key','api_key'}} | {'has_key':bool(c.get('secret'))}
def resolve(id):
    c=s.get('connections',id,True)
    c['key']=cipher().decrypt(c['secret'].encode()).decode() if c.get('secret') else ''
    return c

def prepare(data,id=None):
    data=dict(data); key=data.pop('api_key','').strip()
    model=data['model'].strip();data['model']=model
    pattern=r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}' if data['provider'] in {'groq','ollama','openai'} else r'[A-Za-z0-9][A-Za-z0-9._:-]{0,99}'
    if not re.fullmatch(pattern,model) or '..' in model: raise ValueError('Enter a valid model or deployment ID, without URL parameters.')
    if data['provider']=='azure':
        u=urlparse(data['endpoint'])
        if u.scheme!='https' or not u.hostname or not u.hostname.endswith(('.openai.azure.com','.cognitiveservices.azure.com','.services.ai.azure.com')) or u.query or u.fragment or u.username is not None or u.password is not None or u.port not in {None,443} or u.path not in {'','/','/openai/v1','/openai/v1/'}:
            raise ValueError('Use your Azure HTTPS resource endpoint.')
        data['endpoint']=data['endpoint'].rstrip('/')
    elif data['provider']=='ollama':
        from .local_embeddings import endpoint
        data['endpoint']=endpoint(data.get('endpoint') or 'http://127.0.0.1:11434')
        if ':cloud' in model.lower(): raise ValueError('Select an installed local Ollama model. Cloud-backed models are not supported by the local connection.')
        if key: raise ValueError('Local Ollama does not need an API key. Remove the key before saving.')
        data['account_tier']='local';data['free_tier']=False
    else: data['endpoint']=''
    old=s.get('connections',id) if id else None
    if data['provider']!='azure' and data.get('auth_mode','api-key')!='api-key': raise ValueError('Microsoft authentication is available for Azure connections only.')
    if data['provider']=='azure':
        from .azure_auth import identity
        identity(data)
    same_provider=bool(old) and old['provider']==data['provider']
    if data['provider']!='ollama' and not key and not (same_provider and old.get('secret')) and data.get('auth_mode','api-key')=='api-key': raise ValueError('Enter an API key for this provider.')
    data['secret']='' if data['provider']=='ollama' else cipher().encrypt(key.encode()).decode() if key else old.get('secret','') if same_provider else ''
    tier=data.get('account_tier','unknown')
    if data['provider']!='ollama' and tier=='local':raise ValueError('The local account tier is only for Ollama.')
    if tier=='unknown' and data.get('free_tier'):tier='free'
    data['account_tier']=tier;data['free_tier']=tier=='free'
    # Capability must be tested for this model, not inherited from a previous model.
    same=bool(old) and not key and all(old.get(k,'')==data.get(k,'') for k in ['provider','model','endpoint','auth_mode','tenant_id','client_id'])
    data['tested_vision']=bool(data.get('vision') and same and old.get('tested_vision',False))
    data['tested_text']=bool(same and old.get('tested_text',False))
    if same and old.get('tested_at'): data['tested_at']=old['tested_at']
    if same and old.get('image_model','')==data.get('image_model',''):
        for key in ['tested_image_generation','image_generation_notice']:
            if key in old: data[key]=old[key]
    return data

def save(data,id=None):
    return public(s.put('connections',id or s.uid(),prepare(data,id)))

def bootstrap():
    from .schemas import Connection
    if not any(x['provider']=='ollama' for x in s.rows('connections')):
        save(Connection(**defaults('ollama')).model_dump())
    p=s.DATA/'.gemini-bootstrap'
    if p.exists():
        from .schemas import Connection
        c=save(Connection(name='Gemini · free tier development',provider='gemini',model='gemini-3.1-flash-lite',api_key=p.read_text(),embedding_model='gemini-embedding-001',vision=True,free_tier=True).model_dump())
        s.patch('settings','main',active_connection=c['id']); p.unlink()

def safe_error(exc):
    if isinstance(exc,httpx.HTTPStatusError):
        code=exc.response.status_code
        return {429:'Provider quota or rate limit reached. No retry or paid fallback was made.',401:'Provider rejected the API key.',403:'Provider denied access. Check key permissions, model access and project restrictions.',404:'Model/deployment not available for this connection.'}.get(code,f'Provider returned HTTP {code}. Check model, quota and supported features.')
    if isinstance(exc,httpx.TimeoutException): return 'Provider timed out. No automatic retry was made.'
    if isinstance(exc,httpx.HTTPError): return 'Could not reach provider. Check your connection.'
    return str(exc)[:600]

class Budget:
    def __init__(self,run,max_calls=80,usd=None): self.run=run; self.limit=max_calls; self.usd=usd; self.calls=0
    def check(self,estimated=None):
        job=s.get('jobs',self.run)
        if job and job.get('cancel'): raise ProviderError('Cancelled by user.')
        if self.calls>=self.limit: raise ProviderError('Model call limit reached. Increase the limit to continue in a new run.')
        records=[x for kind in ('calls','cloud_calls') for x in s.rows(kind) if x['run_id']==self.run]
        if self.usd is not None:
            if estimated is None: raise ProviderError('A dollar cap requires pricing for this operation. Set rates or remove the cap; unpriced calls cannot enforce a dollar cap.')
            if any(r.get('cost_usd') is None for r in records) or sum(r['cost_usd'] for r in records)+estimated>self.usd:
                raise ProviderError('Estimated run budget would be exceeded.')
        self.calls+=1

def rate_estimate(c,op,text,max_output):
    if c['provider']=='ollama':return 0
    if op=='embedding': return len(text)/3 * c['embedding_price']/1e6 if c.get('embedding_price') is not None else None
    if op=='image': return c.get('image_price')
    if op=='transcription': return None
    if c.get('input_price') is None or c.get('output_price') is None: return None
    return len(text)/3*c['input_price']/1e6+max_output*c['output_price']/1e6

def auth_headers(c):
    if c['provider']=='ollama':return {}
    if c['provider']=='azure':
        from .azure_auth import headers
        if c.get('auth_mode','api-key')=='api-key': return {'api-key':c['key']}
        return headers(c,'document')
    return {'x-goog-api-key':c['key']} if c['provider']=='gemini' else {'Authorization':'Bearer '+c['key']}

def request(c,budget,op,model,url,body=None,files=None,data=None,preview='',visual_count=0):
    max_output=c.get('max_output',3000)
    estimate=rate_estimate(c,op,preview,max_output)
    # Image input tokenization is model-specific. Do not claim a hard cap for unknown visual usage.
    if visual_count and budget.usd is not None and c['provider']!='ollama': raise ProviderError('Visual input cost cannot be bounded with text rates. Use the call limit, or remove the dollar cap for visual calls.')
    budget.check(estimate)
    id=s.uid(); start=time.time()
    rec={'run_id':budget.run,'connection_id':c['id'],'provider':c['provider'],'model':model,'operation':op,'start':start,'status':'running','input_preview':preview[:6000],'visual_inputs':visual_count,'input_tokens':None,'output_tokens':None,'cached_tokens':None,'cost_usd':None,'price_status':'unpriced','prices':{k:c.get(k) for k in ['input_price','output_price','cached_price','embedding_price','image_price']}}
    s.put('calls',id,rec); s.event(budget.run,op,f'{c["provider"]} / {model}',call_id=id)
    try:
        headers=auth_headers(c)
        with httpx.Client(timeout=httpx.Timeout(180,connect=20),trust_env=False) as client:
            r=client.post(url,headers=headers,json=body,files=files,data=data)
            r.raise_for_status(); obj=r.json()
        usage=obj.get('usage',obj.get('usageMetadata',{})) or {}
        if c['provider']=='ollama':usage={'input_tokens':obj.get('prompt_eval_count'),'output_tokens':obj.get('eval_count'),'total_duration_ns':obj.get('total_duration'),'load_duration_ns':obj.get('load_duration')}
        inp=usage.get('input_tokens',usage.get('prompt_tokens',usage.get('promptTokenCount')))
        out=usage.get('output_tokens',usage.get('completion_tokens',usage.get('candidatesTokenCount')))
        thought=usage.get('thoughtsTokenCount',0) or 0
        if out is not None: out+=thought
        cached=usage.get('input_tokens_details',usage.get('prompt_tokens_details',{})).get('cached_tokens',usage.get('cachedContentTokenCount',0)) or 0
        cost=None
        if op=='embedding' and inp is None: inp=usage.get('total_tokens',obj.get('tokenCount'))
        if op=='embedding' and inp is not None and c.get('embedding_price') is not None: cost=inp*c['embedding_price']/1e6
        elif op=='image' and c.get('image_price') is not None: cost=c['image_price']
        elif op not in ('embedding','image','transcription') and inp is not None and out is not None and c.get('input_price') is not None and c.get('output_price') is not None:
            cost=((inp-cached)*c['input_price']+cached*(c.get('cached_price') if c.get('cached_price') is not None else c['input_price'])+out*c['output_price'])/1e6
        if c['provider']=='ollama':cost=0
        rate_limits={k:r.headers[k] for k in ['retry-after','x-ratelimit-limit-requests','x-ratelimit-limit-tokens','x-ratelimit-remaining-requests','x-ratelimit-remaining-tokens','x-ratelimit-reset-requests','x-ratelimit-reset-tokens'] if k in r.headers}
        s.patch('calls',id,status='completed',duration=time.time()-start,input_tokens=inp,output_tokens=out,cached_tokens=cached,cost_usd=cost,price_status='local API fees only' if c['provider']=='ollama' else 'estimated' if cost is not None else 'unpriced',usage=usage,rate_limits=rate_limits,api_fees_only=c['provider']=='ollama')
        return obj,id
    except Exception as exc:
        message=safe_error(exc)
        rate_limits={k:exc.response.headers[k] for k in ['retry-after','x-ratelimit-remaining-requests','x-ratelimit-remaining-tokens','x-ratelimit-reset-requests','x-ratelimit-reset-tokens'] if k in exc.response.headers} if isinstance(exc,httpx.HTTPStatusError) else {}
        s.patch('calls',id,status='failed',duration=time.time()-start,error=message,rate_limits=rate_limits)
        raise ProviderError(message) from None

def inline(path):
    p=Path(path)
    return {'inlineData':{'mimeType':mimetypes.guess_type(p.name)[0] or 'image/png','data':base64.b64encode(p.read_bytes()).decode()}}

def base(c):
    if c['provider']=='openai': return 'https://api.openai.com/v1'
    if c['provider']=='groq':return 'https://api.groq.com/openai/v1'
    if c['provider']=='ollama':
        from .local_embeddings import endpoint
        return endpoint(c.get('endpoint') or 'http://127.0.0.1:11434')
    u=c['endpoint'].rstrip('/')
    return u if u.endswith('/openai/v1') else u+'/openai/v1'

def ollama_info(c,model):
    try:
        with httpx.Client(timeout=25,trust_env=False,follow_redirects=False) as client:
            r=client.post(base(c)+'/api/show',json={'model':model});r.raise_for_status();info=r.json()
        if info.get('remote_host') or info.get('remote_model') or ':cloud' in model.lower():raise ProviderError('Select an installed local Ollama model. Cloud-backed models are excluded.')
        return info
    except ProviderError:raise
    except httpx.HTTPError as exc:raise ProviderError('Ollama model unavailable. Keep Ollama running and install the exact selected model. '+safe_error(exc)) from None

def list_models(c):
    """Read model inventory without generating content or persisting credentials."""
    provider=c['provider'];models=[];token=None
    url='https://generativelanguage.googleapis.com/v1beta/models' if provider=='gemini' else base(c)+('/api/tags' if provider=='ollama' else '/models')
    try:
        with httpx.Client(timeout=25,trust_env=False,follow_redirects=False) as client:
            for _ in range(10):
                params={'pageSize':1000,**({'pageToken':token} if token else {})} if provider=='gemini' else {}
                r=client.get(url,headers=auth_headers(c),params=params);r.raise_for_status();obj=r.json()
                if provider=='gemini':
                    models.extend({'id':x['name'].removeprefix('models/'),'methods':x.get('supportedGenerationMethods',[]),'selectable':'generateContent' in x.get('supportedGenerationMethods',[])} for x in obj.get('models',[]))
                elif provider=='ollama':
                    for x in obj.get('models',[]):
                        if x.get('remote_host') or x.get('remote_model') or ':cloud' in x['name'].lower():continue
                        caps=x.get('capabilities',[]);embedding_only=('embedding' in caps and 'completion' not in caps) or ('embedding' in x['name'].lower() and not caps)
                        models.append({'id':x['name'],'installed':True,'size':x.get('size'),'capabilities':caps,'selectable':not embedding_only})
                else:models.extend({'id':x['id'],'selectable':True} for x in obj.get('data',[]) if x.get('active',True))
                token=obj.get('nextPageToken') if provider=='gemini' else None
                if not token:break
        return {'models':sorted(models,key=lambda x:x['id']),'partial':bool(token),'provider':provider,
                'notice':'Installed local inventory; embedding-only models are reserved for indexing and excluded from the chat picker.' if provider=='ollama' else 'Provider catalog visibility does not guarantee inference access, modality support or remaining quota. Azure catalog IDs may differ from deployment names.' if provider=='azure' else 'Provider catalog visibility does not guarantee inference access, modality support or remaining quota.'}
    except httpx.HTTPError as exc:raise ProviderError(safe_error(exc)) from None
    except (ValueError,KeyError,TypeError):raise ProviderError('Provider returned an unreadable model inventory.') from None

def generate(c,budget,system,prompt,images=(),json_mode=False,model=None,image_output=False):
    if len(system)+len(prompt)>c.get('context_chars',200000): raise ProviderError('Request exceeds the configured character budget. Increase the connection context budget or narrow the question.')
    if images and not c.get('vision'): raise ProviderError('This connection has vision disabled. Choose description mode or a vision-capable connection.')
    model=model or c['model']
    if image_output and c['provider'] in {'groq','ollama'}:raise ProviderError('Image generation is not supported by this connection. Choose an eligible Gemini, OpenAI or Azure image-generation connection.')
    if c['provider']=='gemini':
        parts=[{'text':prompt}]+[inline(p) for p in images]
        config={'maxOutputTokens':c['max_output']}
        if json_mode: config['responseMimeType']='application/json'
        if image_output: config['responseModalities']=['TEXT','IMAGE']
        body={'systemInstruction':{'parts':[{'text':system}]},'contents':[{'role':'user','parts':parts}],'generationConfig':config}
        obj,id=request(c,budget,'image' if image_output else 'generation',model,f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',body,preview=system+'\n'+prompt,visual_count=len(images))
        parts=obj.get('candidates',[{}])[0].get('content',{}).get('parts',[])
        text='\n'.join(p['text'] for p in parts if p.get('text') and not p.get('thought'))
        generated=[p.get('inlineData',p.get('inline_data')) for p in parts if p.get('inlineData') or p.get('inline_data')]
    elif c['provider']=='groq':
        content=[{'type':'text','text':prompt}]+[{'type':'image_url','image_url':{'url':'data:'+inline(p)['inlineData']['mimeType']+';base64,'+inline(p)['inlineData']['data']}} for p in images]
        body={'model':model,'messages':[{'role':'system','content':system},{'role':'user','content':content if images else prompt}],'max_completion_tokens':c['max_output'],'stream':False}
        if json_mode:body['response_format']={'type':'json_object'}
        obj,id=request(c,budget,'generation',model,base(c)+'/chat/completions',body,preview=system+'\n'+prompt,visual_count=len(images))
        text=obj.get('choices',[{}])[0].get('message',{}).get('content') or '';generated=[]
    elif c['provider']=='ollama':
        info=ollama_info(c,model)
        if 'completion' not in info.get('capabilities',[]):raise ProviderError('Choose an installed Ollama chat model, not an embedding-only model.')
        if images and 'vision' not in info.get('capabilities',[]):raise ProviderError('This installed Ollama model does not accept images. Use description mode or a vision model.')
        tokens=c.get('ollama_context_tokens',16384)
        maximum=max([v for k,v in info.get('model_info',{}).items() if k.endswith('.context_length') and isinstance(v,int)] or [tokens])
        if tokens>maximum:raise ProviderError(f'The installed model declares a {maximum:,}-token context. Reduce the Ollama runtime context setting.')
        # UTF-8 bytes conservatively bound text tokens; reserve template and output space.
        if len((system+prompt).encode('utf-8'))+c['max_output']+1024>tokens:raise ProviderError('The request exceeds the conservative local token budget. Reduce text context/output or increase the Ollama runtime context. No text was silently truncated.')
        user={'role':'user','content':prompt}
        if images:user['images']=[inline(p)['inlineData']['data'] for p in images]
        body={'model':model,'messages':[{'role':'system','content':system},user],'stream':False,'options':{'num_ctx':tokens,'num_predict':c['max_output']}}
        if 'thinking' in info.get('capabilities',[]):body['think']=False
        if json_mode:body['format']='json'
        obj,id=request(c,budget,'generation',model,base(c)+'/api/chat',body,preview=system+'\n'+prompt,visual_count=len(images))
        text=obj.get('message',{}).get('content') or '';generated=[]
    else:
        content=[{'type':'input_text','text':prompt}]+[{'type':'input_image','image_url':'data:'+inline(p)['inlineData']['mimeType']+';base64,'+inline(p)['inlineData']['data']} for p in images]
        body={'model':model,'instructions':system,'input':[{'role':'user','content':content}],'max_output_tokens':c['max_output'],'store':False}
        if json_mode: body['text']={'format':{'type':'json_object'}}
        if image_output:
            body['tools']=[{'type':'image_generation'}]
            if c['provider']=='azure': raise ProviderError('For Azure image generation use a separate image deployment through the image endpoint.')
        obj,id=request(c,budget,'image' if image_output else 'generation',model,base(c)+'/responses',body,preview=system+'\n'+prompt,visual_count=len(images))
        text='\n'.join(p.get('text','') for item in obj.get('output',[]) for p in item.get('content',[]) if p.get('type')=='output_text')
        generated=[{'data':x['result'],'mimeType':'image/png'} for x in obj.get('output',[]) if x.get('type')=='image_generation_call' and x.get('result')]
    s.patch('calls',id,output_preview=text[:8000])
    if not text and not generated: raise ProviderError('Provider returned no usable content. Review output limit and model safety settings.')
    if json_mode:
        text=text.strip()
        if text.startswith('```'): text='\n'.join(text.splitlines()[1:-1])
        try: return json.loads(text)
        except ValueError: raise ProviderError('Provider returned invalid JSON. No unvalidated plan was executed.') from None
    return text,generated

def embed(c,budget,texts,images=None,multimodal=False):
    if c['provider'] in {'groq','ollama'}:raise ProviderError('Choose a separate embedding engine: local EmbeddingGemma / Qwen3 Embedding, CLIP, or a supported cloud embedding connection. This chat connection is not a provider embedding adapter.')
    images=images or [None]*len(texts)
    model='gemini-embedding-2' if multimodal else c['embedding_model']
    if c['provider']=='gemini':
        result=[]
        for text,img in zip(texts,images):
            parts=[{'text':text or 'Document visual'}]
            if img: parts.append(inline(img))
            body={'content':{'parts':parts},'outputDimensionality':768}
            if model=='gemini-embedding-001': body['taskType']='SEMANTIC_SIMILARITY'
            obj,_=request(c,budget,'embedding',model,f'https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent',body,preview=text,visual_count=int(bool(img)))
            result.append(obj['embedding']['values'])
        return result
    if multimodal: raise ProviderError('OpenAI text embeddings cannot embed images. Choose local CLIP or a Gemini multimodal embedding connection.')
    obj,_=request(c,budget,'embedding',model,base(c)+'/embeddings',{'model':model,'input':texts,'encoding_format':'float'},preview='\n'.join(texts))
    return [x['embedding'] for x in sorted(obj['data'],key=lambda x:x['index'])]

def transcribe(c,budget,path):
    if c['provider']=='ollama':raise ProviderError('Use local Whisper for audio/video transcription. The Ollama chat connection does not transcribe audio.')
    if c['provider']=='gemini':
        parts=[{'text':'Return JSON {"segments":[{"start":0.0,"end":5.0,"text":"exact spoken words"}]}. Transcribe all speech in the original language. Times are seconds. Do not summarize.'},inline(path)]
        model=c['model']; body={'contents':[{'parts':parts}],'generationConfig':{'responseMimeType':'application/json','maxOutputTokens':c['max_output']}}
        obj,id=request(c,budget,'transcription',model,f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',body,preview='Transcribe audio with timestamps')
        text=obj['candidates'][0]['content']['parts'][0]['text']; s.patch('calls',id,output_preview=text[:6000]); return json.loads(text)['segments']
    model='whisper-1' if c['provider']=='openai' else 'whisper-large-v3' if c['provider']=='groq' else c.get('transcription_model','whisper')
    with open(path,'rb') as f:
        obj,_=request(c,budget,'transcription',model,base(c)+'/audio/transcriptions',files={'file':(Path(path).name,f,'audio/wav')},data={'model':model,'response_format':'verbose_json','timestamp_granularities[]':'segment'},preview='Transcribe audio with timestamps')
    return obj['segments']
