"""Conservative page routing after a lightweight OCR/text pass, never a diagnosis."""
import re
import unicodedata

ROUTING_VERSION = 'page-material-routing-v1'
PATTERNS = {
    'policy': r'保险单|保险合同|保险责任|保单号码|保单信息',
    'invoice': r'发票|财政.*票据|医疗.*收费票据',
    'settlement': r'医疗保险结算|医疗费用结算|结算单',
    'fee_list': r'费用清单|费用明细|收费明细|耗材使用清单',
    'discharge': r'出院记录|出院小结|出院总结',
    'surgery': r'手术记录|手术经过记录',
    'examination': r'检验报告|检查报告|超声报告|病理报告|影像诊断报告',
    'clinical': r'门诊病历|住院病历|入院记录|病程记录|医嘱单|处方笺',
}


def route_material(text):
    # Use the heading area, not disease mentions deep inside insurance terms.
    heading = ''.join(unicodedata.normalize('NFKC', text or '').split())[:600]
    types = [kind for kind, pattern in PATTERNS.items() if re.search(pattern, heading)]
    certainty = 'likely' if len(types) == 1 else 'mixed' if types else 'unknown'
    profile = types[0] if certainty == 'likely' else 'general'
    return {'version': ROUTING_VERSION, 'material_types': types, 'certainty': certainty,
            'extraction_profile': profile,
            'ocr_strategy': 'table' if profile in {'fee_list', 'settlement'} else 'general',
            'method': 'heading-patterns-not-calibrated-model-confidence',
            'requires_review': certainty != 'likely'}


PROFILE_INSTRUCTIONS = {
    'invoice': '本页为医疗票据候选，重点核对票号、日期、总额和支付构成；费用名不能当患者诊断或已实施治疗。',
    'settlement': '本页为结算材料候选，区分医疗总额、医保支付、个人现金、自费和自付；不互相替代。',
    'fee_list': '本页为费用清单候选，临床诊断与实际用药不能从收费项目推断；明细交给独立费用阶段。',
    'discharge': '本页为出院记录候选，分别保留入院、出院诊断与出院医嘱，不混淆治疗阶段。',
    'surgery': '本页为手术记录候选，保留手术名称、时间及计划/既往/否定限定，不从标本或收费推断实施。',
    'examination': '本页为检查报告候选，区分检查所见、诊断结论和送检临床诊断，不升级疑似或否定。',
    'clinical': '本页为临床记录候选，严格区分原文事实、既往史和后续计划。',
}
