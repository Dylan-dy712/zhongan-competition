import type {ChatTurn} from './types';
import {narrativeBlocks,emphasisParts} from './narrativeFormatting';
import KnowledgeSources from './KnowledgeSources';

export function Emphasis({text}:{text:string}) {
  return <>{emphasisParts(text).map((part,i)=>part.strong?<strong key={i}>{part.text}</strong>:part.text)}</>;
}

export function currentNarrative(turns:ChatTurn[],runId?:string) {
  return runId ? [...turns].reverse().find(t=>t.input_kind==='analysis_ready'
    && t.status==='completed' && t.answer?.analysis_run_id===runId) : undefined;
}

export default function AnalysisNarrative({turn,onEvidence}:{turn:ChatTurn;onEvidence:(id:string)=>void}) {
  if(!turn.answer)return null;
  const blocks=narrativeBlocks(turn.answer.text);
  let number=0;
  return <article className="analysis-narrative" aria-label="暖暖的材料解读">
    <div className="analysis-narrative-copy">
      {blocks.map((block,i)=>block.kind==='point'
        ? <section className="analysis-narrative-point" key={i}>
            <span className="analysis-point-number" aria-label={`第 ${++number} 点`}>{number}</span>
            <div><p className="analysis-point-lead">{block.legacyLead?<strong>{block.text}</strong>:<Emphasis text={block.text}/>}</p>
              {block.paragraphs.map((text,j)=><p key={j}><Emphasis text={text}/></p>)}</div>
          </section>
        : block.kind==='closing'
          ? <section className="analysis-narrative-closing" key={i}>
              <h3>{block.text}</h3>
              {block.paragraphs.map((text,j)=><p key={j}><Emphasis text={text}/></p>)}
            </section>
          : <p key={i}><Emphasis text={block.text}/></p>)}
    </div>
    {turn.answer.evidence_refs.length>0 && <details className="analysis-narrative-sources">
      <summary>这份解读的材料依据 <span>{turn.answer.evidence_refs.length}</span></summary>
      <div>{turn.answer.evidence_refs.map((id,i)=><button className="citation" key={id} onClick={()=>onEvidence(id)}>依据 {i+1} ↗</button>)}</div>
    </details>}
    <KnowledgeSources sources={turn.answer.knowledge_sources}/>
  </article>;
}
