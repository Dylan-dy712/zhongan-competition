"""Source-bound CNY category/payment fields; never an inferred bill total or self-pay ratio."""
import re
from collections import defaultdict
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from .contracts.core import Contract, FieldValue

VERSION='source-bound-cost-fields-v1'
# Preserve literal labels: aliases/overlapping categories are not summed.
LABEL_ROLES={**dict.fromkeys(('医疗总费用','总费用','费用总计','费用合计'),'total'),
    '合计':'unclassified_total',
    **dict.fromkeys(('明细合计','项目合计'),'detail_subtotal'),
    **dict.fromkeys(('药品费','药费','西药费','中成药费','中药饮片费','检查费','检验费','治疗费',
                    '手术费','麻醉费','床位费','护理费','诊察费','材料费','耗材费','其他费用'),'charge_category'),
    **dict.fromkeys(('个人自付','个人自费','自费费用','现金支付','个人账户支付','医保个人账户支付',
                    '医保统筹支付','统筹基金支付','商业保险赔付','商业保险后净支出'),'payment_component')}
NUMBER=r'(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]{1,2})?'
PAIR=re.compile(r'(?<!\w)(?P<label>'+ '|'.join(re.escape(x) for x in sorted(LABEL_ROLES,key=len,reverse=True))+
    r')[ \t]*[:：|]?[ \t]*(?:人民币|CNY|[￥¥])?[ \t]*(?P<number>'+NUMBER+
    r')(?![0-9.]|,[0-9])[ \t]*(?:元|CNY)?[ \t]*(?=$|[\n；;|，,。])',re.I)

class CostAmount(Contract):
    amount_minor:int=Field(ge=0,strict=True)
    currency:Literal['CNY']='CNY'

class CostSource(Contract):
    evidence_id:UUID
    quote:str=Field(min_length=1)

class CostField(Contract):
    scope_ref:str
    scope_kind:Literal['document_page','evidence_block']
    document_id:UUID | None
    document_version:int | None=Field(ge=1)
    page_index:int | None=Field(ge=0)
    source_label:str
    role:Literal['total','detail_subtotal','charge_category','payment_component','unclassified_total']
    amount:FieldValue[CostAmount]
    sources:list[CostSource]=Field(min_length=1)

    @model_validator(mode='after')
    def source_semantics(self):
        if LABEL_ROLES.get(self.source_label)!=self.role:
            raise ValueError('cost label/role mismatch')
        if self.scope_kind=='document_page':
            if any(v is None for v in (self.document_id,self.document_version,self.page_index)):
                raise ValueError('document-page scope requires all source identity fields')
            expected=f'{self.document_id}@{self.document_version}:page:{self.page_index}'
        else:
            if len({source.evidence_id for source in self.sources})!=1:
                raise ValueError('unknown scope cannot combine evidence blocks')
            expected=f'evidence:{self.sources[0].evidence_id}'
        if self.scope_ref!=expected:
            raise ValueError('cost scope does not match its source identity')
        alternatives=self.amount.alternatives if self.amount.status=='conflict' else []
        pairs=[(alt.value,alt.evidence_ids) for alt in alternatives] if alternatives else [(self.amount.value,self.amount.evidence_ids)]
        refs=set()
        for value,ids in pairs:
            if value is None:
                raise ValueError('cost field must preserve observed or conflicting amounts')
            for ref in ids:
                if not any(source.evidence_id==ref and any(p['label']==self.source_label and
                    p['amount_minor']==value.amount_minor for p in cost_pairs(source.quote)) for source in self.sources):
                    raise ValueError('cost amount is not supported by the cited quote')
            refs.update(ids)
        if refs!={source.evidence_id for source in self.sources}:
            raise ValueError('cost source refs are incomplete')
        return self

class CostBreakdown(Contract):
    builder_version:Literal['source-bound-cost-fields-v1']=VERSION
    fields:list[CostField]
    completeness_status:Literal['not_established']='not_established'
    item_sum_minor:None=None
    self_paid_ratio:None=None
    limitations:list[str]=Field(default_factory=lambda:[
        '仅记录有原文依据的分类/支付汇总标签，未证明项目完整或属于同一张结算单。',
        '不同页面、重复页和重叠分类不相加；支付方式、自费项目与保险后支出不互相替代。'])

def cost_pairs(text):
    for match in PAIR.finditer(text):
        yield {'label':match['label'],'amount_minor':int(Decimal(match['number'].replace(',',''))*100),
               'currency':'CNY','quote':match.group().strip()}

def _scope(row):
    if all(row.get(k) is not None for k in ('document_id','document_version','page_index')):
        return f"{row['document_id']}@{row['document_version']}:page:{row['page_index']}",'document_page'
    return f"evidence:{row['evidence_id']}",'evidence_block'

def build_cost_breakdown(rows,model_lines=()):
    observations=[]
    for row in rows:
        observations.extend((row,pair,.9) for pair in cost_pairs(row['text']))
    for item in model_lines:
        quote=item.get('evidence_quote','')
        if not quote.strip() or item.get('currency')!='CNY' or type(item.get('amount_minor')) is not int:
            continue
        supported=[p for p in cost_pairs(quote) if p['label']==item.get('label')]
        # A quote proves both the literal label and the amount; do not bind a different cell's number.
        if not supported or {p['amount_minor'] for p in supported}!={item['amount_minor']}:
            continue
        for row in rows:
            if quote in row['text'] and any(p['label']==item['label'] and p['amount_minor']==item['amount_minor']
                    for p in cost_pairs(row['text'])):
                observations.append((row,{**supported[0],'quote':quote},item.get('confidence_score')))
    groups=defaultdict(list)
    for row,pair,score in observations:
        scope,kind=_scope(row)
        groups[(scope,pair['label'])].append((row,pair,score,kind))
    fields=[]
    for (scope,label),items in sorted(groups.items()):
        variants=defaultdict(list)
        for row,pair,score,_kind in items:
            variants[pair['amount_minor']].append((str(row['evidence_id']),pair['quote'],score))
        refs=lambda values:list(dict.fromkeys(x[0] for x in values))
        row=items[0][0]
        conflict=len(variants)>1
        scores=[item[2] for item in items]
        confidence=min(scores) if not conflict and all(s is not None for s in scores) else None
        amount=FieldValue[CostAmount](field_id=uuid4(),value=None if conflict else
            CostAmount(amount_minor=next(iter(variants))),raw_value=None if conflict else items[0][1]['quote'],
            status='conflict' if conflict else 'observed',evidence_ids=[] if conflict else refs(next(iter(variants.values()))),
            alternatives=[{'value':{'amount_minor':value,'currency':'CNY'},'evidence_ids':refs(sources)}
                          for value,sources in variants.items()] if conflict else [],
            confidence_score=confidence,confidence_method='source-bound-uncalibrated-v1' if confidence is not None else None,
            unit='CNY')
        fields.append(CostField(scope_ref=scope,scope_kind=items[0][3],document_id=row.get('document_id'),
            document_version=row.get('document_version'),page_index=row.get('page_index'),source_label=label,
            role=LABEL_ROLES[label],amount=amount,sources=[{'evidence_id':ref,'quote':quote}
                for ref,quote in dict.fromkeys((ref,quote) for values in variants.values() for ref,quote,_score in values)]))
    return CostBreakdown(fields=fields)

def cost_fact(rows,model_lines=()):
    breakdown=build_cost_breakdown(rows,model_lines)
    references=list(dict.fromkeys(str(s.evidence_id) for field in breakdown.fields for s in field.sources))
    return {'fact_id':uuid4(),'fact_type':'cost_breakdown','value':breakdown.model_dump(mode='json') if references else None,
        'raw_value':None,'status':'derived' if references else 'missing','assertion':'present' if references else 'unknown',
        'evidence_ids':references,'confidence_score':None,'confidence_method':None,'unit':None,
        'derivation':{'method':VERSION,'completeness_status':'not_established'} if references else None,
        'alternatives':[],'missing_reason':None if references else 'no_supported_cost_labels_in_parsed_materials',
        'extractor_version':VERSION}

def has_cost_conflicts(value):
    return any(field.amount.status=='conflict' for field in CostBreakdown.model_validate(value).fields)

def report_cost_context(rows,model_lines=()):
    breakdown=build_cost_breakdown(rows,model_lines)
    return {'builder_version':VERSION,'completeness_status':breakdown.completeness_status,
        'limitations':breakdown.limitations,'truncated':len(breakdown.fields)>100,
        'fields':[{'document_id':str(field.document_id) if field.document_id else None,
            'document_version':field.document_version,'page_index':field.page_index,'source_label':field.source_label,
            'role':field.role,'status':field.amount.status.value,
            'value':field.amount.value.model_dump() if field.amount.value else None,
            'alternatives':[alt.value.model_dump() for alt in field.amount.alternatives],
            'source_quotes':[source.quote for source in field.sources]} for field in breakdown.fields[:100]]}

def validate_cost_sources(breakdown,evidence):
    """Recheck current-run authoritative evidence before delivering a composite cost field."""
    for field in breakdown.fields:
        for source in field.sources:
            row=evidence.get(str(source.evidence_id))
            if not row or source.quote not in (row.get('text_value') or ''):
                raise ValueError('cost source quote is absent from current evidence')
            if any(getattr(field,key) is not None and str(getattr(field,key))!=str(row[key])
                   for key in ('document_id','document_version','page_index')):
                raise ValueError('cost source is outside its document/page scope')
        pairs=[(a.value,a.evidence_ids) for a in field.amount.alternatives] if field.amount.status=='conflict' else [
            (field.amount.value,field.amount.evidence_ids)]
        for value,refs in pairs:
            if any(not any(p['label']==field.source_label and p['amount_minor']==value.amount_minor
                           for p in cost_pairs(evidence[str(ref)]['text_value'] or '')) for ref in refs):
                raise ValueError('cost amount drops qualifiers or does not match current source')
