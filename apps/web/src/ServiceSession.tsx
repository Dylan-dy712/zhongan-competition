import type {ServiceSession as Session} from './types';

export const departmentLabel=(session?:Session)=>session?.doctor_profile?.label||session?.title?.replace(/医生咨询$/,'')||'全科分诊';
function sourceHref(value:string){try{const url=new URL(value);return url.protocol==='https:'?url.href:undefined;}catch{return undefined;}}

export default function ServiceSession({session,onAsk,disabled=false,interactive=true}:{session:Session;
  onAsk:(message:string)=>Promise<boolean>;disabled?:boolean;interactive?:boolean}) {
  const confirm=session.phase==='awaiting_confirmation';
  const active=session.phase==='doctor_active';
  const ongoing=['collecting','awaiting_confirmation','doctor_active'].includes(session.phase);
  return <section className={`service-session service-session-${session.phase}`} aria-label="聊天内模拟服务">
    <header><strong>{session.phase==='booked'?'模拟预约已完成':active?`${departmentLabel(session)}医生 · AI模拟`:
      session.phase==='ended'?'已回到暖暖':session.phase==='blocked'?'先确认适合的就医方式':session.title}</strong>
      <span>模拟演示{session.mode==='doctor'?' · 无真人接入':''}</span></header>
    <p>{session.notice}</p>
    {!!session.paused_sessions?.length&&<p>已暂停并保留：{session.paused_sessions.map(item=>item.title).join('、')}。想继续时直接在聊天里告诉我。</p>}
    {session.mode==='doctor'&&session.doctor_profile&&<details className="service-doctor-scope"><summary>科室匹配与服务范围</summary>
      <p>{session.doctor_profile.scope_note}</p>
      {session.doctor_profile.condition_match&&<p>本次提到：{session.doctor_profile.condition_match.name}。
        {session.doctor_profile.condition_match.in_drug_benefit_list?'在药费直赔目录中找到同名条目，仍需核对服务与保单条件。':'未在这版药费直赔目录找到同名条目，不代表不能咨询。'}
        目录收录不代表可以线上确诊、开方或保证赔付。</p>}
      {session.doctor_profile.sources.map(source=><p key={source.url}>{sourceHref(source.url)&&<a href={sourceHref(source.url)} target="_blank" rel="noopener noreferrer">{source.title}{source.pages?` · 第${source.pages}页`:''}</a>}<br/>{source.product_scope}</p>)}
      <small>公开资料核对：{session.doctor_profile.verified_on}；未核实实时医生与号源。</small>
    </details>}
    {!!session.summary?.length&&<details open={confirm||session.phase==='booked'}><summary>本次需求摘要</summary>
      <dl>{session.summary.map(item=><div key={item.label}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}</dl></details>}
    {!!session.missing_fields?.length&&<p className="service-session-missing">还需了解：{session.missing_fields.slice(0,2).join('、')}</p>}
    {session.booking_reference&&<small>演示预约编号：{session.booking_reference}</small>}
    {session.phase==='booked'&&session.appointment&&<p>模拟安排：{session.appointment.city} · {session.appointment.venue}，{session.appointment.time}。使用人：{session.appointment.participant}。</p>}
    {interactive&&<div className="service-session-actions">
      {confirm&&session.confirmation_text&&<button disabled={disabled} onClick={()=>void onAsk(session.confirmation_text!)}>{session.confirmation_text}</button>}
      {ongoing&&<button className="service-session-return" disabled={disabled} onClick={()=>void onAsk('结束当前模拟服务，回到暖暖继续聊。')}>{active?'结束模拟咨询，回到暖暖':'取消本次模拟安排'}</button>}
    </div>}
  </section>;
}
