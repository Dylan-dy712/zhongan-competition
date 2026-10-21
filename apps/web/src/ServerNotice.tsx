import {useEffect,useId,useRef,useState} from 'react';
import './server-notice.css';

const dismissalKey='zhongan_server_notice_dismissed';

export default function ServerNotice(){
  const [dismissed,setDismissed]=useState(()=>{
    try{return sessionStorage.getItem(dismissalKey)==='1';}catch{return false;}
  });
  const dialog=useRef<HTMLDialogElement>(null);
  const title=useId(),description=useId();
  useEffect(()=>{
    const node=dialog.current;if(!node||dismissed)return;
    const previous=document.activeElement as HTMLElement|null;
    node.showModal();
    return()=>{if(node.open)node.close();if(previous?.isConnected)previous.focus();};
  },[dismissed]);
  const dismiss=()=>{
    try{sessionStorage.setItem(dismissalKey,'1');}catch{/* Keep closing available if storage is unavailable. */}
    setDismissed(true);
  };
  if(dismissed)return null;
  return <dialog ref={dialog} className="server-notice" aria-labelledby={title} aria-describedby={description}
    onCancel={event=>{event.preventDefault();dismiss();}}>
    <button type="button" className="server-notice-close" aria-label="关闭温馨提示" onClick={dismiss}>×</button>
    <h2 id={title}>温馨提示</h2>
    <p id={description}>体验服务器资源有限，使用中可能稍有卡顿，感谢理解。</p>
    <button type="button" className="server-notice-confirm" onClick={dismiss} autoFocus>我知道了</button>
  </dialog>;
}
