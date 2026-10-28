"""Explicit Microsoft sign-in. Tokens remain in the OS encrypted credential cache."""
from __future__ import annotations
import re, threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from . import store as s

CLIENT_ID='04b07795-8ddb-461a-bbee-02f9e1bf7b46'
POOL=ThreadPoolExecutor(max_workers=2,thread_name_prefix='agentic-rag-sign-in')
LOCK=threading.RLock()
PENDING={}

def identity(config):
    tenant=config.get('tenant_id') or 'organizations'; client=config.get('client_id') or CLIENT_ID
    if not re.fullmatch(r'[A-Za-z0-9.-]{1,100}',tenant) or not re.fullmatch(r'[0-9a-fA-F-]{36}',client):
        raise ValueError('Enter a tenant ID/domain and a valid public-client application ID.')
    return tenant,client,s.digest([tenant,client])[:24]

def credential(config,interactive=False,callback=None):
    from azure.identity import AzureCliCredential,DeviceCodeCredential,TokenCachePersistenceOptions,AuthenticationRecord
    from .providers import cipher
    tenant,client,id=identity(config)
    if config.get('auth_mode')=='azure-cli': return AzureCliCredential(tenant_id=tenant if tenant not in {'organizations','common'} else None,process_timeout=20)
    account=s.get('azure_accounts',id)
    record=AuthenticationRecord.deserialize(cipher().decrypt(account['secret_record'].encode()).decode()) if account else None
    if not interactive and not record: raise ValueError('Sign in to Microsoft from Azure workspace first, using the same tenant and application ID.')
    return DeviceCodeCredential(tenant_id=tenant,client_id=client,authentication_record=record,
        cache_persistence_options=TokenCachePersistenceOptions(name='agentic-rag-azure-'+id,allow_unencrypted_storage=False),
        disable_automatic_authentication=not interactive,prompt_callback=callback,timeout=600)

def headers(config,service,key=''):
    if config.get('auth_mode','api-key')=='api-key':
        if not key: raise ValueError('This Azure service needs an API key. Edit the Azure workspace connection.')
        return {'api-key' if service=='search' else 'Ocp-Apim-Subscription-Key':key}
    scope='https://search.azure.com/.default' if service=='search' else 'https://cognitiveservices.azure.com/.default'
    try: token=credential(config).get_token(scope)
    except ValueError: raise
    except Exception: raise ValueError('Microsoft authentication failed. Sign in again and check tenant access and Azure roles.') from None
    return {'Authorization':'Bearer '+token.token}

def accounts():
    return [{k:v for k,v in x.items() if k!='secret_record'} for x in s.rows('azure_accounts')]

def start(config):
    tenant,client,account_id=identity(config)
    with LOCK:
        if sum(x['status'] in {'starting','waiting'} for x in PENDING.values())>=2: raise ValueError('Complete an existing Microsoft sign-in first.')
        id=s.uid(); PENDING[id]={'id':id,'status':'starting','created':s.now(),'tenant_id':tenant,'client_id':client}
    def work():
        from .providers import cipher
        def prompt(uri,code,expires):
            u=urlparse(uri)
            if u.scheme!='https' or u.hostname not in {'microsoft.com','www.microsoft.com','login.microsoftonline.com','aka.ms'}:
                raise ValueError('Microsoft returned an unexpected sign-in address.')
            with LOCK: PENDING[id].update(status='waiting',verification_uri=uri,user_code=code,expires=expires)
        try:
            c=credential(config,True,prompt)
            record=c.authenticate(scopes=['https://cognitiveservices.azure.com/.default'])
            s.put('azure_accounts',account_id,{'tenant_id':tenant,'client_id':client,'username':record.username,'signed_in':s.now(),
                'secret_record':cipher().encrypt(record.serialize().encode()).decode()})
            with LOCK: PENDING[id]={'id':id,'status':'completed','account_id':account_id}
        except Exception:
            with LOCK: PENDING[id]={'id':id,'status':'failed','error':'Microsoft sign-in did not complete. Check your tenant, public-client app permissions, device-code policy and OS credential-store access.'}
    POOL.submit(work)
    return {'id':id,'status':'starting'}

def status(id):
    with LOCK:
        if id not in PENDING: raise ValueError('Sign-in session expired. Start sign-in again.')
        return dict(PENDING[id])
