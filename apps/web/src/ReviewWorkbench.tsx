import {useCallback, useEffect, useState} from 'react';
import {listReviews, decideReview, publishReport, getEvidence} from './api';
import type {Evidence, Report, ReviewDecision, ReviewTask, ReportSection, CareAction} from './types';
import {EvidencePanel} from './CarePages';
import {careSectionLabels} from './carePresentation';

const claimTypeLabels: Record<string, string> = {case_fact: '病例事实', professional_explanation: '专业解释',
  patient_statement: '用户自述', service_suggestion: '服务建议', to_confirm: '待确认'};
const reviewStatusLabels: Record<string, string> = {not_required: '无需复核', pending: '待复核',
  approved: '已批准', corrected: '已纠正', rejected: '已驳回'};
const insightLabels: Record<string, string> = {clinical: '临床', cost: '费用', experience: '体验'};

function genKey() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  const hex = Array.from(bytes, x => x.toString(16).padStart(2, '0')).join('');
  return `review-${hex.slice(0, 24)}`;
}

function asReport(target: ReviewTask['target']): Report | null {
  return target && typeof target === 'object' && 'sections' in target ? target as Report : null;
}

const cloneSections = (sections: ReportSection[]) => JSON.parse(JSON.stringify(sections)) as ReportSection[];
const cloneActions = (actions: CareAction[]) => JSON.parse(JSON.stringify(actions)) as CareAction[];

export function ReviewWorkbench({token}: {token: string}) {
  const [tasks, setTasks] = useState<ReviewTask[] | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editedSections, setEditedSections] = useState<ReportSection[] | null>(null);
  const [editedActions, setEditedActions] = useState<CareAction[] | null>(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [readyToPublish, setReadyToPublish] = useState<{caseId: string; reportId: string; version: number}[]>([]);
  const [insightEdits, setInsightEdits] = useState<null | {severity: string; rationale: string; uncertainty: string; suggested_action: string; judgment_status: string}>(null);
  const [published, setPublished] = useState<string[]>([]);

  const load = useCallback(async () => {
    setError(''); setForbidden(false);
    try {setTasks(await listReviews(token, 'pending'));}
    catch (e) {
      if (e instanceof Error && 'status' in e && (e as {status: number}).status === 403) setForbidden(true);
      else setError(e instanceof Error ? e.message : '加载失败');
      setTasks([]);
    }
  }, [token]);
  useEffect(() => {void load();}, [load]);

  const selected = tasks?.find(t => t.review_id === selectedId) || null;
  const report = selected ? asReport(selected.target) : null;
  const insight = selected && !report ? selected.target as Record<string, unknown> : null;

  const reset = () => {setEditing(false); setEditedSections(null); setEditedActions(null); setInsightEdits(null); setReason('');};
  const select = (id: string | null) => {setSelectedId(id); reset(); setNotice('');};

  const act = async (decision: 'approve' | 'correct' | 'reject') => {
    if (!selected || busy) return;
    if (decision !== 'approve' && !reason.trim()) {setNotice(decision === 'reject' ? '驳回必须填写理由。' : '纠正必须填写理由。'); return;}
    setBusy(true); setError(''); setNotice('');
    try {
      const corrections = [];
      if (decision === 'correct' && editedSections) corrections.push({field_or_claim_id: 'sections' as const, replacement: editedSections, reason: reason.trim()});
      if (decision === 'correct' && editedActions) corrections.push({field_or_claim_id: 'actions' as const, replacement: editedActions, reason: reason.trim()});
      if (decision === 'correct' && insightEdits && insight) {
        const original = insight as Record<string, unknown>;
        for (const field of ['severity', 'rationale', 'uncertainty', 'suggested_action', 'judgment_status'] as const) {
          const before = original[field] == null ? '' : String(original[field]);
          if (insightEdits[field] !== before) {
            corrections.push({field_or_claim_id: field,
              replacement: field === 'uncertainty' && insightEdits[field] === '' ? null : insightEdits[field],
              reason: reason.trim()});
          }
        }
        if (!corrections.length) {setNotice('纠正模式下没有实际修改任何字段。'); setBusy(false); return;}
      }
      const result: ReviewDecision = await decideReview(token, selected.review_id,
        {expected_version: selected.target_version, decision, reason: reason.trim() || '核对无误', corrections},
        genKey());
      setNotice(decision === 'approve' ? '已批准。' : decision === 'correct' ? `已纠正，生成第 ${result.target_version} 版。` : '已驳回。');
      if (selected.target_type === 'report' && decision !== 'reject') {
        const rep = asReport(selected.target);
        setReadyToPublish(v => [{caseId: selected.case_id, reportId: rep?.report_id || selected.target_id,
          version: result.target_version}, ...v.filter(x => x.reportId !== (rep?.report_id || selected.target_id))]);
      }
      reset();
      await load();
    } catch (e) {setError(e instanceof Error ? e.message : '操作失败');}
    finally {setBusy(false);}
  };

  const publish = async (item: {caseId: string; reportId: string; version: number}) => {
    setBusy(true); setError('');
    try {
      await publishReport(token, item.caseId, item.version, item.version, genKey());
      setPublished(v => [...v, `${item.reportId}#${item.version}`]);
      setReadyToPublish(v => v.filter(x => x !== item));
      setNotice(`报告 v${item.version} 已发布，患者端可见。`);
    } catch (e) {setError(e instanceof Error ? e.message : '发布失败');}
    finally {setBusy(false);}
  };

  if (forbidden) return <main className="review-workbench"><div className="review-empty">
    <h1>复核工作台</h1><p>当前连接的账号没有医学审核角色。请使用医学审核账号连接。</p></div></main>;

  return <main className="review-workbench">
    <div className="review-head"><h1>医学复核工作台</h1>
      <button disabled={busy} onClick={() => void load()}>刷新队列</button></div>
    <p className="review-note">待复核任务按创建时间排列；批准仅使报告就绪，发布还需单独确认。证据原文可点击查看。</p>
    {notice && <div className="review-notice" role="status">{notice}</div>}
    {error && <div className="review-error" role="alert">{error}</div>}
    {tasks === null ? <p className="review-empty">加载中…</p> : tasks.length === 0 && <p className="review-empty">当前没有待复核任务。</p>}
    {!!tasks?.length && <div className="review-layout">
      <ul className="review-queue" aria-label="待复核队列">
        {tasks.map(t => {
          const rep = asReport(t.target);
          return <li key={t.review_id}>
            <button className={selectedId === t.review_id ? 'selected' : ''} onClick={() => select(t.review_id)}>
              <strong>{t.target_type === 'report' ? '关怀报告' : '洞察结论'}</strong>
              <small>v{t.target_version} · {new Date(t.created_at).toLocaleString('zh-CN')}</small>
              <small className="review-reason">{t.reason}</small>
              {rep && <small>{rep.sections.reduce((n, s) => n + s.claims.length, 0)} 条声明 · {rep.actions.length} 项行动</small>}
            </button></li>;
        })}
      </ul>
      {selected && <section className="review-detail">
        <div className="review-reason-box"><label>复核意见（驳回/纠正必填）<textarea value={reason}
          onChange={e => setReason(e.target.value)} rows={2} placeholder="例如：费用数字与票据不符，已改为清单口径"/></label></div>
        <div className="review-actions-bar">
          <button disabled={busy} onClick={() => void act('approve')}>通过</button>
          {(report || insight) && <button disabled={busy} onClick={() => {
            if (insight && !editing) {
              setInsightEdits({severity: String(insight.severity || 'undetermined'),
                rationale: String(insight.rationale || ''), uncertainty: String(insight.uncertainty || ''),
                suggested_action: String(insight.suggested_action || ''),
                judgment_status: String(insight.judgment_status || 'candidate')});
            }
            if (report && !editing) {setEditedSections(cloneSections(report.sections)); setEditedActions(cloneActions(report.actions));}
            setEditing(v => !v);}}>{editing ? '退出纠正' : '纠正'}</button>}
          <button className="danger" disabled={busy} onClick={() => void act('reject')}>驳回</button>
        </div>
        {report && <div className="review-report">
          {report.sections.map((s, si) => <details key={s.section_type} open className="review-section">
            <summary>{careSectionLabels[s.section_type] || s.section_type}</summary>
            {s.claims.map((claim, ci) => <article key={claim.claim_id}>
              <div className="review-claim-meta">
                <span>{claimTypeLabels[claim.claim_type] || claim.claim_type}</span>
                <span>{reviewStatusLabels[claim.review_status] || claim.review_status}</span></div>
              {editing && editedSections
                ? <textarea value={editedSections[si]?.claims[ci]?.text || claim.text} rows={3}
                    onChange={e => setEditedSections(prev => {const next: ReportSection[] = prev ? [...prev] : []; const sec: ReportSection = {...(next[si] || s), claims: [...(next[si] || s).claims]}; sec.claims[ci] = {...claim, text: e.target.value}; next[si] = sec; return next;})}/>
                : <p>{claim.text}</p>}
              {claim.evidence_refs.map(id => <button key={id} className="citation"
                onClick={async () => {try {setEvidence(await getEvidence(id, token));} catch {setError('证据加载失败');}}}>查看依据</button>)}
            </article>)}
          </details>)}
          {report.actions.length > 0 && <details open className="review-section"><summary>优先行动</summary>
            {report.actions.map((a, ai) => <article key={a.action_id}>
              {editing && editedActions
                ? <textarea value={editedActions[ai]?.action_text || a.action_text} rows={2}
                    onChange={e => setEditedActions(prev => {const next: CareAction[] = prev ? [...prev] : []; next[ai] = {...(next[ai] || a), action_text: e.target.value}; return next;})}/>
                : <p><strong>{a.action_text}</strong>（{a.owner_role}）</p>}
              <p className="review-claim-meta">{a.rationale}</p></article>)}</details>}          {editing && <p className="review-note">纠正将整组提交六段与行动，服务端会按原文与来源重新校验；无法通过校验的纠正会被拒绝。</p>}
        </div>}
        {insight && <div className="review-report">
          <p><strong>{insightLabels[String(insight.category)] || String(insight.category)}</strong> · {String(insight.label)}</p>
          {editing && insightEdits ? <div className="review-insight-edit">
            <label>严重度<select value={insightEdits.severity} onChange={e => setInsightEdits({...insightEdits, severity: e.target.value})}>
              {['low', 'medium', 'high', 'undetermined'].map(v => <option key={v} value={v}>{v}</option>)}</select></label>
            <label>判定状态<select value={insightEdits.judgment_status} onChange={e => setInsightEdits({...insightEdits, judgment_status: e.target.value})}>
              {['candidate', 'supported', 'indeterminate', 'rejected'].map(v => <option key={v} value={v}>{v}</option>)}</select></label>
            <label>理由<textarea value={insightEdits.rationale} rows={3}
              onChange={e => setInsightEdits({...insightEdits, rationale: e.target.value})}/></label>
            <label>不确定性说明（可留空）<textarea value={insightEdits.uncertainty} rows={2}
              onChange={e => setInsightEdits({...insightEdits, uncertainty: e.target.value})}/></label>
            <label>建议<textarea value={insightEdits.suggested_action} rows={2}
              onChange={e => setInsightEdits({...insightEdits, suggested_action: e.target.value})}/></label>
            <p className="review-note">仅提交有变化的字段；服务端按同一契约重新校验。</p>
          </div>
          : <>
          <p>{String(insight.rationale)}</p>
          <p className="review-claim-meta">建议：{String(insight.suggested_action || '—')}</p>
          <p className="review-claim-meta">严重度：{String(insight.severity)}</p>
          </>}
        </div>}
        {evidence && <EvidencePanel evidence={evidence} onClose={() => setEvidence(null)}/>}
      </section>}
    </div>}
    {readyToPublish.length > 0 && <section className="review-publish" aria-labelledby="review-publish-title">
      <h2 id="review-publish-title">已批准，待发布</h2>
      <p>发布前系统会再次核验材料一致性、来源与授权；未通过核验的版本会被拒绝并说明原因。</p>
      {readyToPublish.map(item => {
        const key = `${item.reportId}#${item.version}`;
        return <div key={key} className="review-publish-item"><span>{item.reportId.slice(0, 8)}… · v{item.version}</span>
          {published.includes(key) ? <span>已发布</span>
            : <button disabled={busy} onClick={() => void publish(item)}>发布 v{item.version}</button>}</div>;
      })}
    </section>}
  </main>;
}
