"""Fixed citation slots enforce the count, without fixing the report's prose."""
import json
from .patient_followup import FollowupPayload


def followup_fields():
    schema = FollowupPayload.model_json_schema()
    definitions = schema.get('$defs', {})

    def inline(value):
        if isinstance(value, list):
            return [inline(item) for item in value]
        if not isinstance(value, dict):
            return value
        if '$ref' in value:
            return inline(definitions[value['$ref'].rsplit('/', 1)[-1]])
        result = {key: inline(item) for key, item in value.items() if key not in {'title', 'default'}}
        if result.get('type') == 'object':
            result['required'] = list(result['properties'])
            result['additionalProperties'] = False
        return result

    return inline(schema)['properties']


def strict_analysis_tool():
    fields={'text':{'type':'string','pattern':r'^[\s\S]{1,6000}$',
                    'description':'温和连贯的完整文字解读，正文中不出现来源编号。'}}
    fields.update({f'source_{i}':{'type':'string','pattern':r'^(|S[1-9][0-9]{0,3})$',
                    'description':'支持正文的实际来源短编号；没有更多来源时填空字符串。'} for i in range(1,21)})
    fields.update({f'knowledge_{i}':{'type':'string','pattern':r'^(|(?:FX|FY|GX|YZ|TN)-S\d{1,2}-\d{2}|TY-COST-\d{2}|COST-DOC-\d{2}-\d{3})$',
                   'description':'实际检索到的参考知识entry_id；未引用时填空字符串。'} for i in range(1,5)})
    fields['citations']={'type':'array','maxItems':40,'description':'逐条事实和建议的来源映射；不把全文所有来源挂在每条内容上。',
        'items':{'type':'object','properties':{'quote':{'type':'string','minLength':2,'maxLength':800,
            'description':'逐字复制正文中唯一的一句话或单行段落，去掉加粗符号，不跨行。'},
            'source_refs':{'type':'array','minItems':1,'maxItems':6,'items':{'type':'string'},
            'description':'仅支持这句话的S编号或知识entry_id，须同时出现在对应来源槽位中。'}},
            'required':['quote','source_refs'],'additionalProperties':False}}
    fields.update(followup_fields())
    return {'type':'function','function':{'name':'deliver_analysis','strict':True,
        'description':'仅调用一次，提交本次全部材料的文字解读和最多20个关键引用；未使用的引用槽位填空字符串。',
        'parameters':{'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}}}


def decode_analysis_tool(message):
    calls=message.get('tool_calls') or []
    if len(calls)!=1 or calls[0].get('function',{}).get('name')!='deliver_analysis':
        raise RuntimeError('ANALYSIS_RESPONSE_FORMAT')
    data=json.loads(calls[0]['function']['arguments'])
    expected={'text',*(f'source_{i}' for i in range(1,21)),*(f'knowledge_{i}' for i in range(1,5))}
    optional={'citations', 'clarification_questions', 'suggested_questions', 'patient_updates'}
    if not expected.issubset(data) or set(data) - expected - optional:
        raise RuntimeError('ANALYSIS_RESPONSE_FORMAT')
    return {'role':'assistant','content':json.dumps({'text':data['text'],
        'evidence_refs':[data[f'source_{i}'] for i in range(1,21) if data[f'source_{i}']],
        'history_refs':[], 'knowledge_refs':[data[f'knowledge_{i}'] for i in range(1,5) if data[f'knowledge_{i}']],
        'citations':data.get('citations',[]),
        **{key:data.get(key,[]) for key in optional - {'citations'}}},ensure_ascii=False)}
