"""Model-selected service routes over an attributed, offline catalogue.

No personal policy verification, appointment, payment, or location lookup happens here.
"""
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from .online_care import scope_summary

CATALOG_PATH=Path(__file__).resolve().parents[3]/'contracts/medical-services/catalog.json'
SERVICE_INVITATION='如果你想了解保单里的医疗增值服务，或想找适合复查的医院、在线咨询的医生，也可以继续问我，我陪你一起看看。'
SERVICE_INSTRUCTION='''
医疗服务推荐：本演示默认客户具备中高端权益，但尚未读取真实保单。以“中高端服务参考”表达，不说已核验、免费全包或一定报销。
用户问复查、看病不便、附近公立/私立医院、身体不适如何就医、体检、护理、康复或线上咨询时，结合本轮和本对话上下文判断；有服务承接价值时调用recommend_medical_services选择benefits、offline、online的一类或组合。不能每轮都展示所有类别；倾诉或单纯术语解释不用强推服务。
用户明确要体检权益、绿通、医院名单或互联网医院入口时，必须先实际调用工具，取得结果后再回答。不能只说“帮你查”“把入口调出来”就结束；缺地区也可调用工具获取地区补问。演示已约定中高端权益，不能因缺真实保单而拒绝查询参考，资格限制由工具返回。
复查通常用followup，不自动用checkup；checkup仅用于用户明确想预防体检且没有新发/加重症状。身体不适先了解部位、持续时间、严重度等必要信息，不能仅凭“不舒服”就推荐体检或声称适合线上处理。
green_channel仅用于用户询问绿通资格，或材料已明确约定癌症/特定疾病且用户需要相应就医协助；不能从泛泛不舒服推断疾病。绿通有疾病、等待期及计划条件，不是普通复查都能使用。
有突发持续胸痛伴气短/大汗、严重呼吸困难、意识异常等急症征象，优先提示立即急救/急诊，不等待保险权益或地址筛选。若调用服务工具，clinical_priority必须urgent。需要线下检查或症状加重时clinical_priority用offline_assessment，不能用线上咨询替代。
建议线下机构时优先询问本次希望就医的城市/区县或附近地标；location只能逐字摘自用户本轮或本对话已说出的地点，不得猜城市或把病历医院当住址。用户可以不提供精确住址。缺位置时仍可提供适用权益或线上入口，并问一句地区；用户随后只补充地点，也须结合上文继续调用工具。
specialty依据本次用户需求和已经读取的材料选择；未知用general，不从泛泛不舒服推断肿瘤、心脏等疾病。只知道普通复查需求时不推荐肿瘤、康复等专病机构。
必须结合当前就诊人、本次疾病和已读取材料填写condition、visit_stage、symptom_status、online_purpose；不得把家属疾病、否定癌症、单纯癌症科普当成本人患癌。condition未知用unknown，不依据药品直赔目录推断医院接诊全病种。common_chronic仅用于材料/用户明确的常见病或慢性病；线上复诊/续方还需既往明确诊断且病情稳定。首次就诊、新发或加重、需检查/手术/放化疗转线下。
恶性或疑似肿瘤（specialty=oncology或condition=oncology）优先同城肿瘤专科及有来源的众安网络候选，不能只给通用互联网医院卡。仅结节不等于癌症。cancer_type只在用户/材料明确时填lung/colorectal/other；未知填unknown。肺癌/肠癌肿瘤安康仅可在用户需要健康管理时用online_purpose=cancer_support，仍保留线下路径，不能代替确诊治疗；其他癌种不套用该专项。绿通和特药只提供符合本计划条件的资格参考，不自动承诺拥有权益。
精神/心理需求condition=mental_health，本版三甲图文不覆盖，转线下对应专科；其他未核实病种condition=other，不承诺线上诊疗。online_purpose=health_guidance表示健康咨询，followup/prescription表示实际复诊/续方，procedure表示需线下检查或治疗。age_years只填已知年龄，未知留空；6周岁及以下不能套用本版线上处方服务。工具返回clinical_prompt时先补充必要信息，notice需在正文说明，不得用其他泛化咨询权益绕过限制。
工具返回卡片将由界面展示，不用在正文重复全部名单和条款。正文用一两段解释选择原因和下一步即可。医院资料只支持候选信息，不证明实时号源、具体科室适用、临床质量排名或已核实合作资格；没有坐标不得编公里数或声称最近。公立和私立按用户偏好选择，不把私立等同于更好。
服务来源随卡片展示；卡片ID、医院ID和来源URL不能填入evidence_refs或knowledge_refs，它们不是用户病历证据或专业知识条目。
工具status为needs_location/no_local_matches时，如实询问或说明同城名录缺口，不跨城凑数。urgent时只围绕急救承接。所有服务为模拟，不能说已真实预约、问诊、核验保单、支付或向医院发送资料；聊天内模拟预约只有服务工具返回booked后才能说模拟预约完成。
'''

def pending_service_reply(text, context=''):
    """Detect an unfulfilled promise or nonexistent cards in the model draft.

    Context only resolves the omitted object in short lookup promises. Clinical
    intent and all recommendation arguments still come from the model planner.
    """
    if len(text)>600:return False
    if re.search(r'(?:不用|不必|不需要)(?:我|帮你|帮您)',text):return False
    if (len(text)<=240 and re.search(r'医院|医生|线下|医疗|就医|权益|体检|问诊|在线咨询',context)
            and re.search(r'(?:我(?:先|来|这就|现在|可以|会|再|马上)?|帮你|帮您|为你|为您).{0,12}'
                          r'(?:查一下|查一查|查查|查询一下|找一下|找找|看看|筛选一下|整理一下|匹配一下|联系一下|对接一下|转接一下)',text)
            and not re.search(r'查到|找到|查过|找过|查不到|找不到|无法|不能|不(?:用|必|需要)|未(?:查|找)|没有(?:查|找)',text)):
        return True
    if (re.search(r'(?:下[面方]|以下).{0,16}卡片|卡片.{0,16}(?:候选|机构|模拟入口)',text)
            and re.search(r'权益|中高端|医院|候选机构|公立|私立|在线咨询|体检',text)):
        return True
    if not re.search(r'我|为你|帮你',text):return False
    if re.search(r'(?:帮你|帮您|为你|为您|我).{0,14}(?:查|找|调|整理|筛选|匹配|推荐|安排|核对|看看).{0,45}(?:医院|医生|专科|就医|权益|医疗|线下资源|候选)',text):return True
    return bool(re.search(
        r'(?:查一下|查一查|查询|筛选|匹配|推荐|调出|整理).{0,24}(?:权益|医疗服务|体检入口|互联网医院|附近.{0,8}医院|医院(?:名单|资源|选择|入口)|在线(?:咨询|问诊)(?:入口|服务))'
        r'|(?:权益|医疗服务|体检|互联网医院|医院(?:名单|资源|选择|入口)|在线(?:咨询|问诊)).{0,24}(?:入口.{0,6}调出|查一下|查一查|帮你查|调出来|推荐|匹配)',text))

def separate_service_citations(reply,services):
    """Keep exact UI catalogue identifiers out of clinical citation fields.

    Service provenance remains visible on its card. Unknown references still
    reach the normal evidence validator and cannot be silently discarded.
    """
    known=set()
    for card in (services or {}).get('cards',[]):
        known.update([card['id'],card['action']['target_id'],card['source']['url']])
        if card['source'].get('address_url'):known.add(card['source']['address_url'])
    if not known:return reply
    citations=[]
    for citation in reply.citations:
        refs=[ref for ref in citation.source_refs if ref not in known]
        if refs:citations.append(citation.model_copy(update={'source_refs':refs}))
    return reply.model_copy(update={'knowledge_refs':[ref for ref in reply.knowledge_refs if ref not in known],
                                   'citations':citations})

class MedicalServiceArgs(BaseModel):
    model_config=ConfigDict(extra='forbid')
    routes:list[Literal['benefits','offline','online']]=Field(min_length=1,max_length=3)
    needs:list[Literal['followup','checkup','consultation','green_channel','inpatient_care','postoperative_care','rehabilitation','medicine']]=Field(min_length=1,max_length=3)
    clinical_priority:Literal['routine','offline_assessment','urgent']='routine'
    location:str=Field(default='',max_length=80,description='只能逐字摘自当前用户或本对话用户消息的地点；未知留空')
    institution_types:list[Literal['public','private']]=Field(default_factory=lambda:['public','private'],min_length=1,max_length=2)
    specialty:Literal['general','cardiology','orthopedics','respiratory','oncology','rehabilitation','pediatrics','ophthalmology','dentistry','psychiatry']='general'
    condition:Literal['unknown','common_chronic','oncology','mental_health','other']='unknown'
    visit_stage:Literal['unknown','first_visit','established']='unknown'
    symptom_status:Literal['unknown','stable','new_or_worsening']='unknown'
    online_purpose:Literal['health_guidance','followup','prescription','cancer_support','procedure']='health_guidance'
    cancer_type:Literal['unknown','lung','colorectal','other']='unknown'
    age_years:int|None=Field(default=None,ge=0,le=120)

@lru_cache(maxsize=1)
def catalog():
    return json.loads(CATALOG_PATH.read_text(encoding='utf-8'))

def _source(item,title):
    return {'title':title,'url':item['source_url'],'pages':item.get('source_pages',''),
            **({'address_url':item['address_source_url']} if item.get('address_source_url') else {})}

def _benefit_card(item,need):
    return {'id':'benefit-'+item['id'],'kind':'benefit','title':item['title'],
        'subtitle':'保单增值服务','description':item['summary'],
        'tags':['中高端权益参考','需确认使用条件'],
        'reasons':['与你这次的'+{'checkup':'预防体检','followup':'复查就诊','inpatient_care':'住院照护',
            'postoperative_care':'院后护理','rehabilitation':'康复支持','medicine':'购药咨询','consultation':'在线咨询','green_channel':'绿通资格咨询'}[need]+'需求对应',
            '对应产品手册列有这类服务，可进一步查看资格'],
        'details':[{'label':'使用条件','value':item['eligibility']},{'label':'次数与期限','value':item['limits']}],
        'notice':'体检不替代因症状或医嘱安排的复查。' if need=='checkup' else '是否可用、剩余次数及费用，以实际保单和服务方核验为准。',
        'source':_source(item,'中高端PLUS2026服务手册'),
        'action':{'kind':'benefit','label':'查看使用方式','target_id':item['id']}}

def _hospital_card(item,location,specialty='general'):
    private=item['ownership']=='private'
    card={'id':'hospital-'+item['id'],'kind':'hospital','title':item['name'],
        'subtitle':'私立医疗候选' if private else '公立医疗候选',
        'description':item['address'] or item['city']+' · 具体院区地址需向服务方确认',
        'tags':[item['city'],'私立' if private else '公立',*([item['level']] if item['level'] else [])],
        'reasons':['与你提供的就医地区“'+location+'”同城，可继续确认交通便利性',
            '来源列为'+(item['level']+'，' if item['level'] else '')+(item['kind'] or '指定私立机构')+'，可向医院确认复查科室和就诊安排'],
        'details':[{'label':'地址','value':item['address'] or '来源未列详细地址，预约前确认具体院区'},
            {'label':'名单范围','value':item['product_scope']+'；'+item['network']},
            {'label':'费用与服务','value':item['coverage_note']}],
        'notice':'按地区匹配，未计算实际距离；号源、适用部门及保单资格待确认。',
        'source':_source(item,'众安公开机构名单' if private else '医院或政府官网'),
        'action':{'kind':'hospital','label':'查看就医方案','target_id':item['id']}}
    if item.get('network_type')=='green_channel':
        card['source']['title']='众安重疾绿通公开历史名单（2021-09-09版）'
        card['tags'].append('绿通历史名单·待核验')
        card['notice']='公开历史绿通名单候选；当前合作、本人产品适用及能否安排均须服务方重新确认。'
    if specialty=='oncology':
        specialist=bool(re.search('肿瘤',item['name']+item['kind']))
        card['subtitle']='肿瘤专科候选' if specialist else '综合医院·肿瘤科待确认'
        card['reasons'][1]=('来源明确列为肿瘤专科候选，需继续核对癌种、治疗阶段及接诊科室' if specialist else
            '作为综合医院备选，须先确认是否开设本次癌种对应专科；不视为已匹配肿瘤治疗能力')
        card['details'].append({'label':'网络性质','value':'历史重疾绿通网络，须重新核验' if item.get('network_type')=='green_channel' else
            '指定医疗机构或公开就医资料；列入保险名单不等于绿通合作或保证赔付'})
    return card

def _online_card(args):
    return {'id':'online-zhongan','kind':'online','title':'众安互联网医院','subtitle':'先在线问一问',
        'description':('适合就已明确诊断且病情稳定的常见病、慢性病申请复诊评估，是否接诊由医生确认。' if args.online_purpose in {'followup','prescription'} else
            '可先咨询健康和就医准备问题；尚未确认本次疾病适合线上诊疗，不代表可以线上确诊或开药。'),
        'tags':['三甲图文','健康咨询','医生评估接诊'],
        'reasons':['与你这次的'+('稳定期复诊评估' if args.online_purpose in {'followup','prescription'} else '健康与就医咨询')+'目的对应',
            '对应中高端产品手册列有三甲图文问诊服务'],
        'details':[{'label':'服务时间','value':'该版三甲图文服务每日9:00—18:00；全科视频与其他服务时间分别确认'},
            {'label':'常见入口','value':'众安互联网医院微信小程序 → 个人中心 → 我的权益 → 对应保单 → 三甲医生问诊'},
            {'label':'使用边界','value':'医生判断是否符合复诊及处方条件；急症、新发或加重病情可能需要线下就医'}],
        'notice':'不承诺指定医生或即时号源；开方、药费结算需分别满足条件。',
        'source':{'title':'中高端PLUS2026服务手册','url':'https://files2.huizecdn.com/file2/M00/F2/7C/rBYA3GqiQ1uAR1fgAEbZn2UiblA278.pdf','pages':'15-18'},
        'action':{'kind':'online','label':'进入在线咨询','target_id':'zhongan-internet-hospital'}}

def _cancer_support_card():
    return {'id':'online-cancer-support','kind':'online','title':'众安肿瘤安康健康管理咨询',
        'subtitle':'肺癌 / 肠癌专项·需初审','description':'可咨询肿瘤科普、康复和就医方案；确诊和治疗由线下专科承接。',
        'tags':['健康管理','需专项权益','不替代线下治疗'],
        'reasons':['本次明确为肺癌或肠癌相关的健康管理需求','众安官方专项说明列有专家健康咨询与线下就医建议'],
        'details':[{'label':'使用条件','value':'仅本人，保单有效且等待期满，须有对应专项权益并经团队初筛；肺癌或肠癌二选一。'},
            {'label':'服务边界','value':'仅按专项要求提供健康管理；不承接线上首次确诊、手术或放化疗，不保证初审通过。'}],
        'notice':'本专项与中高端PLUS通用图文权益分别核验，不能从演示中高端权益推定已拥有此专项。',
        'source':{'title':'众安肿瘤安康综合管理服务介绍（2024-12-02版）',
            'url':'https://open-cdn.zhongan.com/i-dm-s/2025-4-7/eisvb6t9zzs/65slzwpav57.pdf','pages':''},
        'action':{'kind':'online','label':'查看专项使用条件','target_id':'zhongan-cancer-support'}}


def _clinical_routes(args,payload):
    """Enforce service boundaries on model-interpreted context, not keyword diagnoses."""
    routes=set(args.routes);needs=list(dict.fromkeys(args.needs))
    oncology=(args.specialty=='oncology' or args.condition=='oncology' or args.cancer_type!='unknown')
    requires_offline=(args.clinical_priority=='offline_assessment' or
        args.symptom_status=='new_or_worsening' or args.visit_stage=='first_visit' or
        args.online_purpose=='procedure')
    support=False
    if requires_offline:
        routes={'offline'}
        payload['notice']='本次需要线下评估或检查治疗，线上咨询和预防体检不能替代；先匹配相应科室。'
    elif oncology:
        routes.discard('online');routes.add('offline')
        support=('online' in args.routes and args.online_purpose=='cancer_support' and
                 args.cancer_type in {'lung','colorectal'})
        payload['notice']='肿瘤相关需求优先线下专科；互联网医院不替代确诊、手术或放化疗。'
    elif args.condition in {'mental_health','other'}:
        routes.discard('online');routes.add('offline')
        payload['notice']=('本版三甲图文服务不包含精神类及心理咨询，需匹配相应线下专科。' if args.condition=='mental_health' else
            '本次病种的众安线上接诊范围尚未核实，先匹配线下科室，不承诺线上诊疗。')
    elif 'online' in routes and args.online_purpose in {'followup','prescription','cancer_support'}:
        eligible=(args.condition=='common_chronic' and args.visit_stage=='established' and args.symptom_status=='stable'
                  and args.online_purpose!='cancer_support')
        if not eligible:
            routes.discard('online')
            payload['clinical_prompt']='请补充这次具体疾病、是否已由线下医生明确诊断，以及目前病情是否稳定，再判断能否申请线上复诊。'
        elif args.online_purpose=='prescription' and (args.age_years is None or args.age_years<=6):
            routes.discard('online')
            if args.age_years is None:
                payload['clinical_prompt']='申请本版线上处方服务前，还需要确认就诊人年龄；6周岁及以下不支持。'
            else:
                routes.add('offline')
                payload['notice']='本版线上处方服务不支持6周岁及以下儿童，请由线下儿科医生评估用药。'
    # Blocked online services must not reappear under a generic benefit card.
    if 'online' not in routes and (requires_offline or oncology or args.condition in {'mental_health','other'} or payload.get('clinical_prompt')):
        needs=[n for n in needs if n not in {'consultation','medicine'}]
    if oncology:
        needs=[n for n in needs if n!='checkup']
        if not requires_offline and args.visit_stage=='established':
            routes.add('benefits')
            needs=list(dict.fromkeys(['green_channel',*needs]))
    return routes,needs,oncology,support


def _grounded_location(location,user_messages,cities):
    """Keep the model's location, recovering only an explicit current city.

    A prior district must not hide the user's answer to the city clarification.
    This does not infer the city of a district, address, hospital or record.
    """
    location=location.strip()
    if location and not any(location in text for text in user_messages):location=''
    if not user_messages or any(city.removesuffix('市') in location for city in cities):return location
    pattern=(r'(?:我在|想在|希望在|请按|改到|换到|(?:这次|本次).{0,6}(?:就医|复查).{0,6}(?:在|到|去))'
             r'(?P<city>'+ '|'.join(re.escape(city) for city in sorted(cities)) +r')')
    current=user_messages[0]
    if sum(city in current for city in cities)>1:return location
    matches={match.group('city') for match in re.finditer(pattern,current)
             if not re.search(r'不|没|未|别',current[max(0,match.start()-3):match.start()])
             and not re.match(r'以外|之外',current[match.end():])}
    return next(iter(matches)) if len(matches)==1 else location


def recommend_services(args:MedicalServiceArgs,user_messages:list[str]):
    data=catalog()
    payload={'version':data['version'],'status':'available','policy_label':'中高端服务参考',
        'policy_notice':'本演示按中高端权益提供参考，实际保单资格、次数和费用仍需确认。',
        'location_query':'','location_prompt':'','cards':[]}
    if args.clinical_priority=='urgent':
        return {**payload,'status':'urgent','notice':'优先立即联系120或就近急诊，不等待权益或在线问诊安排。'}
    if 'online' in args.routes:payload['online_scope']=scope_summary()
    routes,needs,oncology,support=_clinical_routes(args,payload)
    if 'benefits' in routes:
        # The LLM chooses needs; the catalogue enforces mutually exclusive medical intent.
        if 'checkup' in needs and any(n in needs for n in ['followup','consultation']):needs.remove('checkup')
        for need in needs:
            if need=='consultation' and 'online' in routes:continue
            item=next((x for x in data['benefits'] if x['need']==need),None)
            if item:payload['cards'].append(_benefit_card(item,need))
            if len(payload['cards'])==2:break
    cities={x['city'] for x in data['hospitals'] if x['city'].endswith('市')}
    location=_grounded_location(args.location,user_messages,cities)
    if 'offline' in routes:
        if not location:
            payload.update(status='needs_location',location_prompt='这次你想在哪个城市、区或附近地标就医？不用提供完整家庭住址。')
        else:
            payload['location_query']=location
            found=[city for city in cities if city.removesuffix('市') in location]
            # A district name alone can be ambiguous. Ask for its city instead of guessing.
            if len(found)!=1:
                if not found and re.search(r'[\u4e00-\u9fff]{2,7}市',location):
                    payload.update(status='no_local_matches',location_prompt='目前公开名录还没有覆盖这个城市的可核实候选。可以告诉我一个临近城市，或先一起整理复诊前的问题。')
                else:
                    payload.update(status='needs_location',location_prompt='再告诉我这次就医的城市好吗？有些区县或地标会重名。')
            else:
                city=found[0]
                rows=[x for x in data['hospitals'] if x['city']==city and x['ownership'] in args.institution_types]
                specialty=('oncology' if oncology else 'psychiatry' if args.condition=='mental_health' else
                    'rehabilitation' if needs==['rehabilitation'] else args.specialty)
                specialist_patterns={'cardiology':'心血管|心脏','orthopedics':'骨科','respiratory':'呼吸|肺科',
                    'oncology':'肿瘤','rehabilitation':'康复','pediatrics':'儿童|儿科','ophthalmology':'眼科','dentistry':'口腔|齿科','psychiatry':'精神|心理'}
                def is_general(item):
                    return ('综合' in item['kind'] or item['ownership']=='public') and not re.search(
                        '肿瘤|康复|心血管|心脏|骨科|眼科|妇儿|妇产|儿童|口腔|齿科|精神|心理',item['name'])
                if specialty=='general':rows=[x for x in rows if is_general(x)]
                else:
                    pattern=specialist_patterns[specialty]
                    rows=[x for x in rows if re.search(pattern,x['name']+x['kind']) or (specialty not in {'rehabilitation','psychiatry'} and is_general(x))]
                # Match local address fragments; never convert these scores into distance or quality.
                fragments={location[i:i+2] for i in range(max(0,len(location)-1))}-{
                    city[i:i+2] for i in range(len(city)-1)}-{'附近','医院','我在','现在','想去'}
                rows.sort(key=lambda x:((0 if re.search('肿瘤',x['name']+x['kind']) else 1) if oncology else 0,
                    -sum(t in x['address'] for t in fragments),not bool(x['address']),
                    -({'三级':3,'二级':2}.get(x['level'],0)),x['name']))
                picked=[];seen=set()
                # Oncology prioritizes specialty fit across the allowed ownership types.
                if not oncology:
                    for kind in dict.fromkeys(args.institution_types):
                        row=next((x for x in rows if x['ownership']==kind),None)
                        if row:picked.append(row);seen.add(row['name'])
                for row in rows:
                    if row['name'] not in seen:picked.append(row);seen.add(row['name'])
                    if len(picked)>=3:break
                payload['cards'].extend(_hospital_card(x,location,specialty) for x in picked[:3])
                if not picked:
                    payload.update(status='no_local_matches',location_prompt='这次地区和机构偏好下，公开名录暂时没有可核实的候选。可以换一个临近城市或放宽公立/私立偏好；我也可以先帮你整理复诊问题。')
    if 'online' in routes:payload['cards'].append(_online_card(args))
    if support:payload['cards'].append(_cancer_support_card())
    return payload
