export type NarrativeBlock = {kind:'paragraph'|'point';text:string;paragraphs:string[]};

// A deliberately small text format: numbered points and **emphasis** only.
// HTML, links and arbitrary Markdown remain text and cannot create DOM nodes.
export function narrativeBlocks(text:string):NarrativeBlock[] {
  const chunks=text.trim().split(/\n\s*\n/).filter(Boolean);
  const blocks:NarrativeBlock[]=[];
  let point:NarrativeBlock|undefined;
  for(const chunk of chunks) {
    const lines=chunk.split('\n');
    for(const line of lines) {
      const match=line.match(/^\s*\d{1,2}(?:[.)]\s+|[、）]\s*)(.+)$/);
      if(match) {
        point={kind:'point',text:match[1],paragraphs:[]};blocks.push(point);
      } else if(point) {
        if(line.trim())point.paragraphs.push(line);
      } else if(line.trim()) {
        const last=blocks.at(-1);
        if(last?.kind==='paragraph' && lines.length>1)last.text+='\n'+line;
        else blocks.push({kind:'paragraph',text:line,paragraphs:[]});
      }
    }
    // Plain historic reports get numbered paragraphs without changing any words.
  }
  if(!blocks.some(b=>b.kind==='point') && blocks.length>2) {
    return blocks.map((b,i)=>i>0 && !(i===blocks.length-1 && /[？?]\s*$/.test(b.text))
      ? {...b,kind:'point'}:b);
  }
  return blocks;
}

export function emphasisParts(text:string):{text:string;strong:boolean}[] {
  const result:{text:string;strong:boolean}[]=[];
  const expression=/\*\*([^*\n]{1,100})\*\*/g;
  let start=0;
  for(const match of text.matchAll(expression)) {
    const index=match.index!;
    result.push({text:text.slice(start,index),strong:false});
    // Keep qualifiers visible when a historic answer emphasizes only the noun.
    const prefix=text.slice(Math.max(0,index-12),index);
    result.push({text:match[1],strong:!/(?:不能排除|疑似|未见|否认|既往|待排|不支持|无)\s*$/.test(prefix)});
    start=index+match[0].length;
  }
  result.push({text:text.slice(start),strong:false});
  return result;
}
