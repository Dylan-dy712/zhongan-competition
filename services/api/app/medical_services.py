"""Model-selected service routes over an attributed, offline catalogue.

No personal policy verification, appointment, payment, or location lookup happens here.
"""
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
工具返回卡片将由界面展示，不用在正文重复全部名单和条款。正文用一两段解释选择原因和下一步即可。医院资料只支持候选信息，不证明实时号源、具体科室适用、临床质量排名或已核实合作资格；没有坐标不得编公里数或声称最近。公立和私立按用户偏好选择，不把私立等同于更好。
服务来源随卡片展示；卡片ID、医院ID和来源URL不能填入evidence_refs或knowledge_refs，它们不是用户病历证据或专业知识条目。
工具status为needs_location/no_local_matches时，如实询问或说明同城名录缺口，不跨城凑数。urgent时只围绕急救承接。所有按钮为模拟服务，不能说已替用户预约、问诊、核验保单、支付或向医院发送资料。
'''

def pending_service_reply(text):
    """Detect an unfulfilled promise or nonexistent cards in the model draft.

    This does not classify user intent or choose recommendation arguments.
    """
    if len(text)>600:return False
    if (re.search(r'(?:下[面方]|以下).{0,16}卡片|卡片.{0,16}(?:候选|机构|模拟入口)',text)
            and re.search(r'权益|中高端|医院|候选机构|公立|私立|在线咨询|体检',text)):
        return True
    if not re.search(r'我|为你|帮你',text):return False
    return bool(re.search(
        r'(?:查一下|查一查|查询|筛选|匹配|推荐|调出|整理).{0,24}(?:权益|医疗服务|体检入口|互联网医院|附近.{0,8}医院|医院(?:名单|资源|选择|入口)|在线(?:咨询|问诊)(?:入口|服务))'
        r'|(?:权益|医疗服务|体检|互联网医院|医院(?:名单|资源|选择|入口)|在线(?:咨询|问诊)).{0,24}(?:入口.{0,6}调出|查一下|查一查|帮你查|调出来|推荐|匹配)',text))

class MedicalServiceArgs(BaseModel):
    model_config=ConfigDict(extra='forbid')
    routes:list[Literal['benefits','offline','online']]=Field(min_length=1,max_length=3)
    needs:list[Literal['followup','checkup','consultation','green_channel','inpatient_care','postoperative_care','rehabilitation','medicine']]=Field(min_length=1,max_length=3)
    clinical_priority:Literal['routine','offline_assessment','urgent']='routine'
    location:str=Field(default='',max_length=80,description='只能逐字摘自当前用户或本对话用户消息的地点；未知留空')
    institution_types:list[Literal['public','private']]=Field(default_factory=lambda:['public','private'],min_length=1,max_length=2)
    specialty:Literal['general','cardiology','orthopedics','respiratory','oncology','rehabilitation','pediatrics','ophthalmology','dentistry']='general'

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

def _hospital_card(item,location):
    private=item['ownership']=='private'
    return {'id':'hospital-'+item['id'],'kind':'hospital','title':item['name'],
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

def _online_card():
    return {'id':'online-zhongan','kind':'online','title':'众安互联网医院','subtitle':'先在线问一问',
        'description':'可就已有报告、复诊疑问与医生沟通，由医生评估是否适合线上服务。',
        'tags':['三甲图文','报告解读','复诊咨询'],
        'reasons':['可以先整理复诊问题和已有检查资料，减少来回奔波',
            '对应中高端产品手册列有三甲图文问诊服务'],
        'details':[{'label':'服务时间','value':'该版三甲图文服务每日9:00—18:00；全科视频与其他服务时间分别确认'},
            {'label':'常见入口','value':'众安互联网医院微信小程序 → 个人中心 → 我的权益 → 对应保单 → 三甲医生问诊'},
            {'label':'使用边界','value':'医生判断是否符合复诊及处方条件；急症、新发或加重病情可能需要线下就医'}],
        'notice':'不承诺指定医生或即时号源；开方、药费结算需分别满足条件。',
        'source':{'title':'中高端PLUS2026服务手册','url':'https://files2.huizecdn.com/file2/M00/F2/7C/rBYA3GqiQ1uAR1fgAEbZn2UiblA278.pdf','pages':'15-18'},
        'action':{'kind':'online','label':'进入在线咨询','target_id':'zhongan-internet-hospital'}}

def recommend_services(args:MedicalServiceArgs,user_messages:list[str]):
    data=catalog()
    payload={'version':data['version'],'status':'available','policy_label':'中高端服务参考',
        'policy_notice':'本演示按中高端权益提供参考，实际保单资格、次数和费用仍需确认。',
        'location_query':'','location_prompt':'','cards':[]}
    if args.clinical_priority=='urgent':
        return {**payload,'status':'urgent','notice':'优先立即联系120或就近急诊，不等待权益或在线问诊安排。'}
    routes=set(args.routes);needs=list(dict.fromkeys(args.needs))
    if args.clinical_priority=='offline_assessment':
        routes={'offline'}
    if 'benefits' in routes:
        # The LLM chooses needs; the catalogue enforces mutually exclusive medical intent.
        if 'checkup' in needs and any(n in needs for n in ['followup','consultation']):needs.remove('checkup')
        for need in needs:
            if need=='consultation' and 'online' in routes:continue
            item=next((x for x in data['benefits'] if x['need']==need),None)
            if item:payload['cards'].append(_benefit_card(item,need))
            if len(payload['cards'])==2:break
    location=args.location.strip()
    # A model-proposed location must actually have appeared in a human message.
    if location and not any(location in text for text in user_messages):location=''
    if 'offline' in routes:
        if not location:
            payload.update(status='needs_location',location_prompt='这次你想在哪个城市、区或附近地标就医？不用提供完整家庭住址。')
        else:
            payload['location_query']=location
            cities={x['city'] for x in data['hospitals'] if x['city'].endswith('市')}
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
                specialty='rehabilitation' if needs==['rehabilitation'] else args.specialty
                specialist_patterns={'cardiology':'心血管|心脏','orthopedics':'骨科','respiratory':'呼吸|肺科',
                    'oncology':'肿瘤','rehabilitation':'康复','pediatrics':'儿童|儿科','ophthalmology':'眼科','dentistry':'口腔|齿科'}
                def is_general(item):
                    return ('综合' in item['kind'] or item['ownership']=='public') and not re.search(
                        '肿瘤|康复|心血管|心脏|骨科|眼科|妇儿|妇产|儿童|口腔|齿科',item['name'])
                if specialty=='general':rows=[x for x in rows if is_general(x)]
                else:
                    pattern=specialist_patterns[specialty]
                    rows=[x for x in rows if re.search(pattern,x['name']+x['kind']) or (specialty!='rehabilitation' and is_general(x))]
                # Match local address fragments; never convert these scores into distance or quality.
                fragments={location[i:i+2] for i in range(max(0,len(location)-1))}-{
                    city[i:i+2] for i in range(len(city)-1)}-{'附近','医院','我在','现在','想去'}
                rows.sort(key=lambda x:(-sum(t in x['address'] for t in fragments),not bool(x['address']),
                    -({'三级':3,'二级':2}.get(x['level'],0)),x['name']))
                picked=[];seen=set()
                # Preserve the requested public/private choice without a quality ranking.
                for kind in dict.fromkeys(args.institution_types):
                    row=next((x for x in rows if x['ownership']==kind),None)
                    if row:picked.append(row);seen.add(row['name'])
                for row in rows:
                    if row['name'] not in seen:picked.append(row);seen.add(row['name'])
                    if len(picked)>=3:break
                payload['cards'].extend(_hospital_card(x,location) for x in picked[:3])
                if not picked:
                    payload.update(status='no_local_matches',location_prompt='这次地区和机构偏好下，公开名录暂时没有可核实的候选。可以换一个临近城市或放宽公立/私立偏好；我也可以先帮你整理复诊问题。')
    if 'online' in routes:payload['cards'].append(_online_card())
    return payload
