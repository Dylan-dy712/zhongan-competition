import {useState} from 'react';
import {requestRecommendations} from './api';
import type {RecommendationResponse} from './types';

const NEED_OPTIONS: {name: string; label: string}[] = [
  {name: 'cost_level', label: '费用水平'},
  {name: 'self_paid_burden', label: '自付负担'},
  {name: 'medication_conformity', label: '用药规范记录'},
  {name: 'treatment_conformity', label: '治疗规范记录'},
  {name: 'guidance_completeness', label: '出院指引完整度'},
  {name: 'readmission_rate', label: '非计划再入院率'},
  {name: 'patient_feedback', label: '患者反馈'},
];

export function CareRecommendations({token}: {token: string}) {
  const [picked, setPicked] = useState<string[]>([]);
  const [result, setResult] = useState<RecommendationResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const toggle = (name: string) =>
    setPicked(v => v.includes(name) ? v.filter(x => x !== name) : [...v, name]);

  const ask = async () => {
    if (picked.length < 2 || busy) return;
    setBusy(true); setError(''); setResult(null);
    try {
      setResult(await requestRecommendations(token, {
        disease_group: 'TY', treatment_group: 'unmapped', risk_group: null, payer_group: null,
        needs: picked.map((name, i) => ({need_id: `need-${i}`, metric_name: name})),
      }));
    } catch (e) {setError(e instanceof Error ? e.message : '查询失败');}
    finally {setBusy(false);}
  };

  return <section className="care-recommend" aria-labelledby="care-recommend-title">
    <h2 id="care-recommend-title">下次就医，想参考什么？</h2>
    <p><a href="/#/quality-demo" target="_blank" rel="noopener noreferrer">查看初赛模拟品质方案（虚构数据）</a></p>
    <p className="care-recommend-note">选两到三项你最在意的方面，我们用历史理赔记录的统计给出参考。
      这是记录统计，<strong>不是医疗质量排名</strong>；当前环境为合成演示数据。</p>
    <div className="care-recommend-chips">
      {NEED_OPTIONS.map(o => <button key={o.name} type="button" aria-pressed={picked.includes(o.name)}
        className={picked.includes(o.name) ? 'picked' : ''}
        onClick={() => toggle(o.name)}>{o.label}</button>)}
    </div>
    <button className="care-recommend-go" disabled={busy || picked.length < 2}
      onClick={() => void ask()}>{busy ? '查询中' : picked.length < 2 ? '再选一项（至少两项）' : '查一查'}</button>
    {error && <div className="review-error" role="alert">{error}</div>}
    {result && <div className="care-recommend-result">
      <p className="care-recommend-scope">查询范围：通用病种组 · 未分层（暂无权威分层映射）· 数据来源：{result.data_origin === 'synthetic' ? '合成演示' : result.data_origin} · 指标政策：{result.policy_status === 'draft' ? '未冻结' : '已冻结'}</p>
      {result.results.length === 0 && <p>暂无可参考的机构记录。</p>}
      {result.results.map(r => <article key={r.candidate_id}>
        <h3>{r.entity_name}{r.eligible ? '' : <small> · 暂不能推荐</small>}</h3>
        {r.match_reasons.map((m, i) => <p key={i}>✓ {m.text}</p>)}
        {r.rejection_reason && <p className="care-recommend-why">暂不能推荐的原因：{r.rejection_reason}</p>}
        {r.limitations.map((l, i) => <p key={i} className="care-recommend-limit">{l}</p>)}
      </article>)}
    </div>}
  </section>;
}
