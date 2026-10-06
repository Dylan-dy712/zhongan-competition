import {useEffect,useState} from 'react';
import {changeCareConsent,getCareConsent,type CareConsent} from './api';

export default function AccountPage({token,onChanged,onLogout}:{token:string;onChanged:()=>Promise<void>;onLogout:()=>Promise<void>}) {
  const [consent,setConsent]=useState<CareConsent>();
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  useEffect(()=>{let active=true;getCareConsent(token).then(value=>{if(active)setConsent(value);}).catch(e=>{if(active)setError(e.message);});return()=>{active=false;};},[token]);
  return <main className="claim-intake"><h1>我的账号</h1><p>{sessionStorage.getItem('zhongan_account_name') || '已连接账号'}</p>
    <h2>关怀资料授权</h2><p>仅用于整理你主动提供的合成资料、生成单次关怀与保存相关对话。长期记忆、资源匹配与评测不在此授权中。</p>
    {consent && <><p>状态：{consent.status==='active'?'已授权':consent.status==='revoked'?'已撤回':'尚未授权'} · 版本 {consent.version}</p>
      <button disabled={busy} onClick={async()=>{setBusy(true);setError('');try{
        setConsent(await changeCareConsent(token,consent.status!=='active',consent.version));await onChanged();
      }catch(e){setError(e instanceof Error?e.message:'授权更新失败。');setConsent(await getCareConsent(token).catch(()=>consent));}finally{setBusy(false);}}}>
        {consent.status==='active'?'撤回关怀授权':'确认并授权关怀'}</button></>}
    <small>撤回后停止后续关怀访问与处理；不会删除已保存的审计记录。当前开发版本尚未提供物理删除功能。</small>
    {error && <p role="alert" className="auth-error">{error}</p>}
    <h2>登录管理</h2><p>登录有效期 12 小时，退出时撤销当前会话。</p><button disabled={busy} onClick={()=>void onLogout()}>退出登录</button></main>;
}
