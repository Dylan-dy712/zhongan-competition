"""病历结构化抽取（KR1）：bundle -> CaseFacts。

方法分层：
- A 层（确定性规则）：结构化文档的关键字段——日期、住院天数、诊断、手术、
  病案首页/医保结算单/发票的金额、费用清单分类合计。每条值带证据与置信度。
- B 层（LLM 增强，可选）：叙述性内容的实体补全，独立模块 extract_llm.py。

金额一律转分（amount_minor）；日期保留原文与规范值；置信度 = 规则强度
与 OCR 行分数的加权，未经校准只作排序参考（规格 §11.2）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..contracts.common import (
    Assertion,
    DataOrigin,
    Evidence,
    ExecutionMode,
    FieldCandidate,
    FieldStatus,
    FieldValue,
    TextSpan,
    TimePrecision,
)
from ..contracts.facts import (
    CaseFacts,
    DiagnosisItem,
    Encounter,
    ExpenseItem,
    ExpenseScope,
    MedicalEvent,
    MedicationItem,
    ProcedureItem,
)

# ---------- 页与行检索 ----------


@dataclass
class LineHit:
    page: dict
    line_index: int
    line: dict
    match: re.Match

    @property
    def text(self) -> str:
        return self.line["text"]


def iter_lines(pages: list[dict], doc_types: set[str] | None = None):
    for pg in pages:
        if doc_types and pg["classification"]["doc_type"] not in doc_types:
            continue
        for i, ln in enumerate(pg.get("lines", [])):
            yield pg, i, ln


def find_lines(pages: list[dict], pattern: str, doc_types: set[str] | None = None) -> list[LineHit]:
    rx = re.compile(pattern)
    hits: list[LineHit] = []
    for pg, i, ln in iter_lines(pages, doc_types):
        m = rx.search(ln.get("text", ""))
        if m:
            hits.append(LineHit(pg, i, ln, m))
    return hits


# ---------- 解析工具 ----------

_DATE_PATTERNS = [
    (re.compile(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?"), "day"),
    (re.compile(r"(20\d{2})[-/.](\d{1,2})"), "month"),
]


def parse_date(text: str):
    """返回 (iso_date, precision) 或 None。iso 保留日/月精度，不补造。"""
    for rx, prec in _DATE_PATTERNS:
        m = rx.search(text)
        if m:
            y = int(m.group(1))
            a = int(m.group(2))
            if prec == "day":
                d = int(m.group(3))
                if 1 <= a <= 12 and 1 <= d <= 31:
                    return f"{y:04d}-{a:02d}-{d:02d}", TimePrecision.day
            elif 1 <= a <= 12:
                return f"{y:04d}-{a:02d}", TimePrecision.month
    return None


def parse_amount(text: str):
    """金额（元）转分。容忍 OCR 空格/全角。返回 int(分) 或 None。"""
    t = text.replace(" ", "").replace("\u3000", "").replace("，", "")
    m = re.search(r"(\d[\d,，]*(?:\.\d{1,2})?)", t)
    if not m:
        return None
    s = m.group(1).replace(",", "")
    try:
        yuan = float(s)
    except ValueError:
        return None
    return round(yuan * 100)


def clean_name(s: str) -> str:
    return re.sub(r"\s+", "", s).strip("：:、，,；;。.")


# ---------- 证据构造 ----------


def make_evidence(case_id: str, hit: LineHit, method: str) -> Evidence:
    pg, ln = hit.page, hit.line
    text = ln.get("text", "")
    start = hit.match.start() if hit.match else 0
    return Evidence(
        case_id=case_id,
        document_id=pg["document_id"],
        page_index=pg.get("page_index"),
        line_index=hit.line_index,
        text_span=TextSpan(start=start, end=min(start + len(text), len(text)), text=text),
        bbox=ln.get("bbox"),
        extraction_method=method,
        parser_version=pg.get("classification", {}).get("doc_type", ""),
    )


def fv_from_hit(case_id: str, hit: LineHit, value, method: str, unit: str | None = None,
                strength: float = 0.85) -> tuple[FieldValue, Evidence]:
    ev = make_evidence(case_id, hit, method)
    ocr_score = hit.line.get("score", 0.5)
    conf = round(min(0.98, strength * 0.6 + ocr_score * 0.4), 3)
    fv = FieldValue.observed(
        value=value, raw=hit.text, evidence_ids=[ev.evidence_id],
        confidence=conf, method=f"{method}@0.1.0", unit=unit,
    )
    return fv, ev


# ---------- 分节工具 ----------

_HEADER_STOP = re.compile(
    r"^(入院诊断|出院诊断|门诊（急）诊断|门（急）诊诊断|病理诊断|入院时主要症状|主要化验结果|"
    r"特殊检查|病程与治疗结果|合并症|出院医嘱|出院情况|住院天数|入院日期|出院日期|手术及操作|"
    r"出院带药|既往史|个人史|家族史|体格检查|辅助检查|诊疗经过|入院记录|主诉|现病史|第\d+页)"
)


def extract_section(pages: list[dict], header_pattern: str, doc_types: set[str] | None = None,
                    max_lines: int = 40) -> list[tuple[dict, int, dict]]:
    """取 header 行：先取行内剩余内容，再取后续行（直到下一个已知 header 或空行）。

    真实材料中"入院诊断肺部阴影"这类内容常与标题同行，OCR 又会把表格
    拆成多行，因此行内与行间两种形态都要支持。
    """
    out: list[tuple[dict, int, dict]] = []
    hits = find_lines(pages, header_pattern, doc_types)
    if not hits:
        return out
    h = hits[0]
    inline = h.text[h.match.end() :].strip(" ：:")
    if inline:
        out.append((h.page, h.line_index, {"text": inline, "score": h.line.get("score", 0.5), "bbox": h.line.get("bbox")}))
    pg_lines = [(h.page, i, ln) for i, ln in enumerate(h.page.get("lines", []))]
    idx = pg_lines.index((h.page, h.line_index, h.line))
    started = False
    for pg, i, ln in pg_lines[idx + 1 : idx + 1 + max_lines]:
        t = ln.get("text", "").strip()
        if not t:
            if started:
                break
            continue
        if _HEADER_STOP.match(t):
            break
        out.append((pg, i, ln))
        started = True
    return out


_DATE_CTX = re.compile(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?")
_DATE_NO_CENTURY = re.compile(r"^(\d{1,2})年(\d{1,2})月(\d{1,2})日?$")


def _scan_page_dates(page: dict) -> list[tuple[int, str, re.Match]]:
    """页内全部日期：返回 (行号, 行文本, 匹配)。支持世纪位被 OCR 吞掉的形态。"""
    found: list[tuple[int, str, re.Match]] = []
    for i, ln in enumerate(page.get("lines", [])):
        t = ln.get("text", "")
        m = _DATE_CTX.search(t)
        if m:
            found.append((i, t, m))
            continue
        m2 = _DATE_NO_CENTURY.search(t.strip())
        if m2:
            class _Damaged:
                def __init__(self, mm):
                    self._mm = mm
                    self.start, self.end = mm.start(), mm.end()

                def group(self, n):
                    return self._mm.group(n)

            found.append((i, t, _Damaged(m2)))
    return found


def _infer_century(page: dict, yy2: str) -> str:
    """世纪位被 OCR 吞掉时，用页内完整日期推断世纪（如 5 -> 2025）。

    OCR 可能吞掉"202"只留"5"，因此按 后缀匹配 > 年份后两位 > 年份末位 逐级放宽。
    """
    years: list[str] = []
    for ln in page.get("lines", []):
        m = _DATE_CTX.search(ln.get("text", ""))
        if m:
            years.append(m.group(1))
    if not years:
        return f"20{yy2.zfill(2)}"
    for y in years:
        if y.endswith(yy2):
            return y
    for y in years:
        if int(y) % 100 == int(yy2):
            return y
    for y in years:
        if int(y) % 10 == int(yy2):
            return y
    return years[0]


def _find_dated_field(pages: list[dict], anchor_pat: str, doc_types: set[str]) -> tuple[LineHit, str] | None:
    """anchor 行内含日期优先；否则 anchor 行下方 2 行内的第一个日期行。"""
    hits = find_lines(pages, anchor_pat, doc_types)
    for h in hits:
        m = _DATE_CTX.search(h.text, h.match.end())
        if m:
            parsed = parse_date(h.text[m.start() :])
            if parsed:
                return h, parsed[0]
    for h in hits:
        lines = h.page.get("lines", [])
        for j in range(h.line_index + 1, min(h.line_index + 3, len(lines))):
            t = lines[j].get("text", "")
            m = _DATE_CTX.search(t)
            if m:
                parsed = parse_date(t[m.start() :])
                if parsed:
                    return _hit_at(h.page, j, m), parsed[0]
            m2 = _DATE_NO_CENTURY.search(t.strip())
            if m2:
                y = _infer_century(h.page, m2.group(1))
                iso = f"{y}-{int(m2.group(2)):02d}-{int(m2.group(3)):02d}"
                return _hit_at(h.page, j, m2), iso
    return None


def _hit_at(page: dict, line_index: int, match: re.Match) -> LineHit:
    line = page.get("lines", [{}])[line_index] if line_index < len(page.get("lines", [])) else {}
    return LineHit(page, line_index, line or {"text": "", "score": 0.5}, match)


# ---------- 主流程 ----------


def extract_facts(bundle: dict, *, data_origin=DataOrigin.official_deidentified,
                  execution_mode=ExecutionMode.live) -> CaseFacts:
    case_id = bundle["case_id"]
    pages = bundle["pages"]
    facts = CaseFacts(case_id=case_id, run_id="", data_origin=data_origin, execution_mode=execution_mode)
    evs: list[Evidence] = []

    def add_ev(ev: Evidence) -> str:
        evs.append(ev)
        return ev.evidence_id

    # --- 就医（encounter）：按材料形态判定住院/门诊 ---
    enc = Encounter(kind="hospitalization")
    # 住院号会出现在门诊检验单上，只有明确的住院病程标记才判住院
    inpatient_markers = find_lines(pages, r"入院诊断|出院诊断|入院日期|出院日期|住院天数|病案首页")
    if not inpatient_markers:
        enc.kind = "outpatient"

    # 医院：优先住院类文书，其次门诊病历/检查报告/病理（材料头部常有机构名）
    for dt in ("discharge_summary", "medical_record_front", "inpatient_bill", "insurance_settlement",
               "outpatient_record", "pathology_report", "exam_report", "outpatient_bill", "invoice"):
        hits = find_lines(pages, r"([\u4e00-\u9fa5A-Za-z（）()]{2,22}(?:医院|卫生院|医疗中心))", {dt})
        if hits:
            fv, ev = fv_from_hit(case_id, hits[0], clean_name(hits[0].match.group(1)), "rule_hospital", strength=0.8)
            enc.hospital = fv
            add_ev(ev)
            break

    # 入院/出院日期：住院锚点优先，门诊锚点兜底（检验单上的"住院号"字样
    # 不能作为跳过门诊日期的证据，两套锚点独立尝试）
    _date_specs = [
        ("admission_date", [
            (r"入院(日期|时间|于)|^入院\s*$",
             {"discharge_summary", "medical_record_front", "insurance_settlement"}),
            (r"就诊日期[:：]?|检查日期[:：]?|报告时间[:：]?|送检日期[:：]?|接收日期[:：]?|首次报告日期[:：]?|^日期[:：]?",
             {"outpatient_record", "exam_report", "pathology_report", "insurance_settlement"}),
        ]),
        ("discharge_date", [
            (r"出院(日期|时间)|^出院\s*$",
             {"discharge_summary", "medical_record_front", "insurance_settlement"}),
            (r"报告时间[:：]?|审核时间[:：]?|报告日期[:：]?|记录日期[:：]?",
             {"exam_report", "pathology_report", "outpatient_record"}),
        ]),
    ]
    for attr, candidates in _date_specs:
        for pat, dts in candidates:
            found = _find_dated_field(pages, pat, dts)
            if found:
                h, iso = found
                method = f"rule_{attr}" + ("_op" if pat.startswith("就诊") else "")
                fv, ev = fv_from_hit(case_id, h, iso, method, strength=0.82)
                setattr(enc, attr, fv)
                add_ev(ev)
                break

    # 住院天数：原文优先，否则派生（口径：出院-入院，同日计 1）
    hits = find_lines(pages, r"住院天数[:：]?\s*(\d+)")
    if hits:
        fv, ev = fv_from_hit(case_id, hits[0], int(hits[0].match.group(1)), "rule_stay_days", unit="天", strength=0.85)
        enc.stay_days = fv
        add_ev(ev)
    if enc.stay_days is None and enc.admission_date and enc.discharge_date:
        import datetime as _dt

        try:
            a = _dt.date.fromisoformat(enc.admission_date.value)
            d = _dt.date.fromisoformat(enc.discharge_date.value)
            days = max((d - a).days, 1)
            if days > 400:
                # 日期推算异常（多为 OCR 世纪位错误）保留冲突状态，不出确定天数
                enc.stay_days = FieldValue(
                    status=FieldStatus.conflict,
                    raw_value=f"{enc.admission_date.raw_value}~{enc.discharge_date.raw_value}",
                    missing_reason="derived_days_out_of_range",
                    alternatives=[
                        FieldCandidate(value=days, note="discharge-admission"),
                    ],
                )
            else:
                enc.stay_days = FieldValue(
                    value=days,
                    raw_value=f"{enc.admission_date.raw_value}~{enc.discharge_date.raw_value}",
                    status=FieldStatus.derived,
                    unit="天",
                    confidence_score=0.9,
                    confidence_method="derived_stay@0.1.0",
                    derivation={
                        "formula": "discharge - admission, min 1",
                        "inputs": [enc.admission_date.field_id, enc.discharge_date.field_id],
                    },
                )
        except ValueError:
            pass

    # 科室 / 主治医师
    hits = find_lines(pages, r"(?:科室|病区)[:：]\s*([\u4e00-\u9fa5A-Za-z0-9]{2,12}?)(?=床号|门诊号|住院号|$)")
    if hits:
        fv, ev = fv_from_hit(case_id, hits[0], clean_name(hits[0].match.group(1)), "rule_department", strength=0.7)
        enc.department = fv
        add_ev(ev)
    hits = find_lines(pages, r"(?:主治医师|经治医师|术者)[:：]?\s*([\u4e00-\u9fa5]{2,4})")
    if hits:
        fv, ev = fv_from_hit(case_id, hits[0], hits[0].match.group(1), "rule_attending", strength=0.7)
        enc.attending_doctor = fv
        add_ev(ev)

    facts.encounters = [enc] if (enc.admission_date or enc.hospital) else []
    if not facts.encounters:
        facts.encounters = [Encounter(kind="outpatient")]
    enc_id = facts.encounters[0].encounter_id

    # --- 诊断 ---
    dx_specs = [
        ("outpatient", r"门（急）诊诊断"), ("admission", r"入院诊断"), ("discharge", r"出院诊断"),
        ("pathology", r"病理诊断[:：]"), ("clinical", r"临床诊断[:：]"),
    ]
    if enc.kind == "outpatient":
        dx_specs.append(("outpatient", r"^诊断[:：]"))
    _DX_NOISE = re.compile(
        r"^(具体|详见|待|见|请|无)?$|见.{0,8}报告|待.{0,6}报告|待石蜡|"
        r"部分呈|呈.{0,10}方式|免疫组化|分型$|送检|标本")
    _DX_BRACKET = re.compile(r"^[【\[](.+?)[】\]][：:]?")
    seen_dx: set[tuple[str, str]] = set()
    for role, header in dx_specs:
        for pg, i, ln in extract_section(pages, header):
            body = ln.get("text", "")
            for seg in re.split(r"[、，,；;]", body):
                seg = clean_name(seg)
                bm = _DX_BRACKET.match(seg)
                if bm:
                    seg = clean_name(bm.group(1))
                if not seg or len(seg) < 2 or re.fullmatch(r"[\d.]+", seg):
                    continue
                if _DX_NOISE.search(seg) or (role, seg) in seen_dx or len(seg) > 40:
                    continue
                seen_dx.add(seg)
                m = re.search(re.escape(seg), body)
                ev = Evidence(
                    case_id=case_id, document_id=pg["document_id"], page_index=pg.get("page_index"),
                    line_index=i,
                    text_span=TextSpan(start=m.start() if m else 0, end=(m.end() if m else len(body)), text=body),
                    bbox=ln.get("bbox"), extraction_method="rule_diagnosis",
                )
                evs.append(ev)
                facts.diagnoses.append(
                    DiagnosisItem(
                        encounter_id=enc_id, role=role,
                        name=FieldValue.observed(seg, body, [ev.evidence_id], 0.82, "rule_diagnosis@0.1.0"),
                        is_primary=len([d for d in facts.diagnoses if d.role == role]) == 0,
                    )
                )

    # --- 手术/操作 ---
    proc_hits: list[tuple[str, LineHit]] = []

    def add_proc(nm: str, hit: LineHit) -> None:
        nm = clean_name(nm)
        # 名称须以"术"结尾或为明确的术式缩写，过滤"活检穿刺针"等耗材名
        if not nm or len(nm) < 4 or len(nm) > 26:
            return
        if not (nm.endswith("术") or re.search(r"VATS|ERCP|TURP|PCI", nm)):
            return
        if re.fullmatch(r"[\d.]+", nm) or any(p == nm for p, _ in proc_hits):
            return
        proc_hits.append((nm, hit))

    # 1) 病程叙述："于 2025/10/28 全麻下行VATS左上叶部分肺切除术"
    for h in find_lines(pages, r"(?:行|实施|进行)([\u4e00-\u9fa5A-Za-z（）()]{2,24}术)"):
        add_proc(h.match.group(1), h)
    # 2) 直接命中的完整名称（要求名称足够长，避免"胸腔镜"这类裸关键词）
    for h in find_lines(pages, r"(单孔|胸腔镜|腹腔镜|关节镜|内镜下|经皮|椎间|切开|切除|复位|固定|成形|置换|介入|造影|修补|清除|活检|导航计算机辅助外科)([\u4e00-\u9fa5A-Za-z]{0,18}术?)"):
        if len(clean_name(h.match.group(0))) >= 5:
            add_proc(h.match.group(0), h)
    # 3) 病案首页表格跨行断裂：名称片段 + 后续短行（以"术"结尾）拼接
    for dt in ("medical_record_front", "discharge_summary", "surgery_record"):
        for pg, i, ln in iter_lines(pages, {dt}):
            t = clean_name(ln.get("text", ""))
            if not t or t.endswith("术") or len(t) < 4 or len(t) > 24:
                continue
            if re.search(r"(VATS|胸腔镜|腹腔镜|关节镜|内镜|切除|复位|固定|置换|成形|修补|导航|介入)", t):
                lines = pg.get("lines", [])
                for j in range(i + 1, min(i + 8, len(lines))):
                    t2 = clean_name(lines[j].get("text", ""))
                    if 0 < len(t2) <= 7 and t2.endswith("术") and not t2.startswith(("第", "页")):
                        add_proc(t + t2, LineHit(pg, i, ln, re.match(r".*", t)))
                        break
    # 碎片去重：某名称是另一名称的子串时丢弃碎片（保留合并后的完整名）
    names_all = [nm for nm, _ in proc_hits]
    proc_hits = [
        (nm, h) for nm, h in proc_hits
        if not any(nm != other and nm in other for other in names_all)
    ]
    for nm, h in proc_hits[:10]:
        fv, ev = fv_from_hit(case_id, h, nm, "rule_procedure", strength=0.75)
        evs.append(ev)
        proc = ProcedureItem(encounter_id=enc_id, name=fv)
        # 手术日期：优先显式"手术日期"行；否则取名称行 ±4 行内最近日期行
        # （病案首页表格中日期列与名称列在 OCR 行流中相邻）
        date_hit = find_lines(pages, r"(?:手术|操作)(?:日期|时间)[:：]?\s*(20\d{2})")
        if date_hit:
            parsed = parse_date(date_hit[0].text[date_hit[0].match.end() - 4 :])
            if parsed:
                fvd, evd = fv_from_hit(case_id, date_hit[0], parsed[0], "rule_procedure_date", strength=0.85)
                proc.performed_at, proc.time_precision = fvd, parsed[1]
                evs.append(evd)
        else:
            lines = h.page.get("lines", [])
            best_j, best_iso = None, None
            for j in range(max(0, h.line_index - 4), min(len(lines), h.line_index + 5)):
                m = _DATE_CTX.search(lines[j].get("text", ""))
                if m:
                    parsed = parse_date(lines[j].get("text", "")[m.start() :])
                    if parsed:
                        best_j, best_iso = j, parsed[0]
                        if j >= h.line_index:
                            break
            if best_iso:
                hd = _hit_at(h.page, best_j, _DATE_CTX.search(lines[best_j].get("text", "")))
                fvd, evd = fv_from_hit(case_id, hd, best_iso, "rule_procedure_date_prox", strength=0.6)
                proc.performed_at, proc.time_precision = fvd, TimePrecision.day
                evs.append(evd)
        facts.procedures.append(proc)

    # --- 药品：出院带药段落 + 门诊处方/诊疗意见行 ---
    med_section = extract_section(pages, r"出院带药|出院医嘱.{0,6}药")
    med_lines = [(pg, i, ln) for pg, i, ln in med_section]
    for pg, i, ln in iter_lines(pages, {"outpatient_record"}):
        t = ln.get("text", "")
        if re.search(r"(?:注射液|缓释片|胶囊|颗粒|口服液|滴眼液|喷雾剂|乳膏)", t) and re.search(r"(?:一日|每日|每次|口服|注射|静滴|外用)", t):
            med_lines.append((pg, i, ln))

    _MED_NAME = re.compile(
        r"([\u4e00-\u9fa5A-Za-z0-9（）()]{2,20}?(?:注射液|缓释片|分散片|胶囊|颗粒|口服液|气雾剂|"
        r"滴眼液|喷雾剂|软膏|乳膏|栓剂|片|丸|膏|栓|散))"
    )
    _MED_DOSE = re.compile(r"\[?(\d+(?:\.\d+)?)\s*(mg|g|ml|IU|μg|ug)(?::[\d.]+\s*(?:mg|g|ml))?(/(?:支|片|粒|瓶|袋|盒))?\]?")
    _MED_FREQ = re.compile(r"(一日|每日|一天)([一二三四五1-5])次|每晚|必要时|隔日一次")
    _MED_ROUTE = re.compile(r"(皮下注射|肌内注射|肌注|静脉注射|静脉滴注|静滴|口服|外用|雾化吸入|滴入|含服)")
    seen_meds: set[str] = set()
    for pg, i, ln in med_lines:
        body = ln.get("text", "")
        m = _MED_NAME.search(body)
        if not m:
            continue
        name = clean_name(m.group(1))
        if name in seen_meds or len(name) < 3:
            continue
        seen_meds.add(name)
        ev = Evidence(
            case_id=case_id, document_id=pg["document_id"], page_index=pg.get("page_index"), line_index=i,
            text_span=TextSpan(start=m.start(), end=min(m.end() + 40, len(body)), text=body), bbox=ln.get("bbox"),
            extraction_method="rule_medication",
        )
        evs.append(ev)
        med = MedicationItem(encounter_id=enc_id, name=FieldValue.observed(
            name, body, [ev.evidence_id], 0.7, "rule_medication@0.1.0"),
            phase="discharge_prescription" if (pg, i, ln) in med_section else "outpatient")
        dm = _MED_DOSE.search(body[m.end():])
        if dm:
            med.dosage = FieldValue.observed(
                dm.group(0).strip("[]"), body, [ev.evidence_id], 0.6, "rule_medication_dose@0.1.0")
        fm = _MED_FREQ.search(body)
        if fm:
            med.frequency = FieldValue.observed(
                fm.group(0), body, [ev.evidence_id], 0.6, "rule_medication_freq@0.1.0")
        rm = _MED_ROUTE.search(body)
        if rm:
            med.route = FieldValue.observed(
                rm.group(1), body, [ev.evidence_id], 0.6, "rule_medication_route@0.1.0")
        facts.medications.append(med)

    # --- 费用 ---
    _extract_expenses(case_id, pages, enc_id, facts, evs)

    # --- 事件时间线 ---
    facts.events = _build_events(case_id, facts)

    # 完整性状态
    facts.completeness.diagnoses = "found" if facts.diagnoses else "not_found"
    facts.completeness.procedures = "found" if facts.procedures else "none_applicable"
    facts.completeness.medications = "found" if facts.medications else "not_found"
    facts.completeness.hospitalizations = "found" if facts.encounters and facts.encounters[0].admission_date else "not_found"
    facts.completeness.expenses = "found" if facts.expenses else "not_found"

    facts.evidences = evs
    return facts


def _detect_multiple_encounters(pages: list[dict]) -> bool:
    """多份不同日期的出院小结/结算单 => 多次就医（原型：仅标记，按单次处理）。"""
    ds = {h.text for h in find_lines(pages, r"入院日期[:：]?\s*20\d{2}")}
    return len(ds) > 1


def _extract_expenses(case_id, pages, enc_id, facts, evs) -> None:
    def add(hit: LineHit, scope: ExpenseScope, amount_minor: int, method: str, note: str | None = None) -> None:
        fv, ev = fv_from_hit(case_id, hit, amount_minor, method, unit="CNY-minor", strength=0.88)
        evs.append(ev)
        facts.expenses.append(
            ExpenseItem(encounter_id=enc_id, scope=scope, amount_minor=fv,
                        document_id=hit.page["document_id"], note=note)
        )

    # 病案首页：总费用/自付/自费
    for h in find_lines(pages, r"总费用\s*([\d,，.]+)"):
        amt = parse_amount(h.match.group(1))
        if amt:
            add(h, ExpenseScope.total, amt, "rule_front_total")
    for h in find_lines(pages, r"自付金额[:：]?\s*([\d,，.]+)"):
        amt = parse_amount(h.match.group(1))
        if amt:
            add(h, ExpenseScope.self_paid, amt, "rule_front_selfpaid")
    for h in find_lines(pages, r"自费金额[:：]?\s*([\d,，.]+)"):
        amt = parse_amount(h.match.group(1))
        if amt:
            add(h, ExpenseScope.out_of_catalog, amt, "rule_front_outofcatalog")

    # 医保结算单
    for h in find_lines(pages, r"(?:总|医疗)费用[:：]?\s*([\d,，.]+)"):
        amt = parse_amount(h.match.group(1))
        if amt and not any(e.scope == ExpenseScope.total for e in facts.expenses):
            add(h, ExpenseScope.total, amt, "rule_settle_total")
    for h in find_lines(pages, r"统筹(基金)?支付[:：]?\s*([\d,，.]+)"):
        amt = parse_amount(h.match.group(2))
        if amt:
            add(h, ExpenseScope.insurance_paid, amt, "rule_settle_pool")
    for h in find_lines(pages, r"(?:个人支付|个人现金支付)[:：]?\s*([\d,，.]+)"):
        amt = parse_amount(h.match.group(1))
        if amt:
            add(h, ExpenseScope.self_paid, amt, "rule_settle_personal")

    # 发票
    for h in find_lines(pages, r"(?:价税合计|小写)[:：]?\s*[（(]?([\d,，.]+)"):
        amt = parse_amount(h.match.group(1))
        if amt and not any(e.scope == ExpenseScope.total for e in facts.expenses):
            add(h, ExpenseScope.total, amt, "rule_invoice_total")

    # 电子票据/费用清单：合计行（总费用兜底来源，取首个 >= 100 元的合计）
    if not any(e.scope == ExpenseScope.total for e in facts.expenses):
        for h in find_lines(pages, r"合计[:：]?\s*([\d,，.]{2,})",
                            {"inpatient_bill", "outpatient_bill", "invoice", "insurance_settlement"}):
            amt = parse_amount(h.match.group(1))
            if amt and amt >= 10000:
                add(h, ExpenseScope.total, amt, "rule_bill_total")
                break


def _build_events(case_id: str, facts: CaseFacts) -> list[MedicalEvent]:
    events: list[MedicalEvent] = []
    enc = facts.encounters[0] if facts.encounters else None
    enc_id = enc.encounter_id if enc else ""

    def date_iso(fv: FieldValue | None) -> tuple[dict | None, TimePrecision]:
        if not fv or not fv.value:
            return None, TimePrecision.unknown
        prec = TimePrecision.day if len(str(fv.value)) == 10 else TimePrecision.month
        return {"start": fv.value, "end": fv.value, "timezone": None}, prec

    if enc is not None:
        a, ap = date_iso(enc.admission_date)
        events.append(MedicalEvent(case_id=case_id, encounter_id=enc_id, event_type="admission",
                                   ref_id=enc.encounter_id, occurred_at=a, time_precision=ap, label="入院"))
        d, dp = date_iso(enc.discharge_date)
        events.append(MedicalEvent(case_id=case_id, encounter_id=enc_id, event_type="discharge",
                                   ref_id=enc.encounter_id, occurred_at=d, time_precision=dp, label="出院"))
    for dx in facts.diagnoses:
        events.append(MedicalEvent(case_id=case_id, encounter_id=dx.encounter_id, event_type="diagnosis",
                                   ref_id=dx.diagnosis_id, assertion=dx.assertion, label=dx.name.value or ""))
    for pr in facts.procedures:
        t, tp = date_iso(pr.performed_at)
        events.append(MedicalEvent(case_id=case_id, encounter_id=pr.encounter_id, event_type="procedure",
                                   ref_id=pr.procedure_id, occurred_at=t,
                                   time_precision=tp or TimePrecision.unknown, label=pr.name.value or ""))
    for med in facts.medications:
        events.append(MedicalEvent(case_id=case_id, encounter_id=med.encounter_id, event_type="medication",
                                   ref_id=med.medication_id, label=med.name.value or ""))
    return events
