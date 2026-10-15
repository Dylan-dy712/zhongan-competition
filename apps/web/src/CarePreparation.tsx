import materialsArt from '../../../output_dir/product-design/assets/onboard-materials.webp';
import consentArt from '../../../output_dir/product-design/assets/onboard-consent.webp';
import type {ClaimFile} from './claimTemplate';
import './care-preparation.css';

type Props={
  stage:'materials'|'consent';date:string;files:ClaimFile[];supplements:ClaimFile[];
  uploaded:(file:ClaimFile)=>boolean;busy:boolean;locked:boolean;agreed:boolean;
  onAgree:(value:boolean)=>void;onBack:()=>void;onHome:()=>void;onNext:()=>void;onConfirm:()=>void;
  onPick:()=>void;onRemove:(file:ClaimFile)=>void;onPreview:(file:ClaimFile)=>void;
};

function FileIcon(){return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M6 3h9l4 4v14H6V3Z"/><path d="M15 3v5h4M9 12h6M9 16h4"/></svg>;}

export default function CarePreparation(p:Props){
  const consent=p.stage==='consent';
  const row=(file:ClaimFile,supplement=false)=><li key={file.id}>
    <button className="care-material-file" onClick={()=>p.onPreview(file)} aria-label={`查看${file.name}`}>
      <span className="care-document-icon">{file.url?<img src={file.url} alt=""/>:<FileIcon/>}</span>
      <span className="care-file-copy"><strong>{file.name}</strong><small>{p.uploaded(file)?'已上传，可直接使用':'确认后上传'} · {Math.ceil(file.size/1024)} KB</small></span>
      <span className="care-file-arrow" aria-hidden="true">›</span>
    </button>
    {supplement&&!p.uploaded(file)&&<button className="care-file-remove" disabled={p.busy||p.locked} onClick={()=>p.onRemove(file)} aria-label={`移除${file.name}`}>移除</button>}
  </li>;
  return <section className="care-preparation" aria-label={consent?'知情同意与隐私说明':'这次看病的资料'}>
    <header className="care-preparation-header"><button onClick={p.onBack} disabled={p.busy} aria-label={consent?'返回资料清单':'返回提交结果'}>‹</button><strong>{consent?'资料怎么使用':'这次看病的资料'}</strong><span/></header>
    <div className="care-preparation-scroll" key={p.stage}>
      <img className="care-preparation-art" src={consent?consentArt:materialsArt} alt=""/>
      {!consent?<section className="care-preparation-card">
        <h1>这 {p.files.length} 份，不用再传了</h1>
        <p className="care-preparation-episode">{p.date} · 本次就医资料</p>
        <ul className="care-material-list" aria-label="已上传材料">{p.files.map(file=>row(file))}</ul>
        <p>还有后来拿到的资料？可以一起补充。没有也可以直接继续。</p>
        {!!p.supplements.length&&<><h2>补充的资料 · {p.supplements.length} 份</h2><ul className="care-material-list" aria-label="补充材料">{p.supplements.map(file=>row(file,true))}</ul></>}
        <button className="care-outline" onClick={p.onPick} disabled={p.busy||p.locked}>＋ 补充看病资料</button>
        <small className="care-preparation-note">支持 PDF / JPG / PNG，每份不超过 10 MB。补充资料可在确认上传前移除。</small>
        <button className="care-primary" onClick={p.onNext} disabled={p.busy}>带着这些资料问暖暖</button>
        <small className="care-preparation-note">下一步了解资料用途与隐私说明，确认后开始解读。</small>
      </section>:<section className="care-preparation-card care-privacy-card">
        <span className="care-preparation-eyebrow">就医关怀 · 由你决定</span>
        <h1>让暖暖结合资料，<br/>把这次就医讲清楚</h1>
        <p>将使用已上传的 {p.files.length} 份资料{p.supplements.length?`与补充的 ${p.supplements.length} 份资料`:''}，以及你核对的就医信息。</p>
        <div className="care-privacy-item"><span>01</span><div><h2>用来做什么</h2><p>识别材料、整理就医经过与费用，生成解读，并梳理后续就医与关怀事项。</p></div></div>
        <div className="care-privacy-item"><span>02</span><div><h2>资料与隐私</h2><p>病历可能包含姓名、病情等敏感信息。文件会上传并保存至当前关怀账号，相关内容会交由提供识别与解读的服务处理。</p><details><summary>查看服务与资料管理说明</summary><p>材料识别由火山引擎提供，报告解读由百度千帆提供。请只提交本人或已获授权的资料，避免添加无关个人信息。你可在“我的”中管理资料用途授权；撤回后停止后续分析，已保存的材料和对话不会因此自动删除。</p></details></div></div>
        <div className="care-privacy-item"><span>03</span><div><h2>知情后再开始</h2><p>解读供理解材料与就医准备参考，不能代替医生诊疗或保险公司的审核结论。就医关怀为自愿使用，可以暂不开始。</p></div></div>
        <label className="care-agreement"><input type="checkbox" checked={p.agreed} disabled={p.busy||p.locked} onChange={e=>p.onAgree(e.target.checked)}/><span>我已阅读并了解资料用途与隐私说明，同意使用上述资料进行识别和报告解读。</span></label>
        <button className="care-primary" disabled={!p.agreed||p.busy} onClick={p.onConfirm}>{p.busy?'正在提交…':p.locked?'重试解读':'确认提交，开始解读'}</button>
        <button className="care-later" onClick={p.onHome} disabled={p.busy}>暂不解读，返回首页</button>
      </section>}
    </div>
  </section>;
}
