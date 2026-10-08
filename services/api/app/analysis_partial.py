"""Remove whole unverified points; never turn a rejected statement into a fact."""
import re

POINT=r'(?m)(?=^\s*\d{1,2}(?:[.)]\s+|[、）]\s*))'
def compact(text):return ''.join(text.replace('**','').split())

def verified_partial(text,issues,packed,aliases,refs):
    parts=re.split(POINT,text)
    bad=set()
    for issue in issues:
        quote=compact(issue.draft_quote)
        hits=[i for i,part in enumerate(parts) if quote and quote in compact(part)]
        if not hits:return None
        bad.update(hits)
    remaining=[part for i,part in enumerate(parts) if i not in bad and part.strip()]
    points=[part for part in remaining if re.match(r'^\s*\d{1,2}(?:[.)]\s+|[、）])',part)]
    if not points:return None
    # An explicit total can be retained as a literal quote, only when its exact
    # evidence is already among the reply's citations. Do not infer table columns.
    if any(issue.category=='payment' for issue in issues):
        existing={str(ref) for ref in refs}
        for page in packed:
            for alias,source in page['spans']:
                match=re.search(r'(?m)^[ \t]*(?:合计金额|医疗总费用|总金额)[ \t]*[:：][ \t]*\d+\.\d{2}(?:元)?',source)
                if match and aliases.get(alias) in existing:
                    raw=match.group(0)
                    if compact(raw) not in compact(''.join(points)):
                        points.append('1. **票据原文记录的金额**\n\n原文写到“'+raw+'”。这只是该票据的原文金额，其他支付明细暂不据此推断。\n')
                    break
            else:continue
            break
    ordered=[re.sub(r'^\s*\d{1,2}[.、）)]\s*',f'{i}. ',point.strip(),count=1) for i,point in enumerate(points,1)]
    notice='个别条目暂时无法与原文准确对应，我先保留能够核对的重点；有疑问的部分还需要查看原材料确认。'
    return notice+'\n\n'+'\n\n'.join(ordered)
