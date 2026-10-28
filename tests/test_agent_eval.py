import json,pytest
from app import store as s,providers as p
from app.agent import answer
from app.evaluation import parse_dataset,metrics,run_evaluation

def test_always_clarifies_without_model_call(indexed):
    doc,index=indexed;r=answer({'document_id':doc['id'],'message':'Explain the source.'},'clarify')
    assert r['status']=='clarification' and not r['sources']
    assert not [x for x in s.rows('calls') if x['run_id']=='clarify']

def test_retrieval_preview_is_labeled(indexed):
    doc,index=indexed;r=answer({'document_id':doc['id'],'message':'solar','preview':True},'preview')
    assert r['status']=='preview' and 'not a generated answer' in r['answer']
    assert r['sources'] and r['sources'][0]['elements']

def test_conversation_scope_isolation(indexed):
    doc,index=indexed
    s.put('sessions','other',{'document_id':'other-doc','index_id':index['id'],'messages':[]})
    with pytest.raises(ValueError,match='different document'):answer({'document_id':doc['id'],'session_id':'other','message':'hello'},'isolation')

def test_agent_refines_and_rejects_fake_citations(indexed,monkeypatch):
    doc,index=indexed;c={'id':'test','model':'test','provider':'gemini','vision':False,'max_output':1000,'context_chars':20000}
    outputs=iter([{'queries':['solar']},{'sufficient':False,'next_query':'batteries','missing':'need storage'},{'sufficient':True},('Invented [c99999]',[])])
    monkeypatch.setattr(p,'generate',lambda *a,**k:next(outputs))
    with pytest.raises(ValueError,match='outside its evidence'):answer({'document_id':doc['id'],'message':'Explain energy storage','clarified':True},'reject',c)
    searches=[e for e in s.rows('events') if e['run_id']=='reject' and e['stage']=='retrieval']
    assert len(searches)==2

def test_grounded_answer_and_memory(indexed,monkeypatch):
    doc,index=indexed;target=next(x['id'] for x in index['chunks'] if 'convert' in x['text'])
    outputs=iter([{'queries':['solar']},{'sufficient':True},('Panels convert sunlight to electricity ['+target+'].',[])])
    monkeypatch.setattr(p,'generate',lambda *a,**k:next(outputs))
    c={'id':'test','model':'test','provider':'gemini','vision':False,'max_output':1000,'context_chars':20000}
    r=answer({'document_id':doc['id'],'message':'What do panels do?','clarified':True},'grounded',c)
    assert r['citations']==[target] and r['status']=='completed'
    assert s.get('memory','summary-'+r['session_id'])['type']=='conversation_scope'

def test_dataset_unknown_chunk_rejected(indexed):
    doc,index=indexed;data=[{'question':'Solar?','reference_answer':'Panels.','expected_chunk_ids':['c99999']}]
    with pytest.raises(ValueError,match='must exist'):parse_dataset(json.dumps(data).encode(),'gold.json',doc['id'],index['id'])

def test_duplicate_csv_header_rejected(indexed):
    doc,index=indexed
    with pytest.raises(ValueError,match='duplicate'):parse_dataset(b'question,question\na,b','gold.csv',doc['id'],index['id'])

def test_unverified_reference_not_scored_as_retrieval_truth():
    result={'answer':'Solar electricity','status':'completed','sources':[{'id':'c00001'}],'citations':['c00001']}
    case={'reference_answer':'Solar electricity','expected_chunk_ids':['c00001'],'reference_status':'unverified','should_clarify':False}
    score=metrics(result,case);assert score['token_f1']==1 and score['context_recall'] is None
    case['reference_status']='verified';assert metrics(result,case)['context_recall']==1

def test_eval_pins_models_prompt_and_keeps_failures_separate(indexed,monkeypatch):
    import app.evaluation as ev
    doc,index=indexed;dataset=parse_dataset(json.dumps([{'question':'Solar?','reference_answer':'Electricity.'}]).encode(),'gold.json',doc['id'],index['id'])
    profiles={'a':{'id':'a','model':'A','name':'A','secret':'hidden','key':'never-return'},'b':{'id':'b','model':'B','name':'B','secret':'hidden','key':'never-return'}}
    monkeypatch.setattr(p,'resolve',lambda id:profiles[id])
    def fake(q,run,c,guidance,memory):
        assert memory is False
        if c['id']=='b':raise ValueError('quota')
        return {'answer':'Electricity.','status':'completed','sources':[],'citations':[],'duration':.1}
    monkeypatch.setattr(ev,'answer',fake)
    r=run_evaluation(dataset['id'],['a','b'],'eval-run')
    saved=s.get('evaluations','eval-run')
    assert len(saved['results'])==2 and saved['summary'][1]['failed']==1
    assert 'never-return' not in json.dumps(saved) and 'hidden' not in json.dumps(saved)
    assert saved['prompt_hash'] and saved['index_fingerprint']==index['fingerprint']

def test_explicit_page_scope_reads_beyond_similarity_sample(indexed,monkeypatch):
    doc,index=indexed
    template=index['chunks'][0]
    chunks=[{**template,'id':f'c{i:05d}','pages':[5],'text':f'Strategy {i}.'} for i in range(1,10)]
    s.patch('indexes',index['id'],chunks=chunks)
    outputs=iter([{'queries':['strategy']},{'sufficient':True},('The ninth strategy is documented [c00009].',[])])
    monkeypatch.setattr(p,'generate',lambda *a,**k:next(outputs))
    c={'id':'test','model':'test','provider':'gemini','vision':False,'max_output':1000,'context_chars':20000}
    result=answer({'document_id':doc['id'],'message':'List strategies on page 5','clarified':True,'top_k':2,'max_passes':1},'page-scope',c)
    assert len(result['sources'])==9 and result['citations']==['c00009']

def test_optional_image_failure_keeps_cited_answer(indexed,monkeypatch):
    doc,index=indexed;id=index['chunks'][0]['id'];count=0
    def generate(*args,**kwargs):
        nonlocal count
        count+=1
        if count==1:return {'queries':['solar']}
        if count==2:return {'sufficient':True}
        if count==3:return ('Source fact ['+id+'].',[])
        raise p.ProviderError('Image quota reached.')
    monkeypatch.setattr(p,'generate',generate)
    c={'id':'test','model':'test','provider':'gemini','vision':False,'image_model':'image-test','max_output':1000,'context_chars':20000}
    result=answer({'document_id':doc['id'],'message':'Explain solar','clarified':True,'generate_image':True},'image-failure',c)
    assert result['status']=='completed' and 'quota' in result['image_error'] and result['citations']==[id]

def test_saved_chat_reopens_its_source_evidence(indexed,client):
    doc,index=indexed
    r=answer({'document_id':doc['id'],'message':'solar','preview':True},'saved-source-preview')
    payload=client.get('/api/sessions/'+r['session_id']).json()
    assert payload['latest_answer']['sources'][0]['elements']
    s.patch('sessions',r['session_id'],isolated=True)
    assert r['session_id'] not in [x['id'] for x in client.get('/api/sessions?document_id='+doc['id']).json()]
