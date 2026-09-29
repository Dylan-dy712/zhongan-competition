"""文档类型识别：基于 OCR 文本内容判别（文件名仅作加权提示，不作依据）。

背景：真实材料中文件名与内容常不一致（如名为"发票"实为病案首页），
且大量页面是 UUID 命名，因此类型必须来自内容特征。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# (doc_type, [(pattern, weight)])，按优先级从上到下；命中加权求和取最高。
# 页眉/标题词权重高，正文字词权重低；同类多个特征叠加提高置信度。
_RULES: list[tuple[str, list[tuple[str, int]]]] = [
    (
        "discharge_summary",
        [
            (r"出院小结", 6),
            (r"出院记录", 6),
            (r"入院诊断.*出院诊断", 4),
            (r"出院诊断", 2),
            (r"出院医嘱", 3),
            (r"住院天数", 1),
        ],
    ),
    (
        "medical_record_front",
        [
            (r"病案首页", 6),
            (r"住院费用（元）", 4),
            (r"离院方式", 4),
            (r"手术及操作编码", 4),
            (r"入院病情.*出院诊断", 3),
            (r"是否有出院31天内再住院计划", 5),
            (r"颅脑损伤患者昏迷时间", 3),
        ],
    ),
    (
        "insurance_settlement",
        [
            (r"医疗保险结算", 6),
            (r"医保结算", 5),
            (r"结算单", 3),
            (r"统筹基金支付", 3),
            (r"个人账户支付", 3),
            (r"分类自负|自费金额.*医保", 2),
        ],
    ),
    (
        "invoice",
        [
            (r"发票代码", 5),
            (r"发票号码", 5),
            (r"电子发票", 5),
            (r"增值税.{0,4}普通发票", 6),
        ],
    ),
    (
        "inpatient_bill",
        [
            (r"医疗收费明细", 5),
            (r"住院费用清单", 6),
            (r"住院费用明细", 5),
            (r"收费明细.{0,20}电子", 3),
            (r"自费/分类自负", 4),
            (r"项目编码.{0,10}项目名称", 3),
        ],
    ),
    (
        "outpatient_bill",
        [
            (r"门诊费用清单", 6),
            (r"门诊收费明细", 5),
            (r"门诊费清单", 5),
        ],
    ),
    (
        "pathology_report",
        [
            (r"病理(检查)?报告", 6),
            (r"病理诊断", 4),
            (r"冰冻.{0,6}病理", 3),
            (r"免疫组化", 3),
            (r"石蜡", 2),
        ],
    ),
    (
        "surgery_record",
        [
            (r"手术记录", 6),
            (r"手术经过", 4),
            (r"术后诊断.{0,20}手术名称", 4),
        ],
    ),
    (
        "exam_report",
        [
            (r"检查报告", 4),
            (r"检验报告", 4),
            (r"报告单", 2),
            (r"检查结论|检验结论|检查所见|影像所见", 3),
            (r"超声|CT|MR[I]?|X线|DR|心电图|内窥镜|胃镜|肠镜", 1),
            (r"检验目的|标本类型|检验结果", 2),
        ],
    ),
    (
        "outpatient_record",
        [
            (r"门诊病历", 6),
            (r"门（急）诊病历", 6),
            (r"诊疗历", 5),
            (r"处方笺|处方", 3),
            (r"主诉.{0,30}现病史", 3),
            (r"Rp[:：]", 2),
        ],
    ),
    (
        "admission_note",
        [
            (r"入院记录", 5),
            (r"既往史.{0,40}个人史", 3),
        ],
    ),
]

# 文件名提示（仅同名前缀出现时小幅加权）
_FILENAME_HINTS = {
    "出院小结": "discharge_summary",
    "出院记录": "discharge_summary",
    "住院费用清单": "inpatient_bill",
    "门诊费用清单": "outpatient_bill",
    "检查报告单": "exam_report",
    "一般检查报告单": "exam_report",
    "病理报告": "pathology_report",
    "医保结算单": "insurance_settlement",
    "发票": "invoice",
    "门诊诊疗历": "outpatient_record",
    "门诊病历": "outpatient_record",
    "病历": "outpatient_record",
    "手术记录": "surgery_record",
    "其他资料": "other",
    "病案首页": "medical_record_front",
}

DOC_TYPE_ZH = {
    "discharge_summary": "出院小结/出院记录",
    "medical_record_front": "住院病案首页",
    "inpatient_bill": "住院费用清单",
    "outpatient_bill": "门诊费用清单",
    "insurance_settlement": "医保结算单",
    "invoice": "发票",
    "pathology_report": "病理报告",
    "surgery_record": "手术记录",
    "exam_report": "检查/检验报告",
    "outpatient_record": "门诊病历/诊疗历",
    "admission_note": "入院记录",
    "other": "其他材料",
}


@dataclass
class DocClassification:
    doc_type: str
    score: float
    confidence: float
    matched: list[str] = field(default_factory=list)
    runner_up: str | None = None
    runner_up_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "doc_type": self.doc_type,
            "doc_type_zh": DOC_TYPE_ZH.get(self.doc_type, self.doc_type),
            "score": round(self.score, 2),
            "confidence": round(self.confidence, 3),
            "matched": self.matched,
        }


def classify_page(text: str, filename_hint: str = "") -> DocClassification:
    """对单页 OCR 文本分类。标题区（前 5 行）命中的特征权重 ×2。

    出院小结正文页含大量"检验报告"字样，仅靠全文计数会误判为检查报告；
    文档标题只出现在首页前几行，因此标题区加权是必要纠偏。
    """
    all_lines = text.splitlines()
    head = "\n".join(all_lines[:60])
    title_zone = "\n".join(all_lines[:5])
    scores: dict[str, float] = {}
    matched: dict[str, list[str]] = {}
    for doc_type, patterns in _RULES:
        s = 0.0
        hits: list[str] = []
        for pat, w in patterns:
            m = re.search(pat, head)
            if m:
                bonus = 2 if re.search(pat, title_zone) else 1
                s += w * bonus
                hits.append(pat)
        if s > 0:
            scores[doc_type] = s
            matched[doc_type] = hits

    hint_type = None
    for name_frag, t in _FILENAME_HINTS.items():
        if name_frag in filename_hint:
            hint_type = t
            break
    if hint_type:
        scores[hint_type] = scores.get(hint_type, 0) + 1.5  # 小幅加权，可被内容反超

    if not scores:
        return DocClassification("other", 0.0, 0.2, runner_up=None)

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best, best_score = ranked[0]
    runner_up, runner_score = ranked[1] if len(ranked) > 1 else (None, 0.0)
    # 置信度：绝对分数 + 与次名差距；内容多特征一致时高，仅文件名提示时低
    margin = (best_score - runner_score) / max(best_score, 1.0)
    content_bonus = min(len(matched.get(best, [])), 3) / 3.0
    confidence = min(0.5 + 0.08 * best_score, 0.9) * (0.6 + 0.4 * margin)
    if matched.get(best):
        confidence = min(confidence + 0.1 * content_bonus, 0.98)
    else:
        confidence = min(confidence, 0.55)  # 仅文件名提示
    return DocClassification(
        doc_type=best,
        score=best_score,
        confidence=round(min(confidence, 0.98), 3),
        matched=matched.get(best, []),
        runner_up=runner_up,
        runner_up_score=runner_score,
    )
