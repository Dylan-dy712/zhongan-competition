"""Reproducible claim-cohort statistics; no invented clinical or missing-data scores."""
import hashlib
import json
from collections import defaultdict
from datetime import date, timedelta
from statistics import median, mean
from typing import Literal
from uuid import UUID, NAMESPACE_URL, uuid5

from pydantic import Field, model_validator
from .contracts.core import Contract
from .contracts.knowledge import DiseaseCode

METRICS = {
    'cost_level': ('同组费用水平', 'ratio', -1),
    'self_paid_burden': ('医疗自付负担', 'ratio', -1),
    'medication_conformity': ('用药适用规则符合度', 'ratio', 1),
    'treatment_conformity': ('治疗适用标准符合度', 'ratio', 1),
    'guidance_completeness': ('出院指引记录完整度', 'ratio', 1),
    'readmission_rate': ('完整观察窗内非计划再入院率', 'ratio', -1),
    'patient_feedback': ('固定问项患者反馈', '1-5', 1),
}
MetricName = Literal['cost_level','self_paid_burden','medication_conformity','treatment_conformity',
                     'guidance_completeness','readmission_rate','patient_feedback']
EntityType = Literal['hospital','doctor','treatment_plan']
VERSION='claim-cohort-metrics-v2'


class QualityContract(Contract):
    model_config={'str_strip_whitespace':True}


class NumberSource(QualityContract):
    value: int = Field(ge=0,strict=True)
    source_refs: list[UUID] = Field(min_length=1)


class RuleAudit(QualityContract):
    passed: int = Field(ge=0,strict=True)
    decidable: int = Field(ge=0,strict=True)
    applicable: int = Field(ge=0,strict=True)
    rule_version: str = Field(min_length=1)
    reviewer_id: str = Field(min_length=1)
    source_refs: list[UUID] = Field(min_length=1)

    @model_validator(mode='after')
    def counts(self):
        if not self.passed<=self.decidable<=self.applicable:
            raise ValueError('audit counts must preserve applicable/decidable/passed order')
        return self


class Followup(QualityContract):
    complete: bool = Field(strict=True)
    unplanned_readmission: bool | None = Field(default=None,strict=True)
    planned_excluded: bool = Field(strict=True)
    window_days: int = Field(ge=1,strict=True)
    observed_until: date
    source_refs: list[UUID] = Field(min_length=1)


class FeedbackScore(QualityContract):
    value: float = Field(ge=1,le=5,allow_inf_nan=False)
    question_version: str = Field(min_length=1)
    source_refs: list[UUID] = Field(min_length=1)


class QualityEntity(QualityContract):
    entity_id: str = Field(min_length=1)
    entity_type: EntityType
    display_name: str = Field(min_length=1)
    hospital_id: str | None = None
    doctor_role: str | None = None
    plan_definition: str | None = None
    plan_version: str | None = None

    @model_validator(mode='after')
    def attribution_identity(self):
        if self.entity_type=='doctor' and (not self.hospital_id or not self.doctor_role):
            raise ValueError('doctor requires hospital namespace and documented role')
        if self.entity_type=='treatment_plan' and (not self.plan_definition or not self.plan_version):
            raise ValueError('plan requires a normalized definition and version')
        return self


class Attribution(QualityContract):
    entity_id: str = Field(min_length=1)
    entity_type: EntityType
    metrics: list[MetricName] = Field(min_length=1)
    source_refs: list[UUID] = Field(min_length=1)


class CohortRecord(QualityContract):
    encounter_id: UUID
    subject_ref: str = Field(min_length=1) # private pseudonym, never included in aggregate output
    hospital_id: str = Field(min_length=1)
    discharged_at: date
    disease_group: DiseaseCode
    treatment_group: str = Field(min_length=1)
    risk_group: str | None = None
    payer_group: str | None = None
    settlement_basis: Literal['medical_personal_share'] = 'medical_personal_share'
    currency: Literal['CNY'] = 'CNY'
    attributions: list[Attribution] = Field(min_length=1)
    total_cost_minor: NumberSource | None = None
    self_paid_minor: NumberSource | None = None
    medication_conformity: RuleAudit | None = None
    treatment_conformity: RuleAudit | None = None
    guidance_completeness: RuleAudit | None = None
    followup: Followup | None = None
    feedback: FeedbackScore | None = None

    @model_validator(mode='after')
    def amounts(self):
        if self.self_paid_minor and self.total_cost_minor and self.self_paid_minor.value>self.total_cost_minor.value:
            raise ValueError('medical personal share cannot exceed the matching total')
        keys=[(a.entity_type,a.entity_id) for a in self.attributions]
        if len(set(keys))!=len(keys):
            raise ValueError('duplicate entity attribution')
        return self


class MetricPolicy(QualityContract):
    version: str = Field(min_length=1)
    status: Literal['draft','frozen'] = 'draft'
    reviewed_by: str | None = None
    reviewed_at: date | None = None
    window_start: date
    window_end: date
    min_sample_size: int = Field(ge=2,strict=True)
    max_missing_rate: float = Field(ge=0,le=1,allow_inf_nan=False)
    min_computable_dimensions: int = Field(default=5,ge=5,le=7,strict=True)
    readmission_window_days: int = Field(ge=1,strict=True)
    medication_rule_version: str = Field(min_length=1)
    treatment_rule_version: str = Field(min_length=1)
    guidance_rule_version: str = Field(min_length=1)
    feedback_question_version: str = Field(min_length=1)

    @model_validator(mode='after')
    def policy_scope(self):
        if self.window_start>self.window_end:
            raise ValueError('invalid observation window')
        if self.status=='frozen' and (not self.reviewed_by or not self.reviewed_at):
            raise ValueError('frozen policy requires review provenance')
        return self


class QualityInput(QualityContract):
    dataset_version: str = Field(min_length=1)
    data_origin: Literal['synthetic','official_deidentified','authorized_historical']
    entities: list[QualityEntity]
    records: list[CohortRecord]
    policy: MetricPolicy
    excluded_encounters: list[UUID] = Field(default_factory=list)

    @model_validator(mode='after')
    def identities(self):
        registry={(e.entity_type,e.entity_id):e for e in self.entities}
        if len(registry)!=len(self.entities) or len({r.encounter_id for r in self.records})!=len(self.records):
            raise ValueError('duplicate entities or encounters')
        for record in self.records:
            if ('hospital',record.hospital_id) not in registry:
                raise ValueError('encounter requires a mapped hospital')
            for a in record.attributions:
                entity=registry.get((a.entity_type,a.entity_id))
                if not entity:
                    raise ValueError('unknown attribution entity')
                if (entity.entity_type=='hospital' and entity.entity_id!=record.hospital_id) or (
                    entity.entity_type=='doctor' and entity.hospital_id!=record.hospital_id):
                    raise ValueError('attribution is outside the recorded hospital namespace')
                if entity.entity_type=='treatment_plan' and record.treatment_group!=entity.plan_definition+'@'+entity.plan_version:
                    raise ValueError('plan attribution does not match normalized treatment context/version')
        return self


def _group(record):
    return (record.disease_group.value,record.treatment_group,record.risk_group,record.payer_group,record.settlement_basis)


def _observations(rows, name, policy):
    # Choose the latest attributed index BEFORE testing response availability/version.
    # A missing response on the latest index must not revive an older satisfaction score.
    if name=='patient_feedback':
        latest={}
        for row in sorted(rows,key=lambda r:(r.discharged_at,str(r.encounter_id))):
            latest[row.subject_ref]=row
        rows=list(latest.values())
    values=[]
    for row in rows:
        if name=='cost_level' and row.total_cost_minor:
            values.append((row,row.total_cost_minor.value,None,0))
        elif name=='self_paid_burden' and row.total_cost_minor and row.self_paid_minor and row.total_cost_minor.value>0:
            values.append((row,row.self_paid_minor.value,row.total_cost_minor.value,0))
        elif name in {'medication_conformity','treatment_conformity','guidance_completeness'}:
            audit=getattr(row,name)
            expected=getattr(policy,{'medication_conformity':'medication_rule_version',
                'treatment_conformity':'treatment_rule_version','guidance_completeness':'guidance_rule_version'}[name])
            if audit and audit.applicable>0 and audit.decidable>0 and audit.rule_version==expected:
                values.append((row,audit.passed,audit.decidable,(audit.applicable-audit.decidable)/audit.applicable))
        elif name=='readmission_rate':
            followup=row.followup
            if (followup and followup.complete and followup.unplanned_readmission is not None and followup.planned_excluded
                and followup.window_days==policy.readmission_window_days
                and followup.observed_until>=row.discharged_at+timedelta(days=policy.readmission_window_days)):
                values.append((row,int(followup.unplanned_readmission),1,0))
        elif name=='patient_feedback' and row.feedback and row.feedback.question_version==policy.feedback_question_version:
            values.append((row,row.feedback.value,None,0))
    return values


def _value(values, name, baseline):
    if not values:
        return None
    if name=='cost_level':
        return median(v[1] for v in values)/baseline if baseline and baseline>0 else None
    if name=='patient_feedback':
        return mean(v[1] for v in values)
    denominator=sum(v[2] for v in values)
    return sum(v[1] for v in values)/denominator if denominator else None


class Sensitivity(QualityContract):
    method: Literal['leave-one-index-out-not-a-confidence-interval','leave-one-respondent-out-not-a-confidence-interval']
    lower: float | None = Field(default=None,allow_inf_nan=False)
    upper: float | None = Field(default=None,allow_inf_nan=False)
    undefined_perturbations: int = Field(ge=0)


class ProfileMetric(QualityContract):
    entity_id: str
    entity_type: EntityType
    disease_group: DiseaseCode
    cohort_filters: dict[str,str | None]
    metric_name: MetricName
    label: str
    numerator: int | None
    denominator: int | None
    value: float | None = Field(allow_inf_nan=False)
    unit: Literal['ratio','1-5']
    window_start: date
    window_end: date
    sample_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    missing_rate: float = Field(ge=0,le=1)
    undetermined_rate: float = Field(ge=0,le=1)
    computable: bool
    comparison_allowed: bool
    limitations: list[str]
    snapshot_id: UUID
    metric_version: str
    dataset_version: str
    comparison_group_id: str
    metric_ref: str
    reference_sample_count: int | None
    reference_eligible_count: int | None
    reference_missing_rate: float | None = Field(ge=0,le=1)
    reference_median_minor: float | None
    uncertainty: Sensitivity
    eligibility_policy_version: str

    @model_validator(mode='after')
    def computability(self):
        if self.computable!=(self.value is not None) or (self.comparison_allowed and not self.computable):
            raise ValueError('inconsistent metric computability')
        return self


def build_profiles(data: QualityInput):
    digest=hashlib.sha256(json.dumps(data.model_dump(mode='json'),sort_keys=True,separators=(',',':')).encode()).hexdigest()
    snapshot=str(uuid5(NAMESPACE_URL,VERSION+':'+digest))
    excluded=set(data.excluded_encounters)
    records=[r for r in data.records if r.encounter_id not in excluded and
             data.policy.window_start<=r.discharged_at<=data.policy.window_end]
    groups=defaultdict(list)
    attributed=defaultdict(list)
    for row in records:
        groups[_group(row)].append(row)
        for a in row.attributions:
            attributed[(_group(row),a.entity_type,a.entity_id)].append((row,set(a.metrics)))
    entities={(e.entity_type,e.entity_id):e for e in data.entities}
    profiles=[]
    for (group,kind,key),items in sorted(attributed.items(),key=lambda x:str(x[0])):
        filters=dict(zip(('disease_group','treatment_group','risk_group','payer_group','settlement_basis'),group))
        comparison_id=hashlib.sha256(json.dumps(group).encode()).hexdigest()
        baseline_costs=[r.total_cost_minor.value for r in groups[group] if r.total_cost_minor]
        baseline=median(baseline_costs) if baseline_costs else None
        reference_possible=len(groups[group])
        reference_missing=(reference_possible-len(baseline_costs))/reference_possible
        unknown={'unknown','undetermined','missing','未知','不详','未分层'}
        comparable=all(value and value.casefold() not in unknown for value in group[2:4])
        metrics=[]
        for name,(label,unit,direction) in METRICS.items():
            rows=[r for r,names in items if name in names]
            values=_observations(rows,name,data.policy)
            possible=len({r.subject_ref for r in rows}) if name=='patient_feedback' else len(rows)
            missing=(possible-len(values))/possible if possible else 1
            uncertain=max([v[3] for v in values],default=0)
            value=_value(values,name,baseline)
            limitations=[]
            if not comparable: limitations.append('必要风险或医保分层缺失，不能比较')
            if len(values)<data.policy.min_sample_size: limitations.append('有效样本不足')
            if max(missing,uncertain)>data.policy.max_missing_rate: limitations.append('缺失或不可判定比例超限')
            if name=='cost_level':
                if len(baseline_costs)<data.policy.min_sample_size: limitations.append('费用参照组有效样本不足')
                if reference_missing>data.policy.max_missing_rate: limitations.append('费用参照组缺失比例超限')
            if not rows: limitations.append('该维度未明确归因，不能继承医院统计')
            if value is None: limitations.append('缺有效观测或参照分母')
            valid=value is not None and comparable and not limitations
            # ponytail: leave-one-out is O(n²) per cohort; use sufficient statistics for large cohorts.
            perturbed=[]
            if len(values)>1:
                for i,value_row in enumerate(values):
                    remaining_reference=[r.total_cost_minor.value for r in groups[group] if r.total_cost_minor and
                                         r.encounter_id!=value_row[0].encounter_id] if name=='cost_level' else []
                    remaining=values[:i]+values[i+1:]
                    reference=median(remaining_reference) if remaining_reference else None
                    valid_remaining=(len(remaining)>=data.policy.min_sample_size and
                        (possible-1-len(remaining))/(possible-1)<=data.policy.max_missing_rate and
                        max((v[3] for v in remaining),default=0)<=data.policy.max_missing_rate)
                    if name=='cost_level':
                        valid_remaining=valid_remaining and len(remaining_reference)>=data.policy.min_sample_size and (
                            (reference_possible-1-len(remaining_reference))/(reference_possible-1)<=data.policy.max_missing_rate)
                    perturbed.append(_value(remaining,name,reference) if valid_remaining else None)
            bounds=[v for v in perturbed if v is not None]
            metric={'entity_id':key,'entity_type':kind,'disease_group':group[0],'cohort_filters':filters,
                'metric_name':name,'label':label,'numerator':sum(v[1] for v in values) if unit=='ratio' and name!='cost_level' else None,
                'denominator':sum(v[2] for v in values) if unit=='ratio' and name!='cost_level' else None,
                'value':value,'unit':unit,'window_start':str(data.policy.window_start),'window_end':str(data.policy.window_end),
                'sample_count':len(values),'eligible_count':possible,'missing_rate':missing,'undetermined_rate':uncertain,
                'computable':value is not None,'comparison_allowed':valid,'limitations':limitations,'snapshot_id':snapshot,'metric_version':VERSION,
                'reference_sample_count':len(baseline_costs) if name=='cost_level' else None,
                'reference_eligible_count':reference_possible if name=='cost_level' else None,
                'reference_missing_rate':reference_missing if name=='cost_level' else None,
                'reference_median_minor':baseline if name=='cost_level' else None,
                'dataset_version':data.dataset_version,'comparison_group_id':comparison_id,
                'metric_ref':':'.join((snapshot,comparison_id,kind,key,name)),
                'uncertainty':{'method':('leave-one-respondent-out' if name=='patient_feedback' else 'leave-one-index-out')+'-not-a-confidence-interval',
                               'lower':min(bounds) if bounds else None,'upper':max(bounds) if bounds else None,
                               'undefined_perturbations':len(perturbed)-len(bounds)},'eligibility_policy_version':data.policy.version}
            metrics.append(ProfileMetric.model_validate(metric).model_dump(mode='json'))
        profiles.append({'entity_id':key,'entity_type':kind,'display_name':entities[(kind,key)].display_name,
                         'entity':entities[(kind,key)].model_dump(mode='json'),
                         'cohort_filters':filters,'record_count':len(items),'metrics':metrics})
    return {'snapshot_id':snapshot,'input_sha256':digest,'metric_version':VERSION,'dataset_version':data.dataset_version,
            'data_origin':data.data_origin,'policy':data.policy.model_dump(mode='json'),'included_records':len(records),
            'excluded_records':len(data.records)-len(records),'profiles':profiles}


class MatchingNeed(QualityContract):
    need_id: str = Field(min_length=1)
    metric_name: MetricName


class MatchReason(QualityContract):
    reason_code: MetricName
    text: str = Field(min_length=1)
    metric_refs: list[str] = Field(min_length=1)
    need_refs: list[str] = Field(min_length=1)


class Recommendation(QualityContract):
    candidate_id: str
    entity_type: EntityType
    eligible: bool
    match_reasons: list[MatchReason]
    limitations: list[str]
    metric_snapshot_refs: list[UUID]
    ranking_allowed: bool
    rejection_reason: str | None
    policy_version: str
    rank: int | None = Field(default=None,ge=1)

    @model_validator(mode='after')
    def evidence_and_rank(self):
        if self.eligible and len({r.reason_code for r in self.match_reasons})<2:
            raise ValueError('eligible candidate needs two independent bases')
        if self.ranking_allowed!=(self.rank is not None) or (self.ranking_allowed and not self.eligible):
            raise ValueError('a rank requires explicit ranking eligibility')
        return self


def match_profiles(snapshot, *, disease_group, treatment_group, risk_group, payer_group, needs):
    if len(needs)<2 or len({n.metric_name for n in needs})!=len(needs) or len({n.need_id for n in needs})!=len(needs):
        raise ValueError('at least two independent metrics and unique need IDs required')
    policy=snapshot['policy']
    results=[]
    selected={}
    for profile in snapshot['profiles']:
        group=profile['cohort_filters']
        if group['disease_group']!=disease_group or group['treatment_group']!=treatment_group:
            continue
        key=(profile['entity_type'],profile['entity_id'])
        if key not in selected or (group['risk_group']==risk_group and group['payer_group']==payer_group):
            selected[key]=profile
    for profile in selected.values():
        group=profile['cohort_filters']
        metrics={m['metric_name']:m for m in profile['metrics']}
        usable=[n for n in needs if metrics[n.metric_name]['comparison_allowed']]
        reasons=[{'reason_code':n.metric_name,'text':f"您关注{metrics[n.metric_name]['label']}；同组记录值为{metrics[n.metric_name]['value']:.3g}，有效样本{metrics[n.metric_name]['sample_count']}。这不是疗效保证。",
                  'metric_refs':[metrics[n.metric_name]['metric_ref']],
                  'need_refs':[n.need_id]} for n in usable]
        rejection=[]
        if group['risk_group']!=risk_group or group['payer_group']!=payer_group or not risk_group or not payer_group:
            rejection.append('必要分层不匹配')
        if sum(m['comparison_allowed'] for m in metrics.values())<policy['min_computable_dimensions']:
            rejection.append('可计算画像维度不足')
        if len(usable)!=len(needs): rejection.append('明确需求缺少有效独立依据')
        if policy['status']!='frozen': rejection.append('指标政策未冻结')
        eligible=not rejection
        results.append({'candidate_id':profile['entity_id'],'entity_type':profile['entity_type'],'eligible':eligible,
            'match_reasons':reasons if eligible else [],'limitations':['记录统计不等于全面医疗质量；临床结论需独立医学审核'],
            'metric_snapshot_refs':[snapshot['snapshot_id']],'ranking_allowed':False,'rejection_reason':';'.join(rejection) or None,
            'policy_version':policy['version'],'values':{n.metric_name:metrics[n.metric_name]['value'] for n in usable},
            'bounds':{n.metric_name:metrics[n.metric_name]['uncertainty'] for n in usable},
            'stable_dimensions':sum(m['comparison_allowed'] and m['uncertainty']['lower'] is not None and
                not m['uncertainty']['undefined_perturbations'] for m in metrics.values())})
    for kind in ('hospital','doctor','treatment_plan'):
        candidates=[r for r in results if r['eligible'] and r['entity_type']==kind]
        primary=needs[0].metric_name
        direction=METRICS[primary][2]
        candidates.sort(key=lambda r:direction*-r['values'][primary])
        robust_basis=all(r['stable_dimensions']>=policy['min_computable_dimensions'] and
            all(not bound['undefined_perturbations'] and bound['lower'] is not None for bound in r['bounds'].values())
            for r in candidates)
        stable=(len(candidates)>=2 and robust_basis and
            all(a['bounds'][primary]['lower'] is not None and b['bounds'][primary]['lower'] is not None and
            (a['bounds'][primary]['upper']<b['bounds'][primary]['lower'] if direction<0 else
             a['bounds'][primary]['lower']>b['bounds'][primary]['upper']) for a,b in zip(candidates,candidates[1:])))
        for index,candidate in enumerate(candidates):
            allowed=stable and snapshot['data_origin']!='synthetic'
            candidate['ranking_allowed']=allowed
            candidate['rank']=index+1 if allowed else None
            if not allowed:
                candidate['rejection_reason']=('合成数据仅供原型验证' if snapshot['data_origin']=='synthetic' else
                    '可比候选不足' if len(candidates)<2 else
                    '删一后画像维度或明确需求依据不再有效' if not robust_basis else '次序对删一观测扰动敏感')
    for result in results:
        result.pop('values');result.pop('bounds');result.pop('stable_dimensions')
    return [Recommendation.model_validate(result).model_dump(mode='json') for result in results]


class ProfileMatchRequest(QualityContract):
    disease_group: DiseaseCode
    treatment_group: str = Field(min_length=1)
    risk_group: str | None = None
    payer_group: str | None = None
    needs: list[MatchingNeed] = Field(min_length=2,max_length=7)
