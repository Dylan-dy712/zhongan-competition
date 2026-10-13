import {useState} from 'react';
import cases from './care-demo.json';

const titles:Record<string,string>={diagnosis_explanation:'这次诊断是什么意思',treatment_review:'治疗过程回顾',
  cost_explanation:'费用怎么看',recovery_plan:'康复与生活安排',emotional_support:'把担心慢慢理清',next_visit_advice:'下次就医准备'};
const painNames:Record<string,string>={CLIN_MEDICATION_CONTEXT_REVIEW:'临床 · 用药上下文待核实',
  CLIN_EXAM_JUSTIFICATION_REVIEW:'临床 · 检查目的待核实',COST_AMOUNT_RECONCILIATION:'费用 · 金额范围待核对',
  EXP_DISCHARGE_GUIDANCE_GAP:'体验 · 出院指导缺口',EXP_TERMINOLOGY_BARRIER:'体验 · 术语理解障碍'};

export default function CareScenarioDemo(){
  const [selected,setSelected]=useState(0);
  const record=cases[selected];
  const labels=new Set(cases.flatMap(c=>c.insights.map(i=>i.label)));
  return <section aria-label="三病种关怀生成示例">
    <p>以下为真实模型调用后保存的结果，当前页面不实时调用模型。</p>
    <p>覆盖骨折、肺炎、冠心病；两份骨折材料展示不同就医过程和照护需求。模型：{record.model_id} · 提示词：{record.prompt_version}。</p>
    <div className="quality-demo-options">{cases.map((c,i)=><button key={c.id} aria-pressed={selected===i}
      onClick={()=>setSelected(i)}>{c.disease}{c.id.includes('caregiver')?' · 家人陪同':c.id.includes('independent')?' · 独居门诊':''}</button>)}</div>
    <article className="quality-demo-candidate"><h2>输入材料与本人关切</h2><p>{record.user_input}</p>
      <details><summary>查看完整合成材料</summary><p>{record.material}</p></details>
      <p><small>输入哈希：{record.input_sha256}</small></p></article>
    <article className="quality-demo-candidate"><h2>痛点候选与归类原因</h2>
      <p>全部示例共覆盖三类、{labels.size}种痛点。每条都是待核实候选，不表示已认定医疗行为不合理。</p>
      {record.insights.map((insight,i)=><section key={i}><h3>{painNames[insight.label]||insight.label}</h3>
        <p><small>待复核候选 · 严重程度待医学判定 · 模型自报置信度：{insight.confidence===null?'未提供':`${Math.round(insight.confidence*100)}%（未经校准）`}</small></p>
        <p><strong>归类原因：</strong>{insight.rationale}</p><p><strong>可做的下一步：</strong>{insight.suggested_action}</p>
        <details><summary>原文依据</summary><blockquote>{insight.evidence_quote}</blockquote></details>
      </section>)}
    </article>
    {record.draft?.sections.map(section=><article key={section.section_type} className="quality-demo-candidate">
      <h2>{titles[section.section_type]}</h2>{section.claims.map((claim,i)=><section key={i}>
        <p>{claim.text}</p>{claim.claim_type==='to_confirm'&&<small>此项待确认</small>}
        {(claim.evidence_quote||claim.source_quote)&&<details><summary>查看来源</summary>
          <blockquote>{claim.evidence_quote||claim.source_quote}</blockquote></details>}
      </section>)}
    </article>)}
    <article className="quality-demo-candidate"><h2>下一步行动草稿</h2>
      {record.draft?.actions.map((action,i)=><section key={i}><h3>{i+1}. {action.action_text}</h3>
        <p>{action.rationale}</p><p>时间：{action.due_at||'按原医嘱或联系诊疗团队确认，未指定日期'}</p>
        {action.source_quote&&<details><summary>行动依据</summary><blockquote>{action.source_quote}</blockquote></details>}
      </section>)}
      <p>这里没有执行通知、建立真实随访或发布报告。实际触达与反馈请在应用授权流程中演示。</p>
    </article>
  </section>;
}
