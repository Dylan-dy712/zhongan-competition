import {useEffect,useId,useRef} from 'react';

export default function SamplePreparationDialog({open,loading,completed,total,error,onRetry,onHome}:{open:boolean;loading:boolean;completed:number;total:number;error:string;onRetry:()=>void;onHome:()=>void}){
  const dialog=useRef<HTMLDialogElement>(null),title=useId(),description=useId();
  useEffect(()=>{
    const node=dialog.current;if(!node||!open)return;
    const previous=document.activeElement as HTMLElement|null;
    if(!node.open)node.showModal();
    return()=>{if(node.open)node.close();if(previous?.isConnected)previous.focus();};
  },[open]);
  return <dialog ref={dialog} className="sample-preparation-dialog" aria-labelledby={title} aria-describedby={description} onCancel={event=>{event.preventDefault();onHome();}}>
    <div className={`sample-preparation-icon ${error?'failed':''}`} aria-hidden="true">{error?'!':<svg viewBox="0 0 40 40" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 6h13l6 6v22H12V6Z"/><path d="M25 6v7h6M17 20h9M17 26h6M7 12v19"/></svg>}</div>
    <h2 id={title}>{error?'资料准备暂时中断':'正在准备体验资料'}</h2>
    <p id={description}>{error?'申请信息已保留，可以重新准备材料。':'申请信息已填好，材料准备完成后会自动返回申请页面。'}</p>
    {loading&&<div className="sample-preparation-progress" role="status" aria-live="polite"><div><span>正在准备示例材料</span><strong>{completed}<small> / {total}</small></strong></div><progress value={completed} max={total} aria-label="示例材料准备进度"/><small>请稍候，准备完成后即可核对并提交</small></div>}
    {error&&<><p className="sample-preparation-error" role="alert">{error}</p><button className="sample-preparation-retry" onClick={onRetry}>重新准备示例资料</button></>}
    <button className="sample-preparation-home" onClick={onHome}>先返回首页</button>
  </dialog>;
}
