"""Bind final report paragraphs to the same authorized source packet."""
import json
from pydantic import Field
from .chat_reply import ChatParagraph,ParagraphReply,decode_chat_reply

class AnalysisParagraph(ChatParagraph):
    source_refs: list[str] = Field(default_factory=list,max_length=16)

class AnalysisParagraphReply(ParagraphReply):
    paragraphs: list[AnalysisParagraph] = Field(min_length=1,max_length=30)

INSTRUCTION = """
本轮最终JSON采用段落格式，替代前文text/citations及evidence_refs/knowledge_refs字段：
{"paragraphs":[{"text":"完整正文中的一段","source_refs":["支持该段的S编号或真实知识entry_id"]}],"history_refs":[],"clarification_questions":[],"suggested_questions":[],"patient_updates":[]}。
正文仍须完整讲清本次就医，保持前文要求的开头、编号主题、独立段落和接下来安排，按reading_requirements展开，不能压成摘要。
标题单独一段，source_refs为空；其下每段正文一到三句话，最多800字符，不跨行。不同依据的事实或解释分段，来源只关联到真正支持的那一段，最多16个，不复制全部来源；全篇最多80个病例S编号和8个不同知识entry_id。
病例事实引用本次原文S编号；一般知识解释引用实际给定的知识entry_id，不能把知识当个体诊断或处方。正文不写来源编号。
只写一次正文，不另写quote或citations；程序直接用这段原句生成引用位置。相同有来源的段落不要重复。原文核验仍须独立进行。history_refs为空，补问和追问规则保持不变。
"""


def decode_analysis_paragraphs(content,aliases):
    data=json.loads(content)
    if not isinstance(data,dict) or 'paragraphs' not in data:
        return data  # Legacy persisted replies retain their strict contract.
    wire=AnalysisParagraphReply.model_validate(data)
    plain='\n\n'.join(line.strip().replace('**','') for paragraph in wire.paragraphs
                      for line in paragraph.text.splitlines() if line.strip())
    # Unlike ordinary chat, never silently lose a report's explicit source link.
    for paragraph in wire.paragraphs:
        if paragraph.source_refs:
            for line in paragraph.text.splitlines():
                quote=line.strip().replace('**','')
                if len(quote)<2 or plain.count(quote)!=1:
                    raise ValueError('CITATION_ANCHOR_NOT_UNIQUE')
    reply=decode_chat_reply(content,paragraph_model=AnalysisParagraphReply)
    refs=list(dict.fromkeys([*reply['evidence_refs'],*reply['knowledge_refs']]))
    actual=set(aliases)|set(aliases.values())
    reply['evidence_refs']=[ref for ref in refs if ref in actual]
    reply['knowledge_refs']=[ref for ref in refs if ref not in actual]
    return reply
