import {useState} from 'react';
import type {ChatAnswer,PatientField} from './types';
import './chat-followups.css';

const fieldLabels:Record<PatientField,string>={followup_time:'复查时间',followup_location:'复查医院',
  medication:'用药情况',allergy:'过敏情况',recovery_status:'恢复情况'};

export default function ChatFollowups({answer,disabled,onSend}:{answer:ChatAnswer;disabled:boolean;onSend:(message:string)=>Promise<boolean>}) {
  const [editing,setEditing]=useState<PatientField>();
  const [drafts,setDrafts]=useState<Partial<Record<PatientField,string>>>({});
  const questions=answer.clarification_questions||[];
  const suggestions=[...new Set(answer.suggested_questions||[])].slice(0,3);
  if(!questions.length&&!suggestions.length)return null;
  return <div className="chat-followups">
    {questions.length>0&&<section className="clarification-section" aria-label="补充就医信息">
      <h3><span aria-hidden="true">✦</span> 再了解一点，更好地陪你</h3>
      {questions.map(question=><div className="clarification-question" key={question.field}>
        <p>{question.question}</p>
        <div className="clarification-choices">
          {question.options.map((option,i)=><button type="button" key={i} disabled={disabled} onClick={()=>void onSend(option.message)}>{option.label}</button>)}
          <button type="button" disabled={disabled} aria-expanded={editing===question.field} onClick={()=>setEditing(editing===question.field?undefined:question.field)}>我来补充</button>
        </div>
        {editing===question.field&&<form className="clarification-form" onSubmit={async event=>{
          event.preventDefault();const value=drafts[question.field]?.trim();if(!value||disabled)return;
          if(await onSend(`我补充一下${fieldLabels[question.field]}：${value}`)){
            setDrafts(previous=>({...previous,[question.field]:''}));setEditing(undefined);
          }
        }}>
          <label>补充{fieldLabels[question.field]}<textarea value={drafts[question.field]||''} maxLength={3800} rows={2}
            placeholder="按你知道的情况填写，不确定也可以直接说"
            disabled={disabled} onChange={event=>setDrafts(previous=>({...previous,[question.field]:event.target.value}))}/></label>
          <button type="submit" disabled={disabled||!drafts[question.field]?.trim()}>发送补充</button>
        </form>}
      </div>)}
      <small>也可以直接在下方回复，暂时不清楚的先留着。</small>
    </section>}
    {suggestions.length>0&&<section className="suggested-section" aria-label="你可以接着问">
      <h3>你可以接着问</h3>
      <div className="suggested-questions">{suggestions.map(question=><button type="button" key={question} disabled={disabled} onClick={()=>void onSend(question)}><span>{question}</span><span aria-hidden="true">↗</span></button>)}</div>
    </section>}
  </div>;
}
