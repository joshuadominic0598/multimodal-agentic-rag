import io,json,pytest,httpx
from PIL import Image
from app import store as s,providers as p
from app.schemas import Connection
from app.main import validate_url

def profile(provider='gemini',**extra):
    return {'id':'test','name':'test','key':'dummy-key','provider':provider,'model':'model-test','embedding_model':'embed-test','endpoint':'https://unit.openai.azure.com','vision':True,'max_output':1000,'input_price':None,'output_price':None,'cached_price':None,'embedding_price':None,'image_price':None,**extra}

def test_keys_encrypted_and_write_only():
    c=p.save(Connection(name='Test',provider='gemini',model='test',api_key='private-test-key').model_dump())
    assert 'private-test-key' not in json.dumps(c)
    raw=s.get('connections',c['id']);assert raw['secret']!='private-test-key'
    assert p.resolve(c['id'])['key']=='private-test-key'
    assert (s.DATA/'.secret-key').stat().st_mode&0o777==0o600

def test_azure_endpoint_restrictions():
    with pytest.raises(ValueError,match='Azure HTTPS'):p.save(Connection(name='bad',provider='azure',model='m',api_key='k',endpoint='http://127.0.0.1').model_dump())

@pytest.mark.parametrize('url',['http://127.0.0.1/secret','http://169.254.169.254/latest/meta-data','file:///etc/passwd','http://user:pass@example.org'])
def test_web_import_blocks_internal_urls(url):
    with pytest.raises(ValueError):validate_url(url)

def test_paths_cannot_escape_storage():
    with pytest.raises(ValueError):s.asset_path('../../etc/passwd')

def test_api_origin_and_header(client):
    assert client.post('/api/connections',headers={'Origin':'http://evil.invalid'},json={}).status_code==403
    from fastapi.testclient import TestClient
    from app.main import app
    assert TestClient(app).post('/api/connections',json={}).status_code==403
    assert client.get('/api/state').status_code==200

def test_original_html_is_downloaded(client):
    from app.main import register
    d=register('source.html',b'<script>alert(1)</script>')
    r=client.get('/api/files/'+d['path'])
    assert 'attachment' in r.headers['content-disposition']
    assert r.headers['x-content-type-options']=='nosniff'

def test_call_limit_and_unpriced_budget():
    b=p.Budget('limit',1);b.check()
    with pytest.raises(ValueError,match='call limit'):b.check()
    with pytest.raises(ValueError,match='pricing'):p.Budget('unpriced',1,.5).check(None)

def test_visual_dollar_cap_is_not_guessed():
    with pytest.raises(ValueError,match='Visual input cost'):p.request(profile(),p.Budget('visual',2,.01),'generation','m','https://example.org',{},visual_count=1)

@pytest.mark.parametrize('provider',['openai','azure','gemini'])
def test_native_provider_payload_and_usage(monkeypatch,provider):
    seen=[];c=profile(provider,input_price=1,output_price=2)
    def handler(request):
        seen.append(request);body=json.loads(request.content)
        if provider=='gemini':
            assert 'systemInstruction' in body and body['generationConfig']['responseMimeType']=='application/json'
            return httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':'{"ready":true}'}]}}],'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':20,'thoughtsTokenCount':5}})
        assert body['store'] is False and body['text']['format']['type']=='json_object'
        assert request.url.path.endswith('/responses')
        return httpx.Response(200,json={'output':[{'content':[{'type':'output_text','text':'{"ready":true}'}]}],'usage':{'input_tokens':100,'output_tokens':25}})
    real=httpx.Client
    monkeypatch.setattr(p.httpx,'Client',lambda **kwargs:real(transport=httpx.MockTransport(handler)))
    assert p.generate(c,p.Budget('native-'+provider),'system','JSON please',json_mode=True)=={'ready':True}
    rec=next(x for x in s.rows('calls') if x['run_id']=='native-'+provider)
    assert rec['input_tokens']==100 and rec['output_tokens']==25
    assert rec['cost_usd']==pytest.approx(.00015)
    assert c['key'] not in json.dumps(rec)
    assert ('x-goog-api-key' in seen[0].headers) if provider=='gemini' else ('api-key' in seen[0].headers) if provider=='azure' else ('authorization' in seen[0].headers)

def test_multimodal_embedding_sends_pixels(monkeypatch):
    b=io.BytesIO();Image.new('RGB',(10,10),'red').save(b,format='PNG');a=s.DATA/'assets'/'pixel.png';a.write_bytes(b.getvalue())
    captured=[]
    def fake(c,budget,op,model,url,body,**kw):
        captured.append(body);return {'embedding':{'values':[.1,.2]}},'embedding-call'
    monkeypatch.setattr(p,'request',fake)
    assert p.embed(profile(),p.Budget('embed'),['red square'],[a],True)==[[.1,.2]]
    assert captured[0]['content']['parts'][1]['inlineData']['data']

def test_quota_error_has_no_key_or_url(monkeypatch):
    real=httpx.Client
    monkeypatch.setattr(p.httpx,'Client',lambda **kwargs:real(transport=httpx.MockTransport(lambda req:httpx.Response(429,json={'error':{'message':'sensitive dummy-key'}}))))
    with pytest.raises(ValueError,match='No retry'):p.generate(profile(),p.Budget('quota'),'system','hello')
    rec=next(x for x in s.rows('calls') if x['run_id']=='quota')
    assert rec['status']=='failed' and rec['cost_usd'] is None and 'dummy-key' not in json.dumps(rec)

def test_http_module_import_does_not_interrupt_running_jobs():
    import importlib,app.main
    s.put('jobs','import-regression',{'kind':'test','status':'running'})
    importlib.reload(app.main)
    assert s.get('jobs','import-regression')['status']=='running'
    s.delete('jobs','import-regression')

def test_context_budget_rejects_oversize_before_api_call():
    c=profile(context_chars=100)
    with pytest.raises(ValueError,match='character budget'):p.generate(c,p.Budget('too-long'),'system','x'*101)

def test_connection_verification_survives_price_edit_but_not_model_change():
    config=Connection(name='Verified',provider='gemini',model='model-a',api_key='private-test',vision=True).model_dump()
    c=p.save(config);s.patch('connections',c['id'],tested_text=True,tested_vision=True)
    config['api_key']='';config['input_price']=1
    edited=p.save(config,c['id']);assert edited['tested_text'] and edited['tested_vision']
    config['model']='model-b';changed=p.save(config,c['id']);assert not changed['tested_text'] and not changed['tested_vision']
