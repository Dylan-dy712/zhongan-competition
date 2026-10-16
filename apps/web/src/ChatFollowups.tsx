import {useRef,useState} from 'react';
import type {ChatAnswer,PatientField} from './types';
import {distinctFollowupChoices} from './followupChoices';
import './chat-followups.css';

const fieldLabels:Record<PatientField,string>={followup_time:'复查时间',followup_location:'复查医院',
  medication:'用药情况',allergy:'过敏情况',recovery_status:'恢复情况'};

export default function ChatFollowups({answer,disabled,onSend}:{answer:ChatAnswer;disabled:boolean;onSend:(message:string)=>Promise<boolean>}) {
  const [selections,setSelections]=useState<Partial<Record<PatientField,string>>>({});
  const [drafts,setDrafts]=useState<Partial<Record<PatientField,string>>>({});
  const submitting=useRef(false);
  const questions=answer.clarification_questions||[];
  const suggestions=[...new Set(answer.suggested_questions||[])].slice(0,3);
  const responses=questions.map(question=>({field:question.field,value:selections[question.field]==='custom'
    ?drafts[question.field]?.trim():selections[question.field]==='unknown'?'我暂不确定，稍后再补充。':selections[question.field]}));
  const completed=responses.filter(response=>response.value).length;
  const message='我补充一下这次的就医信息：\n'+responses.map(response=>`${fieldLabels[response.field]}：${response.value||''}`).join('\n');
  const ready=completed===questions.length&&message.length<=4000;
  if(!questions.length&&!suggestions.length)return null;
  return <div className="chat-followups">
    {questions.length>0&&<section className="clarification-section" aria-label="补充就医信息">
      <h3><span aria-hidden="true">✦</span> 再了解一点，更好地陪你</h3>
      <form onSubmit={async event=>{
        event.preventDefault();if(disabled||submitting.current||!ready)return;
        submitting.current=true;
        try{if(await onSend(message)){setSelections({});setDrafts({});}}
        finally{submitting.current=false;}
      }}>
      {questions.map(question=><div className="clarification-question" key={question.field}>
        <p>{question.question}</p>
        <div className="clarification-choices">
          {distinctFollowupChoices(question.options).map((option,i)=><button type="button" key={i} disabled={disabled} aria-pressed={selections[question.field]===option.message}
            onClick={()=>setSelections(previous=>({...previous,[question.field]:option.message}))}>{option.label}</button>)}
          <button type="button" disabled={disabled} aria-pressed={selections[question.field]==='unknown'}
            onClick={()=>setSelections(previous=>({...previous,[question.field]:'unknown'}))}>暂不确定</button>
          <button type="button" disabled={disabled} aria-pressed={selections[question.field]==='custom'} aria-expanded={selections[question.field]==='custom'}
            onClick={()=>setSelections(previous=>({...previous,[question.field]:'custom'}))}>我来补充</button>
        </div>
        {selections[question.field]==='custom'&&<div className="clarification-form">
          <label>补充{fieldLabels[question.field]}<textarea value={drafts[question.field]||''} maxLength={1800} rows={2}
            placeholder="按你知道的情况填写，不确定也可以直接说"
            disabled={disabled} onChange={event=>setDrafts(previous=>({...previous,[question.field]:event.target.value}))}/></label>
        </div>}
      </div>)}
      <div className="clarification-submit"><small role="status">已补充 {completed}/{questions.length} 项</small>
        <button type="submit" disabled={disabled||!ready}>{disabled?'正在回复…':'提交补充'}</button></div>
      <small>选好或填好每一项后一起提交，暂不清楚的可选“暂不确定”。</small>
      </form>
    </section>}
    {suggestions.length>0&&<section className="suggested-section" aria-label="你可以接着问">
      <h3>你可以接着问</h3>
      <div className="suggested-questions">{suggestions.map(question=><button type="button" key={question} disabled={disabled} onClick={()=>void onSend(question)}><span>{question}</span><span aria-hidden="true">↗</span></button>)}</div>
    </section>}
  </div>;
}
