"""Compile the user's reference cost documents into deterministic local chunks."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def split_content(text, max_chars=900):
    heading = ''
    body = []
    for line in text.splitlines():
        if re.match(r'^#{1,4} ', line):
            if body:
                yield heading, '\n'.join(body).strip()
            heading = line.lstrip('# ').strip()
            body = []
        elif line.strip():
            if sum(len(x)+1 for x in body)+len(line)>max_chars and body:
                yield heading, '\n'.join(body).strip()
                body=[]
            # Bound oversized paragraphs while preserving every character.
            for start in range(0, len(line), max_chars):
                part=line[start:start+max_chars]
                if body and sum(len(x)+1 for x in body)+len(part)>max_chars:
                    yield heading, '\n'.join(body).strip();body=[]
                body.append(part)
    if body:
        yield heading, '\n'.join(body).strip()


def main():
    chunks=[]
    for path in sorted((ROOT/'docs/medical/费用与发票知识库').glob('*.md')):
        if not re.match(r'^\d{2}-', path.name):
            continue
        text=path.read_text(encoding='utf-8')
        sources=list(dict.fromkeys(re.findall(r'https?://[^\s<>）)]+',text)))
        for index,(heading,body) in enumerate(split_content(text),1):
            chunks.append({'entry_id':f'COST-DOC-{path.name[:2]}-{index:03d}',
                           'title':heading or path.stem,'content':body,
                           'source':'；'.join(sources) or '用户提供的费用与发票专业资料',
                           'source_path':path.relative_to(ROOT).as_posix(),
                           'disease_code':'TY','scope':'费用与票据的一般解释；地区政策、保单和年份须另行核对',
                           'anchoring':'票据原始标签或用户实际问题','status':'user-authorized-reference',
                           'numeric_pending_review':False})
    raw=('\n'.join(json.dumps(c,ensure_ascii=False,separators=(',',':')) for c in chunks)+'\n').encode('utf-8')
    target=ROOT/'contracts/knowledge'
    (target/'rag-cost-chunks.jsonl').write_bytes(raw)
    (target/'rag-build-report.json').write_text(json.dumps({'chunks_total':len(chunks),
        'content_sha256':hashlib.sha256(raw).hexdigest(),'reference_policy':'user-authorized-reference-v1'},indent=2)+'\n',encoding='utf-8')
    print(f'RAG_COST_CORPUS_BUILT chunks={len(chunks)}')


if __name__=='__main__':main()
