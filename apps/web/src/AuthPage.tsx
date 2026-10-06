import {useState} from 'react';
import {authenticate} from './api';
import './auth.css';
import {reading} from './CarePages';

export default function AuthPage({onAuthenticated}:{onAuthenticated:(token:string)=>Promise<void>}) {
  const [register,setRegister]=useState(false);
  const [username,setUsername]=useState('');
  const [password,setPassword]=useState('');
  const [confirm,setConfirm]=useState('');
  const [name,setName]=useState('');
  const [consent,setConsent]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  return <main className="auth-page"><div className="auth-card">
    <span className="auth-brand">众安 · 暖愈智护</span>
    <img className="auth-mascot" src={reading} alt="陪伴你的暖暖" width="100"/>
    <h1>{register?'让关怀，从这里开始':'欢迎回来'}</h1>
    <p>把看病资料放在一起，让每一步都更安心。</p>
    <div className="auth-tabs"><button disabled={busy} aria-pressed={!register} onClick={()=>{setRegister(false);setError('');}}>登录</button>
      <button disabled={busy} aria-pressed={register} onClick={()=>{setRegister(true);setError('');}}>注册</button></div>
    <form onSubmit={async e=>{e.preventDefault();if(busy)return;setError('');
      if(register && password!==confirm){setError('两次输入的密码不一致。');return;}
      setBusy(true);
      try {const result=await authenticate(register?'register':'login',{username,password,
        ...(register?{display_name:name,care_consent:consent}:{})});
        sessionStorage.setItem('zhongan_account_name',result.user.display_name);
        await onAuthenticated(result.access_token);
      } catch(e){setError(e instanceof Error?e.message:'连接失败，请稍后重试。');}
      finally {setBusy(false);}
    }}>
      {register && <label>怎么称呼你<input value={name} onChange={e=>setName(e.target.value)} maxLength={40} autoComplete="nickname" required disabled={busy}/></label>}
      <label>用户名<input value={username} onChange={e=>setUsername(e.target.value)} minLength={3} maxLength={32} pattern="[A-Za-z0-9_]+" placeholder="3–32 位字母、数字或下划线" autoComplete="username" required disabled={busy}/></label>
      <label>密码<input type="password" value={password} onChange={e=>setPassword(e.target.value)} minLength={10} maxLength={128} placeholder="至少 10 位" autoComplete={register?'new-password':'current-password'} required disabled={busy}/></label>
      {register && <><label>确认密码<input type="password" value={confirm} onChange={e=>setConfirm(e.target.value)} autoComplete="new-password" required disabled={busy}/></label>
        <label className="auth-consent"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)} disabled={busy}/><span>可选：同意将主动提供的合成资料用于本次关怀，并保存相关对话与记录。不包含长期记忆、推荐或评测用途。也可注册后再授权。版本：account-care-v1。</span></label></>}
      {error && <p role="alert" className="auth-error">{error}</p>}
      <button className="auth-primary" disabled={busy}>{busy?'正在连接…':register?'注册并进入':'登录'}</button>
    </form>
    <small>当前为比赛开发系统，仅使用合成资料。登录有效期为 12 小时。</small>
  </div></main>;
}
