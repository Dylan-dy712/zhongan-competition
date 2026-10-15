import {useState} from 'react';
import {authenticate} from './api';
import './auth.css';
import mascot from './assets/auth-sprout.webp';

function FieldIcon({kind}:{kind:'phone'|'lock'|'person'|'eye'|'hidden'|'arrow'}) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{kind==='phone'?<><rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/></>:kind==='lock'?<><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 15v2"/></>:kind==='person'?<><circle cx="12" cy="7" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/></>:kind==='arrow'?<path d="M4 12h16m-7-7 7 7-7 7"/>:<><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>{kind==='hidden'&&<path d="m3 3 18 18"/>}</>}</svg>;
}

export default function AuthPage({onAuthenticated}:{onAuthenticated:(token:string)=>Promise<void>}) {
  const [register,setRegister]=useState(false);
  const [username,setUsername]=useState('');
  const [password,setPassword]=useState('');
  const [confirm,setConfirm]=useState('');
  const [name,setName]=useState('');
  const [consent,setConsent]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [showPassword,setShowPassword]=useState(false);
  return <main className="auth-page"><div className={`auth-card${register?' auth-register':''}`}>
    <div className="auth-hero-art" aria-hidden="true"><img className="auth-mascot" src={mascot} alt="" width="1200" height="900"/></div>
    <header className="auth-hero">
    <span className="auth-brand">众安 · 暖愈智护</span>
    <h1>{register?'让关怀，从这里开始':'欢迎回来'}</h1>
    <p>把看病资料放在一起，<br/>让每一步都更安心。</p>
    </header>
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
      {register && <label>怎么称呼你<span className="auth-input"><FieldIcon kind="person"/><input value={name} onChange={e=>setName(e.target.value)} placeholder="请输入称呼" maxLength={40} autoComplete="nickname" required disabled={busy}/></span></label>}
      <label>手机号<span className="auth-input"><FieldIcon kind="phone"/><input type="tel" inputMode="numeric" value={username} onChange={e=>setUsername(e.target.value)} pattern="1[3-9][0-9]{9}" placeholder="请输入手机号" autoComplete="username" required disabled={busy}/></span></label>
      <label>密码<span className="auth-input"><FieldIcon kind="lock"/><input type={showPassword?'text':'password'} value={password} onChange={e=>setPassword(e.target.value)} placeholder="请输入密码" autoComplete={register?'new-password':'current-password'} required disabled={busy}/><button type="button" className="auth-password-toggle" aria-label={showPassword?'隐藏密码':'显示密码'} aria-pressed={showPassword} disabled={busy} onClick={()=>setShowPassword(value=>!value)}><FieldIcon kind={showPassword?'eye':'hidden'}/></button></span></label>
      {register && <><label>确认密码<span className="auth-input"><FieldIcon kind="lock"/><input type={showPassword?'text':'password'} value={confirm} onChange={e=>setConfirm(e.target.value)} placeholder="请再次输入密码" autoComplete="new-password" required disabled={busy}/></span></label>
        <label className="auth-consent"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)} disabled={busy}/><span>可选：同意将主动提供的资料用于本次就医关怀，并保存相关对话与记录。其他用途需另行授权，也可注册后再确认。</span></label></>}
      {error && <p role="alert" className="auth-error">{error}</p>}
      <button className="auth-primary" disabled={busy}><span>{busy?'正在连接…':register?'注册并进入':'登录'}</span><span className="auth-submit-arrow"><FieldIcon kind="arrow"/></span></button>
    </form>
    <small>登录后可查看已保存的资料与对话，登录有效期为 12 小时。</small>
  </div></main>;
}
