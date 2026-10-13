import {useEffect,useRef,useState} from 'react';
import {requestRecommendations,listQualitySnapshots,getQualitySnapshot,getDemoQuality} from './api';
import type {RecommendationResponse,QualitySnapshot,ProfileMetric} from './types';
import './insights.css';

const diseaseNames:Record<string,string>={FY:'肺炎',FX:'骨折',TN:'糖尿病',GX:'冠心病',YZ:'腰椎间盘突出症',TY:'通用'};
const needs=[['cost_level','费用水平'],['self_paid_burden','自付负担'],['medication_conformity','用药规范记录'],['treatment_conformity','治疗规范记录'],['guidance_completeness','出院指引完整度'],['readmission_rate','非计划再入院率'],['patient_feedback','患者反馈']];
export function metricValue(metric:ProfileMetric){if(metric.value===null)return '暂无数据';return metric.metric_name==='cost_level'?`${metric.value.toFixed(2)} 倍同组中位数`:metric.unit==='1-5'?`${metric.value.toFixed(1)} / 5`:`${(metric.value*100).toFixed(1)}%`;}
export function CareRecommendations({token,initialDisease='',demo=false}:{token:string;initialDisease?:string;demo?:boolean}){
 const [noProfiles,setNoProfiles]=useState(false);
 const [snapshot,setSnapshot]=useState<QualitySnapshot|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true),[retry,setRetry]=useState(0);
 const [group,setGroup]=useState(''),[picked,setPicked]=useState<string[]>(['cost_level','guidance_completeness']),[result,setResult]=useState<RecommendationResponse|null>(null),[busy,setBusy]=useState(false),[compare,setCompare]=useState<string[]>([]);
 const revision=useRef(0);
 useEffect(()=>{let active=true;++revision.current;setSnapshot(null);setResult(null);setCompare([]);setLoading(true);setError('');setNoProfiles(false);
  void (async()=>{try{const value=demo?await getDemoQuality(token):await (async()=>{const items=await listQualitySnapshots(token);if(!items.length)return null;return getQualitySnapshot(token,items[0].snapshot_id);})();
   if(active){setSnapshot(value);setNoProfiles(!value||!value.profiles.length);setGroup(demo&&value?.profiles[0]?JSON.stringify(value.profiles[0].cohort_filters):'');}
  }catch(e){if(active)setError(e instanceof Error?e.message:'画像暂不可用');}finally{if(active)setLoading(false);}})();return()=>{active=false;++revision.current;};
 },[token,demo,retry,initialDisease]);
 const change=()=>{++revision.current;setResult(null);setCompare([]);setBusy(false);setError('');};
 async function ask(){if(!group||picked.length<2||busy)return;const version=++revision.current;setBusy(true);setError('');setResult(null);
  try{const {disease_group,treatment_group,risk_group,payer_group}=JSON.parse(group);const value=await requestRecommendations(token,{disease_group,treatment_group,risk_group,payer_group,needs:picked.map((metric_name,i)=>({need_id:`need-${i}`,metric_name}))},demo);
   if(version===revision.current){if(value.snapshot_id!==snapshot?.snapshot_id){setError('机构数据版本已更新，请重新加载后查询。');}else setResult(value);}
  }catch(e){if(version===revision.current)setError(e instanceof Error?e.message:'查询失败');}finally{if(version===revision.current)setBusy(false);}}
 const groups=[...new Set(snapshot?.profiles.map(p=>JSON.stringify(p.cohort_filters))||[])];
 const profiles=snapshot?.profiles.filter(p=>JSON.stringify(p.cohort_filters)===group)||[];
 const catalog=[...new Set(profiles.flatMap(p=>p.metrics.map(m=>m.metric_ref)))];
 const selected=profiles.filter(p=>compare.includes(p.entity_id));
 return <section className="quality-panel" aria-label="机构品质画像与参考">
  <header><small>就医参考</small><h2>从你关心的方面，看懂机构记录</h2><p>选择病种与适用分组，再选择两到三项关注点。第一项是首要关注点。</p></header>
  <p><a href="/#/quality-demo" target="_blank" rel="noopener noreferrer">查看三病种关怀与模拟品质方案（虚构数据）</a></p>
  {demo&&<p className="demo-notice">合成演示 · 3 个病种 × 每病种 5 家机构 · 不代表真实机构或真实医学质量排名</p>}
  {loading?<p role="status">正在加载机构画像…</p>:snapshot&&<>
   {initialDisease&&<p className="muted">本次诊断字段对应：{diseaseNames[initialDisease]}。请进一步确认下方统计分组适用。</p>}
   <label className="overview-field">病种与统计范围<select value={group} onChange={e=>{change();setGroup(e.target.value);}}><option value="">请选择适用病种与分组</option>{groups.map((g,index)=>{const f=JSON.parse(g);return <option value={g} key={g}>{diseaseNames[f.disease_group]||f.disease_group} · 统计分组 {index+1} · {f.risk_group?'风险已分层':'风险未分层'} · {f.payer_group?'支付已分层':'支付未分层'}</option>;})}</select></label>
   {group&&<details><summary>查看本组适用条件</summary><p>治疗：{JSON.parse(group).treatment_group}；风险：{JSON.parse(group).risk_group||'未知'}；支付：{JSON.parse(group).payer_group||'未知'}。这些是统计分组，不能仅凭病种确定适用。</p></details>}
   <div className="care-recommend-chips">{needs.map(([name,label])=><button key={name} aria-pressed={picked.includes(name)} disabled={!picked.includes(name)&&picked.length>=3} onClick={()=>{change();setPicked(v=>v.includes(name)?v.filter(n=>n!==name):[...v,name]);}}>{picked.includes(name)?`${picked.indexOf(name)+1}. `:''}{label}</button>)}</div>
   <button className="care-primary" disabled={!group||picked.length<2||busy} onClick={()=>void ask()}>{busy?'正在匹配…':'查看匹配理由'}</button>
   <p className="muted">数据：{snapshot.data_origin==='synthetic'?'合成演示':snapshot.data_origin} · {snapshot.dataset_version} · {profiles.length} 家候选。统计分组需与本次情况相符。</p>
   <div className="profile-grid">{profiles.map(profile=>{const recommendation=result?.results.find(r=>r.candidate_id===profile.entity_id&&r.entity_type===profile.entity_type);return <article className="profile-card" key={profile.entity_id}>
    <header><h3>{profile.display_name}</h3><label><input type="checkbox" checked={compare.includes(profile.entity_id)} disabled={!compare.includes(profile.entity_id)&&compare.length>=3} onChange={()=>setCompare(v=>v.includes(profile.entity_id)?v.filter(x=>x!==profile.entity_id):[...v,profile.entity_id])}/>加入对比</label></header>
    <small>{profile.metrics.filter(m=>m.value!==null).length} 个有效维度</small>
    {profile.metrics.map(metric=><details className="profile-metric" key={metric.metric_ref}><summary><span>{metric.label}</span><strong>{metricValue(metric)}</strong><sup>{catalog.indexOf(metric.metric_ref)+1}</sup></summary>
     <p>有效样本 {metric.sample_count} · 缺失 {(metric.missing_rate*100).toFixed(1)}%</p><p>{metric.window_start} 至 {metric.window_end}</p><p>{metric.comparison_allowed?'满足本组比较条件':'当前不满足比较条件'}</p><p>{metric.limitations.join('；')}</p><small>来源：{snapshot.dataset_version} · 指标 {metric.metric_name} · 快照 {snapshot.snapshot_id}</small>
    </details>)}
    {recommendation&&<div className="match-reasons"><h4>{recommendation.eligible?'与你关注点的对应关系':'暂不能推荐'}</h4>{recommendation.match_reasons.map((reason,i)=><details key={i}><summary>{reason.text}<sup>{i+1}</sup></summary><p>对应需求：{needs.find(([key])=>key===reason.reason_code)?.[1]}</p>{reason.metric_refs.map(ref=>{const metric=profile.metrics.find(m=>m.metric_ref===ref);return <p key={ref}>{metric?`${metric.label}：${metricValue(metric)}，有效样本 ${metric.sample_count}；${metric.window_start} 至 ${metric.window_end}`:'该指标来源暂不可用'}</p>;})}</details>)}
     {recommendation.rejection_reason&&<p>{recommendation.rejection_reason}</p>}{recommendation.limitations.map((text,i)=><small key={i}>{text}</small>)}
     {!recommendation.ranking_allowed&&<small>列表顺序不代表排名。</small>}
    </div>}
   </article>;})}</div>
   {group&&!profiles.length&&<p>该分组暂无机构画像。</p>}
   {selected.length>0&&<section className="profile-comparison"><h3>机构对比（{selected.length}/3）</h3>{needs.map(([name,label])=><div key={name}><h4>{label}</h4>{selected.map(profile=>{const metric=profile.metrics.find(m=>m.metric_name===name);return <p key={profile.entity_id}><span>{profile.display_name}</span><strong>{metric?metricValue(metric):'暂无数据'}</strong></p>;})}</div>)}</section>}
  </>}
  {!loading&&noProfiles&&<section className="overview-note"><h3>当前没有可用于机构比较的数据</h3><p>本次材料不能证明医院之间的品质差异，因此暂不生成机构排名或推荐名单。已有的就诊提醒与参考资料可在上方查看。</p></section>}
  {error&&<div role="alert"><p>{error}</p><button onClick={()=>setRetry(n=>n+1)}>重新加载画像</button></div>}
 </section>;
}
