import type {ChatTurn} from './types';

export function currentNarrative(turns:ChatTurn[],runId?:string) {
  return runId ? [...turns].reverse().find(t=>t.input_kind==='analysis_ready'
    && t.status==='completed' && t.answer?.analysis_run_id===runId) : undefined;
}

export default function AnalysisNarrative({turn,onEvidence}:{turn:ChatTurn;onEvidence:(id:string)=>void}) {
  if(!turn.answer)return null;
  return <article className="analysis-narrative" aria-label="暖暖的材料解读">
    <div className="analysis-narrative-copy">
      {turn.answer.text.split(/\n\s*\n/).filter(p=>p.trim()).map((p,i)=><p key={i}>{p}</p>)}
    </div>
    {turn.answer.evidence_refs.length>0 && <details className="analysis-narrative-sources">
      <summary>这份解读的材料依据 <span>{turn.answer.evidence_refs.length}</span></summary>
      <div>{turn.answer.evidence_refs.map((id,i)=><button className="citation" key={id} onClick={()=>onEvidence(id)}>依据 {i+1} ↗</button>)}</div>
    </details>}
  </article>;
}
