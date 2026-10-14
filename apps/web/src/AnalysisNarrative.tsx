import type {ChatTurn} from './types';
import {narrativeBlocks,emphasisParts} from './narrativeFormatting';
import {CitedText} from './SourceCitations';

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
  const cited=(text:string)=><CitedText text={text} citations={turn.answer!.citations} sources={turn.answer!.knowledge_sources} onEvidence={onEvidence}/>;
  let number=0;
  return <article className="analysis-narrative" aria-label="暖暖的材料解读">
    <div className="analysis-narrative-copy">
      {blocks.map((block,i)=>block.kind==='point'
        ? <section className="analysis-narrative-point" key={i}>
            <span className="analysis-point-number" aria-label={`第 ${++number} 点`}>{number}</span>
            <div><p className="analysis-point-lead">{cited(block.text)}</p>
              {block.paragraphs.map((text,j)=><p key={j}>{cited(text)}</p>)}</div>
          </section>
        : block.kind==='closing'
          ? <section className="analysis-narrative-closing" key={i}>
              <h3>{block.text}</h3>
              {block.paragraphs.map((text,j)=><p key={j}>{cited(text)}</p>)}
            </section>
          : <p key={i}>{cited(block.text)}</p>)}
    </div>
    {turn.answer.guidance_delivery?.status!=='passed' && turn.answer.guidance_delivery?.notice &&
      <p className="muted analysis-reading-notice" role="note">{turn.answer.guidance_delivery.notice}</p>}
    {!turn.answer.citations?.length && turn.answer.evidence_refs.length>0 && <small className="muted">此历史解读尚无逐条引用，可重新分析材料以生成带来源角标的解读。</small>}
  </article>;
}
