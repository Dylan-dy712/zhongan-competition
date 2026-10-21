"""Attributed service capabilities; problem directions are not live specialties."""
import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

SCOPE_PATH=Path(__file__).resolve().parents[3]/'contracts/medical-services/online-care-scope.json'


@lru_cache(maxsize=1)
def online_scope():
    return json.loads(SCOPE_PATH.read_text(encoding='utf-8'))


def scope_summary():
    data=online_scope()
    return {'verified_on':data['verified_on'],'live_roster_verified':False,
        'departments':[{'id':key,'label':p['label'],'support_level':p['support_level'],
            'examples':p['examples'],'scope_note':p['scope_note']} for key,p in data['profiles'].items()],
        'disease_list_scope':data['disease_list_scope']}


def department_instruction():
    data=online_scope()
    return ('科室必须从有来源的目录按本次用户需求选择，不能全部生成消化内科。'
        '已核实大科室与推断咨询方向不同；direction_only只按大科室提供方向模拟，triage_only先全科分诊，'
        'other_product必须提示当前保单范围待核实。不存在实时专科/医生名单，不能编造已匹配真实专家。'
        'condition_name仅填用户逐字说过的疾病名，未知留空；药费目录不决定能否线上接诊或赔付。'
        '更新需求需action=update和department明确重选，重新核对后接入；confirm/reply保持本次已选方向。目录：'+
        json.dumps(scope_summary(),ensure_ascii=False))


def select_doctor_profile(department,condition_name,user_messages):
    data=online_scope()
    name=condition_name.strip()
    if name and not any(name in text for text in user_messages):
        return None
    disease=next((x for x in data['diseases'] if x['name']==name),None)
    selected=department if department in data['profiles'] else 'general'
    # A quoted diagnosis can constrain routing; the lookup does not diagnose symptoms.
    disease_profile=next((key for key,p in data['profiles'].items() if name and name in p['examples']),None)
    if disease_profile and (selected not in {'pediatrics','traditional_chinese_medicine'} or
            data['profiles'][disease_profile]['support_level']=='offline'):
        selected=disease_profile
    profile=deepcopy(data['profiles'][selected])
    profile.update(id=selected,verified_on=data['verified_on'],live_roster_verified=False,
        sources=[data['sources'][source] for source in profile.pop('source_ids')])
    if name:
        profile['condition_match']={'name':name,'in_drug_benefit_list':disease is not None,
            'scope':data['disease_list_scope'],**({'source_row':disease['row'],'source_page':disease['page']} if disease else {})}
    return profile
