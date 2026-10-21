import {useState} from 'react';
import type {MedicalServiceCard,MedicalServices} from './types';
import benefitSmall from './assets/medical-services/benefit-v1-384.webp';
import benefitLarge from './assets/medical-services/benefit-v1-768.webp';
import hospitalSmall from './assets/medical-services/hospital-v1-384.webp';
import hospitalLarge from './assets/medical-services/hospital-v1-768.webp';
import onlineSmall from './assets/medical-services/online-v1-384.webp';
import onlineLarge from './assets/medical-services/online-v1-768.webp';
import './medical-services.css';

type Ask=(message:string)=>Promise<boolean>;
const serviceArtwork={benefit:[benefitSmall,benefitLarge],hospital:[hospitalSmall,hospitalLarge],online:[onlineSmall,onlineLarge]};

function ServiceArtwork({kind}:{kind:MedicalServiceCard['kind']}) {
  const [small,large]=serviceArtwork[kind];
  return <figure className="medical-card-visual">
    <img src={small} srcSet={`${small} 384w, ${large} 768w`}
      sizes="(max-width:620px) calc(100vw - 64px), (max-width:1000px) 45vw, 384px"
      width={768} height={384} loading="lazy" decoding="async" alt=""/>
    <figcaption>{kind==='hospital'?'就医场景示意':kind==='online'?'在线服务示意':'权益服务示意'}</figcaption>
  </figure>;
}

function ServiceIcon({kind}:{kind:MedicalServiceCard['kind']}) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {kind==='benefit'?<><path d="M12 3 4.5 6v6c0 4.6 7.5 9 7.5 9s7.5-4.4 7.5-9V6L12 3Z"/><path d="m8.5 12 2.4 2.4 4.6-4.8"/></>:kind==='hospital'?<><path d="M5 21V5h14v16M3 21h18M9 21v-5h6v5M9 9h6m-3-3v6"/></>:<><rect x="3" y="4" width="18" height="13" rx="3"/><path d="M8 21h8m-4-4v4m-3-11h6m-3-3v6"/></>}
  </svg>;
}

export function ReportServiceGuide(_props:{text?:string;onAsk?:Ask;disabled?:boolean}) {
  return <p className="medical-guide-note">需要下一步的就医帮助，也可以问我</p>;
}

function sourceUrl(value:string){try{const url=new URL(value);return url.protocol==='https:'?url.href:undefined;}catch{return undefined;}}

export default function MedicalServiceCards({services,onAsk,disabled=false,canAskForLocation=true}:{services:MedicalServices;onAsk:Ask;disabled?:boolean;canAskForLocation?:boolean}) {
  const [location,setLocation]=useState('');
  if(services.status==='urgent')return <aside className="medical-urgent" role="note"><strong>先及时就医</strong><p>{services.notice}</p></aside>;
  return <section className="medical-services" aria-label="为你整理的医疗服务">
    <header className="medical-services-header"><div><span className="medical-eyebrow">把下一步，安排得轻松一点</span><h3>适合继续了解的服务</h3></div><span className="medical-policy-tag">{services.policy_label}</span></header>
    {services.notice&&<p className="medical-card-notice" role="note">{services.notice}</p>}
    {services.clinical_prompt&&<p className="medical-card-notice" role="note">{services.clinical_prompt}</p>}
    {services.cards.length>0&&<div className="medical-card-grid">{services.cards.map(card=><article className={`medical-service-card medical-service-${card.kind}`} key={card.id}>
      {card.kind==='hospital'&&<ServiceArtwork kind={card.kind}/>}
      <div className="medical-card-top"><span className="medical-service-symbol"><ServiceIcon kind={card.kind}/></span><small>{card.subtitle}</small></div>
      <h4>{card.title}</h4><p className="medical-card-description">{card.description}</p>
      <div className="medical-card-tags">{card.tags.map(tag=><span key={tag}>{tag}</span>)}</div>
      <ul className="medical-reasons">{card.reasons.map(reason=><li key={reason}>{reason}</li>)}</ul>
      <details className="medical-card-source"><summary>使用条件与来源</summary>{card.details.map(item=><p key={item.label}><strong>{item.label}：</strong>{item.value}</p>)}
        {sourceUrl(card.source.url)&&<a href={sourceUrl(card.source.url)} target="_blank" rel="noopener noreferrer">{card.source.title}{card.source.pages?` · 第${card.source.pages}页`:''} ↗</a>}
        {card.source.address_url&&sourceUrl(card.source.address_url)&&<p><a href={sourceUrl(card.source.address_url)} target="_blank" rel="noopener noreferrer">医院官网位置资料 ↗</a></p>}</details>
      <small className="medical-card-notice">{card.notice}</small>
      <button type="button" className="medical-card-action" disabled={disabled||!canAskForLocation} onClick={()=>void onAsk(card.kind==='benefit'?`我想在当前聊天预约${card.title}，请帮我问清需求并完成模拟预约。`:card.kind==='online'?'我想在当前聊天咨询医生，请先了解我的病情和医生偏好，再模拟接入医生。':`请在当前聊天帮我整理${card.title}的就医需求和准备事项。`)}>{card.kind==='benefit'?'让暖暖帮我预约':card.kind==='online'?'在这里咨询医生':'在这里安排就医'}<span aria-hidden="true">→</span></button>
    </article>)}</div>}
    {services.location_prompt&&canAskForLocation&&<form className="medical-location" onSubmit={async e=>{e.preventDefault();if(!location.trim()||disabled)return;const sent=await onAsk(`这次我想在${location.trim()}就医，请接着刚才的需求看看附近的医疗机构。`);if(sent)setLocation('');}}>
      <label><strong>先告诉我这次的就医地区</strong><span>{services.location_prompt}</span><input aria-label="本次就医地区" value={location} maxLength={80} disabled={disabled} placeholder="例如：上海市浦东新区，或附近地标" onChange={e=>setLocation(e.target.value)}/></label>
      <button type="submit" disabled={disabled||!location.trim()}>按这个地区找找</button>
    </form>}
    <p className="medical-policy-note">{services.policy_notice}</p>
  </section>;
}
