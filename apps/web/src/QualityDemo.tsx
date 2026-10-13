import {useState} from 'react';
import data from './quality-demo.json';
import './quality-demo.css';
import CareScenarioDemo from './CareScenarioDemo';

const needs = ['cost_level','self_paid_burden','medication_conformity','treatment_conformity','guidance_completeness'];
const labels:Record<string,string> = {cost_level:'费用水平',self_paid_burden:'个人承担',
  medication_conformity:'用药规范示例',treatment_conformity:'治疗规范示例',guidance_completeness:'出院指导完整度'};
const entityNames:Record<string,string> = {hospital:'医疗机构',doctor:'医生',treatment_plan:'治疗方案'};

export default function QualityDemo() {
  const [view,setView]=useState<'quality'|'care'>('quality');
  const [disease,setDisease] = useState('FX');
  const [kind,setKind] = useState('hospital');
  const [picked,setPicked] = useState(['cost_level','guidance_completeness']);
  const match=data.matches.find(m=>m.request.disease_group===disease &&
    m.request.needs.every(n=>picked.includes(n.metric_name)));
  const candidates=match?.candidates.filter(c=>c.entity_type===kind) || [];
  return <main className="quality-demo">
    <a href="/#/home">返回应用</a>
    <header><p>暖愈智护 · 初赛产品方案</p><h1>下一次就医，把依据看清楚</h1>
      <p className="quality-demo-warning" role="note">{view==='quality'?data.disclaimer:
        '合成材料上的模型生成草稿，未获医学批准；当前查看保存结果，不是对真实患者的诊疗指引。'}</p></header>
    <nav className="quality-demo-options" aria-label="初赛方案演示">
      <button aria-pressed={view==='care'} onClick={()=>setView('care')}>痛点与三病种关怀</button>
      <button aria-pressed={view==='quality'} onClick={()=>setView('quality')}>品质画像与匹配理由</button>
    </nav>
    {view==='care'?<CareScenarioDemo />:<>
    <section aria-label="选择参考范围"><h2>选择病种与参考对象</h2>
      <div className="quality-demo-options">{Object.entries(data.diseases).map(([code,name])=><button key={code}
        aria-pressed={disease===code} onClick={()=>setDisease(code)}>{name}</button>)}</div>
      <div className="quality-demo-options">{Object.entries(entityNames).map(([code,name])=><button key={code}
        aria-pressed={kind===code} onClick={()=>setKind(code)}>{name}</button>)}</div>
      <h2>选两项关注点</h2><p>选择第三项会替换最早选择的一项。每个候选给出两个独立维度的匹配依据。</p>
      <div className="quality-demo-options">{needs.map(name=><button key={name} aria-pressed={picked.includes(name)}
        onClick={()=>{if(!picked.includes(name))setPicked([...picked.slice(1),name]);}}>{labels[name]}</button>)}</div>
    </section>
    <p className="quality-demo-summary">模拟覆盖：3病种 × 每病种5机构 · 5个有效维度 · 当前{candidates.length}个{entityNames[kind]}候选。列表没有可信医疗排名。</p>
    <section aria-label="模拟匹配结果">{candidates.map(candidate=>{
      const profile=data.snapshot.profiles.find(p=>p.entity_id===candidate.candidate_id);
      if(!profile)return null;
      return <article className="quality-demo-candidate" key={candidate.candidate_id}>
        <h2>{profile.display_name}</h2><p>同病种、同示例路径、同模拟风险和医保分组 · {profile.record_count}个模拟病例</p>
        <dl>{profile.metrics.filter(m=>needs.includes(m.metric_name)).map(metric=><div key={metric.metric_name}>
          <dt>{labels[metric.metric_name]}</dt><dd>{metric.value===null?'缺数据':metric.metric_name==='cost_level'?
            `${metric.value.toFixed(2)}倍同组中位数`:`${(metric.value*100).toFixed(1)}%`}</dd>
          <small>有效样本 {metric.sample_count} · 缺失 {(metric.missing_rate*100).toFixed(0)}%</small>
        </div>)}</dl>
        <h3>为什么与这两项关注点匹配</h3>{candidate.match_reasons.map(reason=><p key={reason.reason_code}>
          <strong>{labels[reason.reason_code]}：</strong>{reason.text}</p>)}
        <details><summary>公式、来源与局限</summary>
          {profile.metrics.filter(m=>needs.includes(m.metric_name)).map(metric=><p key={metric.metric_name}>
            {labels[metric.metric_name]}：{data.formulas[metric.metric_name as keyof typeof data.formulas]}<br/>
            <small>快照依据：{metric.metric_ref}</small></p>)}
          <p>{data.synthetic_assumptions}</p><p>费用水平与指导记载不代表疗效。模拟数据不能形成可信医疗排名。</p>
        </details>
      </article>;
    })}</section>
    <details><summary>可复算数据与覆盖说明</summary><p>数据版本：{data.demo_version}</p>
      <p>公式与匹配由现有品质计算核心生成，生产合成数据拒排规则保持生效。</p>
      <pre>{JSON.stringify(Object.entries(data.diseases).map(([code,name])=>({病种:name,
        有效机构: data.matches.find(m=>m.request.disease_group===code)?.coverage.valid_two_reason_hospitals})),null,2)}</pre>
    </details>
    </>}
  </main>;
}
