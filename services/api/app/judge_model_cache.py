"""Private, version-bound material extraction for the fixed reviewed library."""
import json,os
from pathlib import Path
from uuid import uuid4
from .parse_cache import payload_digest
from .llm_extractor import ModelExtraction,PROMPT_VERSION as FIELD_PROMPT,SCHEMA_VERSION as FIELD_SCHEMA
from .insight_llm import SemanticInsights,PROMPT_VERSION as INSIGHT_PROMPT,SCHEMA_VERSION as INSIGHT_SCHEMA

FORMAT='reviewed-material-preprocessing-v1'


def canonical_material(documents):
    return '\n\n'.join(page['text'] for doc,pages in sorted(documents,key=lambda pair:pair[0]['source_hash'])
                       for page in sorted(pages,key=lambda page:page['page_index']) if page.get('text'))


def model_identity(documents,knowledge,parser_profile):
    # Document/evidence/account IDs and personal context are never inputs or output.
    sources=sorted([{'sha256':doc['source_hash'],'pages':sorted([
        {key:page.get(key) for key in ('page_index','text','content_hash','parser_version')} for page in pages],
        key=lambda page:page['page_index'])} for doc,pages in documents],key=lambda doc:doc['sha256'])
    reference=[{'entry_id':entry.entry_id,'title':entry.title,'content':entry.content[:500],
                'anchoring':entry.anchoring} for entry in knowledge[:80]]
    return payload_digest({'format':FORMAT,'sources':sources,'parser':parser_profile,'knowledge':reference,
        'field_prompt':FIELD_PROMPT,'field_schema':FIELD_SCHEMA,'insight_prompt':INSIGHT_PROMPT,'insight_schema':INSIGHT_SCHEMA,
        'provider':os.environ.get('LLM_PROVIDER','openai_compatible'),'model':os.environ.get('LLM_MODEL_ID',''),
        'endpoint':os.environ.get('LLM_BASE_URL','').rstrip('/')})


def artifact_path(identity):
    return Path(os.getenv('ZHONGAN_JUDGE_RECOGNITION_ROOT','/home/ubuntu/zhongan-data/judge-recognition'))/'models'/(identity+'.json')


def validated(data):
    fields=ModelExtraction.model_validate(data['fields']).model_dump(mode='json')
    insights=SemanticInsights.model_validate(data['insights']).model_dump(mode='json')
    return {'fields':fields,'insights':insights}


def write_models(documents,knowledge,parser_profile,fields,insights):
    if fields.get('status')!='completed' or insights.get('status')!='completed':
        raise ValueError('MATERIAL_PREPROCESSING_INCOMPLETE')
    data=validated({'fields':{**fields['candidates'],'personnel':fields.get('personnel',[])},
                    'insights':{'candidates':insights['candidates']}})
    material=canonical_material(documents)
    for candidate in [*data['fields']['candidates'],*data['fields']['cost_lines'],*data['fields']['personnel'],*data['insights']['candidates']]:
        if candidate['evidence_quote'] not in material:raise ValueError('MATERIAL_PREPROCESSING_QUOTE_INVALID')
    allowed={entry.entry_id for entry in knowledge[:80]}
    if any(not set(candidate['knowledge_refs']).issubset(allowed) for candidate in data['insights']['candidates']):
        raise ValueError('MATERIAL_PREPROCESSING_KNOWLEDGE_INVALID')
    identity=model_identity(documents,knowledge,parser_profile);target=artifact_path(identity)
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(target.parent,0o700)
    payload={'format':FORMAT,'identity':identity,'data':data,'payload_sha256':payload_digest(data)}
    temporary=target.with_suffix('.tmp-'+uuid4().hex)
    try:
        with temporary.open('x',encoding='utf-8') as stream:
            os.chmod(temporary,0o600);json.dump(payload,stream,ensure_ascii=False,separators=(',',':'))
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,target)
    finally:
        if temporary.exists():temporary.unlink()
    return identity


def read_models(documents,knowledge,parser_profile):
    try:
        identity=model_identity(documents,knowledge,parser_profile);path=artifact_path(identity)
        if path.is_symlink() or path.stat().st_size>2*1024*1024:return None
        payload=json.loads(path.read_text(encoding='utf-8'))
        if payload['format']!=FORMAT or payload['identity']!=identity:return None
        if payload_digest(payload['data'])!=payload['payload_sha256']:return None
        data=validated(payload['data'])
        metadata={'material_preprocessing':'preloaded','artifact':identity,'prompt_tokens':0,'completion_tokens':0,'total_tokens':0}
        fields=data['fields'];personnel=fields.pop('personnel',[])
        return ({'status':'completed','candidates':fields,'personnel':personnel,'raw_output':None,
                 'repaired_output':None,'usage_metadata':dict(metadata)},
                {'status':'completed','candidates':data['insights']['candidates'],'raw_output':None,'usage_metadata':dict(metadata)})
    except (OSError,ValueError,KeyError,TypeError):return None
