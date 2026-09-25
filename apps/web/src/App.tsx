import { useMemo, useState, type ReactNode } from "react";
import { ApiError, getEvidence, getReport } from "./api";
import { demoEvidence, demoReport } from "./demo";
import type { Evidence, Report, ReportSection } from "./types";

type View = "home" | "report" | "actions" | "profile";
type IconName = "home" | "file" | "heart" | "user" | "shield" | "spark" | "arrow" | "check" | "source" | "close" | "settings";

const sectionMeta: Record<ReportSection["section_type"], { title: string; hint: string; icon: string }> = {
  diagnosis_explanation: { title: "这次生病怎么回事", hint: "诊断与通俗解释", icon: "听" },
  treatment_review: { title: "医院做了哪些治疗", hint: "诊疗过程回顾", icon: "疗" },
  cost_explanation: { title: "费用花在哪里", hint: "费用与结算说明", icon: "费" },
  recovery_plan: { title: "回家后怎么恢复", hint: "康复与日常照护", icon: "养" },
  emotional_support: { title: "给你的一点安心", hint: "情绪与陪伴支持", icon: "暖" },
  next_visit_advice: { title: "什么时候需要复诊", hint: "复诊与危险信号", icon: "诊" }
};

function Icon({ name, size = 22 }: { name: IconName; size?: number }) {
  const paths: Record<IconName, ReactNode> = {
    home: <><path d="m3 10 9-7 9 7"/><path d="M5 9v11h14V9M9 20v-6h6v6"/></>,
    file: <><path d="M6 2h8l4 4v16H6z"/><path d="M14 2v5h5M9 12h6M9 16h6"/></>,
    heart: <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8l1.1 1.1L12 21l7.8-7.5 1.1-1.1a5.5 5.5 0 0 0-.1-7.8Z"/>,
    user: <><circle cx="12" cy="8" r="4"/><path d="M4 22a8 8 0 0 1 16 0"/></>,
    shield: <><path d="M12 2 4 5v6c0 5 3.4 9.4 8 11 4.6-1.6 8-6 8-11V5z"/><path d="m9 12 2 2 4-5"/></>,
    spark: <><path d="m12 3 1.4 4.1L17.5 9l-4.1 1.5L12 15l-1.5-4.5L6.5 9l4-1.9z"/><path d="m19 15 .7 2.1L22 18l-2.3.9L19 21l-.9-2.1L16 18l2.1-.9z"/></>,
    arrow: <path d="m9 18 6-6-6-6"/>, check: <path d="m5 12 4 4L19 6"/>,
    source: <><path d="M5 3h14v18H5z"/><path d="M8 8h8M8 12h8M8 16h5"/></>,
    close: <path d="M5 5l14 14M19 5 5 19"/>, settings: <><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.9 4.9 7 7M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1 7 17M17 7l2.1-2.1"/></>
  };
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

function StatusPill({ status }: { status: string }) {
  const published = status === "published";
  return <span className={`status ${published ? "status-ready" : "status-wait"}`}><span />{published ? "已完成专业审核" : "等待专业审核"}</span>;
}

function EvidencePanel({ evidence, onClose }: { evidence: Evidence | null; onClose: () => void }) {
  return <aside className={`evidence-panel ${evidence ? "is-open" : ""}`} aria-hidden={!evidence}>
    <div className="evidence-head"><div><span className="eyebrow">原始材料</span><h2>证据来源</h2></div><button className="icon-button" onClick={onClose} aria-label="关闭证据"><Icon name="close" /></button></div>
    {evidence ? <div className="evidence-body">
      <div className="source-paper"><span className="paper-tab">第 {(evidence.page_index ?? 0) + 1} 页</span><blockquote>{evidence.text_span?.text || "该证据没有可展示的文字片段，请打开原始材料核对。"}</blockquote></div>
      <dl className="meta-list"><div><dt>提取方式</dt><dd>{evidence.extraction_method === "native_pdf_text" ? "原生 PDF 文本" : evidence.extraction_method}</dd></div><div><dt>材料版本</dt><dd>第 {evidence.document_version} 版</dd></div></dl>
      <p className="privacy-note"><Icon name="shield" size={18}/> 只展示与当前结论直接相关的原文片段。</p>
    </div> : <div className="evidence-empty"><Icon name="source" size={30}/><p>点击报告中的“查看依据”后，原文会显示在这里。</p></div>}
  </aside>;
}

function ReportView({ report, onEvidence }: { report: Report; onEvidence: (id: string) => void }) {
  const [open, setOpen] = useState<string[]>(["diagnosis_explanation", "recovery_plan"]);
  const toggle = (key: string) => setOpen(v => v.includes(key) ? v.filter(x => x !== key) : [...v, key]);
  return <main className="page report-page">
    <header className="page-heading"><div><span className="eyebrow">关怀报告 · 第 {report.report_version} 版</span><h1>把复杂的病历，讲成你能看懂的话</h1><p>每条内容都能回到材料出处；无法确定的地方会明确告诉你。</p></div><StatusPill status={report.status}/></header>
    <div className="gentle-banner"><span className="banner-icon"><Icon name="heart"/></span><div><strong>先慢慢看，不必一次记住所有内容</strong><p>最需要做的事情已经整理在“优先行动”里。</p></div></div>
    <section className="section-list" aria-label="六段关怀报告">
      {report.sections.map(section => {
        const meta = sectionMeta[section.section_type]; const expanded = open.includes(section.section_type);
        return <article className={`report-section ${expanded ? "expanded" : ""}`} key={section.section_type}>
          <button className="section-toggle" onClick={() => toggle(section.section_type)} aria-expanded={expanded}>
            <span className="section-mark">{meta.icon}</span><span className="section-title"><strong>{meta.title}</strong><small>{meta.hint}</small></span><span className="chevron"><Icon name="arrow"/></span>
          </button>
          {expanded && <div className="section-content">{section.claims.map(c => <div className="claim" key={c.claim_id}><p>{c.text}</p><div className="claim-foot"><span className={`claim-kind ${c.claim_type}`}>{c.claim_type === "case_fact" ? "来自本次材料" : c.claim_type === "to_confirm" ? "需要确认" : c.claim_type === "professional_explanation" ? "专业知识说明" : "关怀建议"}</span>{c.evidence_refs.map(id => <button className="source-link" key={id} onClick={() => onEvidence(id)}><Icon name="source" size={16}/>查看依据</button>)}</div></div>)}</div>}
        </article>;
      })}
    </section>
  </main>;
}

function ActionsView({ report }: { report: Report }) {
  const [done, setDone] = useState<string[]>([]);
  return <main className="page"><header className="page-heading"><div><span className="eyebrow">优先行动</span><h1>接下来，先做好这三件事</h1><p>数量少一点，行动更容易。完成后可以在这里打勾。</p></div></header>
    <div className="action-grid">{report.actions.map((a, i) => <article className={`action-card ${done.includes(a.action_id) ? "done" : ""}`} key={a.action_id}><span className="action-number">0{i + 1}</span><div className="action-copy"><h2>{a.action_text}</h2><p>{a.rationale}</p><span>{a.owner_role === "caregiver" ? "建议家属协助" : "建议本人完成"}</span></div><button className="round-check" aria-label={done.includes(a.action_id) ? "标记为未完成" : "标记为已完成"} onClick={() => setDone(v => v.includes(a.action_id) ? v.filter(x => x !== a.action_id) : [...v, a.action_id])}><Icon name="check"/></button></article>)}</div>
    <div className="safety-card"><div className="safety-symbol">!</div><div><h2>出现这些情况，请及时就医</h2><p>呼吸困难明显加重、口唇发紫、意识不清或持续高热。内容来自通用知识，具体情况请听从专业人员判断。</p></div></div>
  </main>;
}

function HomeView({ report, navigate }: { report: Report; navigate: (v: View) => void }) {
  return <main className="page home-page"><section className="welcome"><div><span className="eyebrow">下午好</span><h1>恢复的每一步<br/><em>都值得被温柔看见</em></h1><p>我们把材料里的重要信息整理好了，你可以从最关心的地方开始。</p><button className="primary-button" onClick={() => navigate("report")}>查看关怀报告 <Icon name="arrow" size={18}/></button></div><div className="warm-visual" aria-hidden="true"><div className="sun"/><div className="hill hill-one"/><div className="hill hill-two"/><div className="plant"><i/><i/><b/></div><span className="float-heart">♡</span></div></section>
    <section className="overview"><div className="section-label"><div><span className="eyebrow">今日概览</span><h2>你的关怀进度</h2></div><span className="date">9月25日 · 周五</span></div><div className="overview-grid"><button className="overview-card report-card" onClick={() => navigate("report")}><span className="card-icon peach"><Icon name="file"/></span><span><small>关怀报告</small><strong>6 个部分已整理</strong><em><Icon name="shield" size={15}/> 内容可追溯</em></span><Icon name="arrow"/></button><button className="overview-card" onClick={() => navigate("actions")}><span className="card-icon green"><Icon name="check"/></span><span><small>优先行动</small><strong>{report.actions.length} 件事等你完成</strong><em>从简单的一件开始</em></span><Icon name="arrow"/></button></div></section>
    <section className="care-note"><Icon name="spark"/><div><strong>给今天的你</strong><p>康复有快有慢，不需要拿自己的进度和别人比较。今天照顾好自己，就是很重要的一步。</p></div></section>
  </main>;
}

function ProfileView({ mode, setMode, onLoad, loading, error }: { mode: "demo" | "live"; setMode: (m: "demo" | "live") => void; onLoad: (values: { token: string; caseId: string; version: number }) => void; loading: boolean; error: string }) {
  const [token, setToken] = useState(localStorage.getItem("zhongan_token") || ""); const [caseId, setCaseId] = useState(""); const [version, setVersion] = useState(1);
  return <main className="page"><header className="page-heading"><div><span className="eyebrow">我的</span><h1>阅读与数据设置</h1><p>演示数据有清晰标记；真实模式只显示服务器实际返回的内容。</p></div></header>
    <section className="settings-card"><div className="settings-row"><div><strong>当前数据</strong><p>{mode === "demo" ? "合成演示案例，不含真实个人信息" : "连接真实 API"}</p></div><div className="segmented"><button className={mode === "demo" ? "active" : ""} onClick={() => setMode("demo")}>合成演示</button><button className={mode === "live" ? "active" : ""} onClick={() => setMode("live")}>真实接口</button></div></div>{mode === "live" && <form className="connection-form" onSubmit={e => { e.preventDefault(); localStorage.setItem("zhongan_token", token); onLoad({ token, caseId, version }); }}><label>访问令牌<input type="password" value={token} onChange={e => setToken(e.target.value)} required autoComplete="off" placeholder="仅保存在本机浏览器"/></label><label>案件 ID<input value={caseId} onChange={e => setCaseId(e.target.value)} required placeholder="UUID"/></label><label>报告版本<input type="number" min="1" value={version} onChange={e => setVersion(Number(e.target.value))}/></label><button className="primary-button" disabled={loading}>{loading ? "正在连接…" : "读取报告"}</button>{error && <p className="form-error" role="alert">{error}</p>}</form>}</section>
    <section className="privacy-card"><Icon name="shield"/><div><strong>你的材料如何被使用</strong><p>报告只展示当前授权范围内的案件内容。引用原文时仅显示与结论相关的片段。</p></div></section>
  </main>;
}

export default function App() {
  const [view, setView] = useState<View>("home"); const [mode, setModeState] = useState<"demo" | "live">("demo"); const [report, setReport] = useState<Report>(demoReport); const [evidence, setEvidence] = useState<Evidence | null>(null); const [token, setToken] = useState(""); const [loading, setLoading] = useState(false); const [error, setError] = useState("");
  const nav = useMemo(() => [{ key: "home", label: "首页", icon: "home" }, { key: "report", label: "关怀报告", icon: "file" }, { key: "actions", label: "行动", icon: "heart" }, { key: "profile", label: "我的", icon: "user" }] as {key: View; label: string; icon: IconName}[], []);
  const setMode = (m: "demo" | "live") => { setModeState(m); setError(""); if (m === "demo") setReport(demoReport); };
  const load = async ({ token: value, caseId, version }: { token: string; caseId: string; version: number }) => { setLoading(true); setError(""); try { const next = await getReport(caseId, version, value); setReport(next); setToken(value); setView("report"); } catch (e) { setError(e instanceof ApiError ? `${e.message}${e.traceId ? ` · 追踪号 ${e.traceId}` : ""}` : "暂时无法连接服务器，请稍后再试。"); } finally { setLoading(false); } };
  const showEvidence = async (id: string) => { if (mode === "demo") { setEvidence(demoEvidence[id] || null); return; } try { setEvidence(await getEvidence(id, token)); } catch (e) { setError(e instanceof Error ? e.message : "证据读取失败"); } };
  return <div className="app-shell">
    <aside className="side-nav"><a className="brand" href="#" onClick={e => { e.preventDefault(); setView("home"); }}><span className="brand-symbol"><Icon name="heart"/></span><span><strong>暖愈智护</strong><small>让康复更有温度</small></span></a><nav>{nav.map(n => <button key={n.key} className={view === n.key ? "active" : ""} onClick={() => setView(n.key)}><Icon name={n.icon}/><span>{n.label}</span>{n.key === "report" && <i>6</i>}</button>)}</nav><div className="nav-foot"><Icon name="shield"/><span>隐私安全守护中</span></div></aside>
    <div className="content-shell"><div className="mobile-top"><a className="brand" href="#" onClick={e => { e.preventDefault(); setView("home"); }}><span className="brand-symbol"><Icon name="heart"/></span><strong>暖愈智护</strong></a><button className="icon-button" onClick={() => setView("profile")} aria-label="设置"><Icon name="settings"/></button></div>{mode === "demo" && <div className="demo-ribbon"><span>合成演示</span> 页面内容用于功能展示，不含真实个人信息</div>}
      {view === "home" && <HomeView report={report} navigate={setView}/>} {view === "report" && <ReportView report={report} onEvidence={showEvidence}/>} {view === "actions" && <ActionsView report={report}/>} {view === "profile" && <ProfileView mode={mode} setMode={setMode} onLoad={load} loading={loading} error={error}/>} 
    </div>
    <EvidencePanel evidence={evidence} onClose={() => setEvidence(null)}/>{evidence && <button className="drawer-backdrop" onClick={() => setEvidence(null)} aria-label="关闭证据"/>}
    <nav className="bottom-nav">{nav.map(n => <button key={n.key} className={view === n.key ? "active" : ""} onClick={() => setView(n.key)}><Icon name={n.icon}/><span>{n.label}</span></button>)}</nav>
  </div>;
}
