"""Starter choices, not a promise of account access or current quota."""
CATALOG = [
    {'id':'gemini','label':'Gemini API','models':['gemini-3.1-flash-lite','gemini-3.8-flash'],
     'defaults':{'model':'gemini-3.1-flash-lite','embedding_model':'gemini-embedding-001','vision':True,'account_tier':'free'},
     'notice':'Use a free or paid Gemini project key. Billing and quotas are controlled in Google AI Studio; changing this label does not upgrade your account.'},
    {'id':'openai','label':'OpenAI platform','models':['gpt-4.1-mini','gpt-5-mini'],
     'defaults':{'model':'gpt-4.1-mini','embedding_model':'text-embedding-3-small','vision':True,'account_tier':'unknown'},
     'notice':'Use an OpenAI platform API key with model access and API billing or credits. ChatGPT and Codex subscriptions do not supply this app with API credits.'},
    {'id':'groq','label':'Groq API','models':['openai/gpt-oss-20b','openai/gpt-oss-120b','qwen/qwen3.8-27b'],
     'defaults':{'model':'openai/gpt-oss-20b','embedding_model':'','vision':False,'account_tier':'free','context_chars':12000,'max_output':1500,'capacity_profile':'small'},
     'notice':'Free and paid Groq keys use the same connection. Starter choices appear in Groq’s free-plan limits; availability and remaining quota depend on your account. Choose a separate local or cloud embedding engine.'},
    {'id':'ollama','label':'Ollama · local','models':['qwen3:8b','qwen3:14b','qwen2.5-coder:7b'],
     'defaults':{'model':'qwen3:8b','endpoint':'http://127.0.0.1:11434','embedding_model':'','vision':False,'account_tier':'local','context_chars':12000,'max_output':1500,'capacity_profile':'small','ollama_context_tokens':16384},
     'notice':'Runs installed models on your computer, without an API key. Qwen3 8B is text-only. Choose description mode for visuals, or install and verify a vision model. Cloud-backed Ollama models are excluded.'},
    {'id':'azure','label':'Azure OpenAI · existing resources','models':[],
     'defaults':{'model':'','embedding_model':'text-embedding-3-small','vision':False,'account_tier':'unknown'},
     'notice':'Additional Azure connection for the existing cloud workflow. Enter the deployment name from your own Azure resource; catalog model names may differ from deployment names.'},
]

def defaults(provider):
    item=next(x for x in CATALOG if x['id']==provider)
    return {'name':item['label'],'provider':provider,'max_output':3000,'context_chars':40000,'capacity_profile':'custom',**item['defaults']}
