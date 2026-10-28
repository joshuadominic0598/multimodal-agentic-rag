"""Typed metadata predicates shared by local retrieval, Azure Search and the agent."""
from __future__ import annotations
from collections import Counter
from pathlib import Path
from . import store as s
from .schemas import SearchFilters

VERSION=2
COLLECTIONS=('kinds','sections','source_names','source_types','source_paths','sheets','tags')

def clean(filters=None):
    if isinstance(filters,SearchFilters): filters=filters.model_dump()
    obj=SearchFilters.model_validate(filters or {}).model_dump()
    return {k:v for k,v in obj.items() if v is not None and v!=[] and v!={}}

def groups(filters=None):
    return [clean(x) for x in filters if clean(x)] if isinstance(filters,list) else ([clean(filters)] if clean(filters) else [])

def metadata(chunk,elements=(),tags=()):
    def values(key):return list(dict.fromkeys(str(e[key]) for e in elements if e.get(key) is not None and str(e[key]).strip()))
    names=values('source_name');paths=values('source_path');starts=[float(e['start_seconds']) for e in elements if e.get('start_seconds') is not None];ends=[float(e['end_seconds']) for e in elements if e.get('end_seconds') is not None]
    return {'kinds':list(chunk.get('kinds',[])), 'sections':values('section'), 'source_names':names,
        'source_types':list(dict.fromkeys(Path(name).suffix.lower().lstrip('.') or 'text' for name in (paths or names))),
        'source_paths':paths,'sheets':values('sheet'),'tags':list(dict.fromkeys(tags)), 'has_visual':bool(chunk.get('assets')),
        'time_start':min(starts) if starts else None,'time_end':max(ends) if ends else None}

def indexed_chunks(index):
    # Old local snapshots are read compatibly without rewriting their chunks/fingerprints.
    chunks=index['chunks']
    if all('filter_metadata' in c for c in chunks):return chunks
    extraction=s.get('extractions',index.get('extraction_id','')) or {};lookup={e['id']:e for e in extraction.get('elements',[])}
    return [c if 'filter_metadata' in c else {**c,'filter_metadata':metadata(c,[lookup[id] for id in c.get('element_ids',[]) if id in lookup],index.get('config',{}).get('metadata_tags',[]))} for c in chunks]

def matches(chunk,filters=None):
    m=chunk.get('filter_metadata',{});pages=chunk.get('pages',[])
    for f in groups(filters):
        if f.get('pages') and not set(f['pages'])&set(pages):return False
        if f.get('page_from') is not None or f.get('page_to') is not None:
            if not any((f.get('page_from') is None or n>=f['page_from']) and (f.get('page_to') is None or n<=f['page_to']) for n in pages):return False
        from .index_schema import values
        scalars=values(chunk)
        if any(scalars.get(key)!=value for key,value in f.get('equals',{}).items()):return False
        for key in COLLECTIONS:
            if f.get(key) and not set(f[key])&set(m.get(key,chunk.get(key,[]))):return False
        if 'has_visual' in f and f['has_visual']!=m.get('has_visual',bool(chunk.get('assets'))):return False
        if f.get('time_from') is not None and (m.get('time_end') is None or m['time_end']<f['time_from']):return False
        if f.get('time_to') is not None and (m.get('time_start') is None or m['time_start']>f['time_to']):return False
    return True

def quote(value):return "'"+value.replace("'","''")+"'"

def odata(filters=None):
    clauses=[]
    for f in groups(filters):
        for key,value in f.get('equals',{}).items():
            literal=quote(value) if isinstance(value,str) else str(value).lower() if isinstance(value,bool) else str(value)
            clauses.append(f'{key} eq {literal}')
        for key in COLLECTIONS:
            if f.get(key):clauses.append('('+ ' or '.join(f'{key}/any(v: v eq {quote(v)})' for v in f[key])+')')
        if f.get('pages'):clauses.append('('+' or '.join(f'pages/any(p: p eq {n})' for n in f['pages'])+')')
        bounds=[]
        if f.get('page_from') is not None:bounds.append(f"p ge {f['page_from']}")
        if f.get('page_to') is not None:bounds.append(f"p le {f['page_to']}")
        if bounds:clauses.append('pages/any(p: '+' and '.join(bounds)+')')
        if 'has_visual' in f:clauses.append('has_visual eq '+str(f['has_visual']).lower())
        if f.get('time_from') is not None:clauses.append(f"time_end ge {f['time_from']}")
        if f.get('time_to') is not None:clauses.append(f"time_start le {f['time_to']}")
    return ' and '.join('('+c+')' for c in clauses)

def schema_fields():
    return [*[{'name':k,'type':'Collection(Edm.String)','filterable':True,'facetable':True} for k in COLLECTIONS],
        {'name':'has_visual','type':'Edm.Boolean','filterable':True},
        *[{'name':k,'type':'Edm.Double','filterable':True} for k in ('time_start','time_end')]]

def catalog(index,limit=200):
    chunks=indexed_chunks(index);fields={}
    from .index_schema import configure,SPECS
    settings=configure(index.get('config',{}).get('index_fields',{}))
    for key in ('pages',)+COLLECTIONS:
        if not settings[key]['filterable']:continue
        count=Counter(v for c in chunks for v in set(c.get('pages',[]) if key=='pages' else c['filter_metadata'].get(key,[])))
        vals=sorted(count,key=lambda v:str(v).casefold())
        fields[key]={'values':[{'value':v,'count':count[v]} for v in vals[:limit]],'total_values':len(vals),'truncated':len(vals)>limit}
    scalar_fields=[spec for spec in SPECS if settings[spec['name']]['filterable'] and not spec['type'].startswith('Collection')]
    return {'index_id':index['id'],'backend':index.get('backend','local'),'metadata_version':index.get('retrieval_schema_version',0),
        'requires_rebuild':index.get('backend')=='azure-ai-search' and index.get('retrieval_schema_version',0)<VERSION,
        'fields':fields,'scalar_fields':scalar_fields,'has_visual_filterable':settings['has_visual']['filterable'],'has_visual':any(c['filter_metadata']['has_visual'] for c in chunks),
        'has_timestamps':settings['time_start']['filterable'] and settings['time_end']['filterable'] and any(c['filter_metadata']['time_start'] is not None for c in chunks)}

def validate_agent_filters(index,proposed):
    f=clean(proposed)
    require_schema(index,f)
    # Model-generated names must exist in this snapshot, never arbitrary OData.
    chunks=indexed_chunks(index)
    for key in ('pages',)+COLLECTIONS:
        available={v for c in chunks for v in (c.get('pages',[]) if key=='pages' else c['filter_metadata'].get(key,[]))}
        if any(v not in available for v in f.get(key,[])):raise ValueError('The agent proposed a metadata value absent from this index. Specify a filter or refine the question.')
    return f

def require_schema(index,filters=None):
    if index.get('backend')=='azure-ai-search' and index.get('retrieval_schema_version',0)<VERSION:
        if any(any(k not in {'pages','page_from','page_to'} for k in f) for f in groups(filters)):
            raise ValueError('This Azure index predates rich metadata filters. Build a new index version to use these filters; the existing index remains available.')

def validate_fields(index,filters=None):
    from .index_schema import configure,SPECS
    settings=configure(index.get('config',{}).get('index_fields',{}))
    aliases={'page_from':'pages','page_to':'pages','time_from':'time_end','time_to':'time_start'}
    import math
    from .index_schema import SPECS
    types={spec['name']:spec['type'] for spec in SPECS}
    for group in groups(filters):
        for field,value in group.get('equals',{}).items():
            type_name=types.get(field,'')
            valid=(type_name=='Edm.String' and isinstance(value,str)) or (type_name=='Edm.Boolean' and isinstance(value,bool)) or (type_name=='Edm.Int32' and type(value) is int) or (type_name=='Edm.Double' and type(value) in {float,int} and math.isfinite(value))
            if not valid or not settings[field]['filterable']:raise ValueError('Exact metadata filters must use a configured filterable scalar field with the correct value type.')
        for key in group:
            if key=='equals':continue
            field=aliases.get(key,key)
            if not settings[field]['filterable']:raise ValueError(f'{field} was not configured as filterable in this index. Change its field setup and build a new index version.')
    require_schema(index,filters)
