"""Fixed citation slots enforce the count, without fixing the report's prose."""
import json


def strict_analysis_tool():
    fields={'text':{'type':'string','pattern':r'^[\s\S]{1,6000}$',
                    'description':'温和连贯的完整文字解读，正文中不出现来源编号。'}}
    fields.update({f'source_{i}':{'type':'string','pattern':r'^(|S[1-9][0-9]{0,3})$',
                    'description':'支持正文的实际来源短编号；没有更多来源时填空字符串。'} for i in range(1,21)})
    return {'type':'function','function':{'name':'deliver_analysis','strict':True,
        'description':'仅调用一次，提交本次全部材料的文字解读和最多20个关键引用；未使用的引用槽位填空字符串。',
        'parameters':{'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}}}


def decode_analysis_tool(message):
    calls=message.get('tool_calls') or []
    if len(calls)!=1 or calls[0].get('function',{}).get('name')!='deliver_analysis':
        raise RuntimeError('ANALYSIS_RESPONSE_FORMAT')
    data=json.loads(calls[0]['function']['arguments'])
    expected={'text',*(f'source_{i}' for i in range(1,21))}
    if set(data)!=expected:
        raise RuntimeError('ANALYSIS_RESPONSE_FORMAT')
    return {'role':'assistant','content':json.dumps({'text':data['text'],
        'evidence_refs':[data[f'source_{i}'] for i in range(1,21) if data[f'source_{i}']],
        'history_refs':[]},ensure_ascii=False)}
