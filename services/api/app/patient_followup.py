"""Structured, optional conversation follow-ups and source-preserving patient statements."""
from typing import Literal
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator


PatientField = Literal['followup_time', 'followup_location', 'medication', 'allergy', 'recovery_status']


class QuestionChoice(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=24)
    message: str = Field(min_length=1, max_length=200)


def choice_key(value: str) -> str:
    # Preserve internal punctuation and signs that can change a medical answer.
    value = re.sub(r'\s+', '', unicodedata.normalize('NFKC', value))
    return re.sub(r'[。！？!?，,；;：:、.]+$', '', value).lower()


UNCERTAINTY_CHOICE = re.compile(
    r'(?:我)?(?:目前|现在)?(?:还|暂时|暂|尚)?'
    r'(?:不太?确定|不太?清楚|不知道|不记得|记不清楚?|没确定|未确定|无法确定|想不起来)'
    r'(?:具体)?(?:复查时间|复查医院|用药情况|过敏情况|恢复情况|时间|医院|药名|过敏史)?(?:了)?')
CUSTOM_CHOICES = {'我来补充', '我想补充', '自行填写', '手动填写', '自己填写', '其他', '其他情况'}


class ClarificationQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    field: PatientField
    question: str = Field(min_length=1, max_length=200)
    options: list[QuestionChoice] = Field(default_factory=list, max_length=3)

    @field_validator('options')
    @classmethod
    def distinct_choices(cls, values):
        # The UI supplies one uncertainty button and one free-text entry itself.
        labels, messages, result = set(), set(), []
        for option in values:
            label, message = choice_key(option.label), choice_key(option.message)
            if (UNCERTAINTY_CHOICE.fullmatch(label) or label in CUSTOM_CHOICES
                    or label in labels or message in messages):
                continue
            labels.add(label)
            messages.add(message)
            result.append(option)
        return result


class PatientUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    field: PatientField
    statement: str = Field(min_length=2, max_length=4000)


class FollowupPayload(BaseModel):
    clarification_questions: list[ClarificationQuestion] = Field(default_factory=list, max_length=2)
    suggested_questions: list[str] = Field(default_factory=list, max_length=3)
    patient_updates: list[PatientUpdate] = Field(default_factory=list, max_length=5)

    @field_validator('suggested_questions')
    @classmethod
    def clean_suggestions(cls, values):
        if any(not value.strip() or len(value.strip()) > 200 for value in values):
            raise ValueError('Questions must contain 1 to 200 characters')
        return list(dict.fromkeys(value.strip() for value in values))

    @field_validator('clarification_questions')
    @classmethod
    def distinct_fields(cls, values):
        return list({question.field: question for question in values}.values())


def source_patient_updates(updates, question):
    """Keep the entire actual user message, including negation and uncertainty.

    These are self-reports, never extracted medical facts or prescriptions.
    A model cannot save a shortened quote, report text or an invented value.
    """
    return list({item.field: item.model_dump() for item in updates
                 if item.statement == question.strip()}.values())


FOLLOWUP_INSTRUCTION = """
同时返回 clarification_questions、suggested_questions、patient_updates 三个数组；不需要时用空数组。
clarification_questions 是你主动向用户补问的实际信息缺口，不是让用户问你的问题。报告生成时检查与本次资料相关的复查时间、复查医院、目前用药、过敏或恢复情况；优先问最影响后续安排的1项，最多2项。
每项包含field（followup_time/followup_location/medication/allergy/recovery_status之一）、question、options。
options最多3项，每项含label（24字以内）和message（200字以内，完整第一人称回答，用户选好各项后统一提交）。各项含义须有区别，不用同义改写凑选项；界面统一提供“暂不确定”和“我来补充”，不要再生成“还不确定”“暂不清楚”“不知道”等通用不确定选项或“其他/自行填写”入口。可给含义不同的“医生还没交代”等如实表态选项，没有合适选项时options用空数组。只有材料或用户已给出的选项才可涉及具体药物、剂量或时间；未给复查时间时不能提供“一周后/一月后”等推测选项。
仅询问当前有必要确认、材料和用户尚未说清的事，不为凑数问所有缺失字段。已明确或刚刚回答的信息不重复问；用户说不确定或暂不补充就先保留不确定，不立即追问同一项。OCR未识别、未读完不等于用户没提供。不要在正文重复列出这些补问。
suggested_questions 是用户可以继续问你的2到3条问题，每条200字以内，贴合本轮报告或回答，如实际术语解释、已有医嘱的注意事项或票据口径。以用户口吻写完整问句，避免重复，不预设不存在的异常、药物或自费项目，不承诺诊断、处方或赔付。仅有寒暄、处理中或无具体内容时用空数组。
patient_updates仅在当前用户明确补充自己的复查、用药、过敏或恢复信息时填写；每项含field和statement。statement必须逐字等于当前用户消息全文（保留否定、提问、未定和时间限定），最多4000字。问句、假设、示例、他人情况、报告内容和你生成的选项都不能作为已补充信息。纯追问不得生成patient_updates。分析续答的系统请求不得生成patient_updates。
用户可能把多项补充合并为一条消息，逐项识别本条明确说明的字段，一次综合回应；每个字段的statement仍保存本条消息全文。标为暂不确定或稍后补充的字段保留不确定，不改成确定的安排。
patient_context中的内容只是带时间和就医范围的用户自述；可以用来避免重复提问和接续交流，不能覆盖病历、当作核实事实或把以前的用药当作当前处方。后来的更正优先，仍须保留自述身份。不得声称已安排复查或自动生成用药提醒。
"""
