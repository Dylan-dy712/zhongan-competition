import {useEffect,useId,useRef,useState} from 'react';
import type {MedicalServiceCard,MedicalServices} from './types';
import reading from '../../../output_dir/product-design/assets/nuan-reading-v1.webp';
import benefitSmall from './assets/medical-services/benefit-v1-384.webp';
import benefitLarge from './assets/medical-services/benefit-v1-768.webp';
import hospitalSmall from './assets/medical-services/hospital-v1-384.webp';
import hospitalLarge from './assets/medical-services/hospital-v1-768.webp';
import onlineSmall from './assets/medical-services/online-v1-384.webp';
import onlineLarge from './assets/medical-services/online-v1-768.webp';
import './medical-services.css';

type Ask=(message:string)=>Promise<boolean>;
const invitation='如果你想了解保单里的医疗增值服务，或想找适合复查的医院、在线咨询的医生，也可以继续问我，我陪你一起看看。';
const guideActions=[['看看我的医疗权益','我想了解中高端保单里有哪些医疗增值权益适合我，请结合刚才的情况推荐。'],
  ['找复查医院','我想找适合这次复查的公立或私立医院，请结合已提供的就医地区看看附近的选择，缺少地区时再问我。'],
  ['了解在线咨询','请结合我的情况，介绍众安互联网医院有哪些适合的在线咨询服务。']];
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

export function ReportServiceGuide({text=invitation,onAsk,disabled=false}:{text?:string;onAsk?:Ask;disabled?:boolean}) {
  return <aside className="medical-guide" aria-label="解读后的医疗服务引导">
    <img src={reading} alt=""/>
    <div className="medical-guide-copy"><span className="medical-eyebrow">关怀，还可以多走一步</span>
      <h3>需要下一步的就医帮助，也可以问我</h3><p>{text}</p>
      <div className="medical-guide-actions">{guideActions.map(([label,message])=><button type="button" key={label} disabled={disabled||!onAsk} onClick={()=>void onAsk?.(message)}>{label}<span aria-hidden="true">↗</span></button>)}</div>
    </div>
  </aside>;
}

function ServicePreview({card,onClose,onAsk,disabled}:{card:MedicalServiceCard;onClose:()=>void;onAsk:Ask;disabled:boolean}) {
  const dialog=useRef<HTMLDialogElement>(null),titleId=useId();
  useEffect(()=>{const previous=document.activeElement as HTMLElement|null;dialog.current?.showModal();return()=>{dialog.current?.close();previous?.focus?.();};},[]);
  const steps=card.kind==='online'?['选择就诊人，查看可用保单权益','整理既往病历、检查报告和想问医生的问题','由医生评估复诊条件，再按实际页面发起咨询']:
    card.kind==='hospital'?['确认具体院区、复查科室和就诊时间','核对保单适用部门、费用及陪诊等可用服务','通过官方渠道预约，携带原有病历和检查报告前往']:
    ['查看本人保单对应的服务清单','确认等待期、剩余次数、互斥套餐及服务地区','向服务方申请，经核验后确认时间和安排'];
  const ask=card.kind==='hospital'?`我想进一步了解${card.title}是否适合我这次复查，以及去之前需要准备什么。`:
    card.kind==='online'?'使用众安互联网医院在线咨询前，我应该整理哪些资料和问题？':`我想进一步了解${card.title}的使用条件和需要准备的材料。`;
  return <dialog ref={dialog} className="medical-preview" aria-labelledby={titleId} onCancel={e=>{e.preventDefault();onClose();}}>
    <header><div><span className="medical-eyebrow">服务体验 · 模拟跳转</span><h2 id={titleId}>{card.title}</h2></div><button type="button" className="medical-close" onClick={onClose} aria-label="关闭服务体验">×</button></header>
    <div className="medical-preview-notice">这里是服务使用方式的演示，尚未发起真实预约、问诊、支付或资料传送。</div>
    <p className="medical-preview-description">{card.description}</p>
    <ol className="medical-preview-steps">{steps.map((step,i)=><li key={step}><span>{i+1}</span><p>{step}</p></li>)}</ol>
    <div className="medical-preview-details">{card.details.map(item=><div key={item.label}><strong>{item.label}</strong><p>{item.value}</p></div>)}</div>
    <p className="medical-card-notice">{card.notice}</p>
    <footer><button type="button" className="medical-primary" disabled={disabled} onClick={()=>{onClose();void onAsk(ask);}}>让暖暖帮我准备</button><button type="button" className="medical-secondary" onClick={onClose}>返回对话</button></footer>
  </dialog>;
}

function sourceUrl(value:string){try{const url=new URL(value);return url.protocol==='https:'?url.href:undefined;}catch{return undefined;}}

export default function MedicalServiceCards({services,onAsk,disabled=false,canAskForLocation=true}:{services:MedicalServices;onAsk:Ask;disabled?:boolean;canAskForLocation?:boolean}) {
  const [selected,setSelected]=useState<MedicalServiceCard|null>(null),[location,setLocation]=useState('');
  if(services.status==='urgent')return <aside className="medical-urgent" role="note"><strong>先及时就医</strong><p>{services.notice}</p></aside>;
  return <section className="medical-services" aria-label="为你整理的医疗服务">
    <header className="medical-services-header"><div><span className="medical-eyebrow">把下一步，安排得轻松一点</span><h3>适合继续了解的服务</h3></div><span className="medical-policy-tag">{services.policy_label}</span></header>
    {services.cards.length>0&&<div className="medical-card-grid">{services.cards.map(card=><article className={`medical-service-card medical-service-${card.kind}`} key={card.id}>
      <ServiceArtwork kind={card.kind}/>
      <div className="medical-card-top"><span className="medical-service-symbol"><ServiceIcon kind={card.kind}/></span><small>{card.subtitle}</small></div>
      <h4>{card.title}</h4><p className="medical-card-description">{card.description}</p>
      <div className="medical-card-tags">{card.tags.map(tag=><span key={tag}>{tag}</span>)}</div>
      <ul className="medical-reasons">{card.reasons.map(reason=><li key={reason}>{reason}</li>)}</ul>
      <details className="medical-card-source"><summary>使用条件与来源</summary>{card.details.map(item=><p key={item.label}><strong>{item.label}：</strong>{item.value}</p>)}
        {sourceUrl(card.source.url)&&<a href={sourceUrl(card.source.url)} target="_blank" rel="noopener noreferrer">{card.source.title}{card.source.pages?` · 第${card.source.pages}页`:''} ↗</a>}
        {card.source.address_url&&sourceUrl(card.source.address_url)&&<p><a href={sourceUrl(card.source.address_url)} target="_blank" rel="noopener noreferrer">医院官网位置资料 ↗</a></p>}</details>
      <small className="medical-card-notice">{card.notice}</small>
      <button type="button" className="medical-card-action" disabled={disabled} onClick={()=>setSelected(card)}>{card.action.label}<span aria-hidden="true">↗</span></button>
    </article>)}</div>}
    {services.location_prompt&&canAskForLocation&&<form className="medical-location" onSubmit={async e=>{e.preventDefault();if(!location.trim()||disabled)return;const sent=await onAsk(`这次我想在${location.trim()}就医，请接着刚才的需求看看附近的医疗机构。`);if(sent)setLocation('');}}>
      <label><strong>先告诉我这次的就医地区</strong><span>{services.location_prompt}</span><input aria-label="本次就医地区" value={location} maxLength={80} disabled={disabled} placeholder="例如：上海市浦东新区，或附近地标" onChange={e=>setLocation(e.target.value)}/></label>
      <button type="submit" disabled={disabled||!location.trim()}>按这个地区找找</button>
    </form>}
    <p className="medical-policy-note">{services.policy_notice}</p>
    {selected&&<ServicePreview card={selected} onClose={()=>setSelected(null)} onAsk={onAsk} disabled={disabled}/>}
  </section>;
}
