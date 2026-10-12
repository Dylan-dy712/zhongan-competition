import {useState} from 'react';
import {CareRecommendations} from './CareRecommendations';

export const demoCases=[
 {code:'FY',name:'肺炎',text:'【合成演示材料，不是真实患者】\n出院小结\n入院日期：2026年9月20日\n出院日期：2026年9月25日\n出院诊断：肺炎\n出院情况：症状缓解。\n出院医嘱：一周后门诊复诊，携带出院小结。\n患者补充：不理解病历里的医学术语，希望解释。\n医疗收费票据\n医疗总费用：1200.00元\n费用清单合计：1100.00元\n两份材料金额不一致，待核对。'},
 {code:'FX',name:'骨折',text:'【合成演示材料，不是真实患者】\n出院记录\n入院日期：2026年9月10日\n出院日期：2026年9月15日\n出院诊断：桡骨远端骨折\n治疗经过：石膏固定。\n出院医嘱：按门诊预约复诊，携带影像资料。\n患者补充：出院材料未注明具体复诊日期，希望确认。\n医疗收费票据\n医疗总费用：3500.00元'},
 {code:'TN',name:'糖尿病',text:'【合成演示材料，不是真实患者】\n门诊病历\n就诊日期：2026年9月18日\n诊断：2型糖尿病\n本次检查：血糖检查。\n患者补充：希望了解检查目的，对既往用药记录有疑问，需医生核对。\n医嘱：记录居家血糖情况，复诊时带给医生查看；具体监测时间按既有医嘱执行。\n医疗收费票据\n医疗总费用：320.00元'},
];
export default function DemoShowcase({token,busy,canRun,onRun,onBack}:{token:string;busy:boolean;canRun:boolean;onRun:(file:File)=>void;onBack:()=>void}){
 const [selected,setSelected]=useState('FY'),[tab,setTab]=useState('case');const item=demoCases.find(c=>c.code===selected)!;
 const file=()=>new File([item.text],`合成演示-${item.name}.txt`,{type:'text/plain'});
 return <main className="encounter-overview"><header className="overview-hero"><small>演示与验收</small><h1>让每一步都有依据</h1><p>合成案例经过真实分析接口运行；机构画像来自明确标识的合成统计，不写入业务画像库。</p><button onClick={onBack}>返回首页</button></header>
 <nav className="overview-tabs" aria-label="演示内容">{[['case','运行案例'],['quality','机构画像'],['acceptance','验收口径']].map(([key,label])=><button key={key} aria-current={tab===key?'page':undefined} onClick={()=>setTab(key)}>{label}</button>)}</nav>
 <div className="overview-content">{tab==='case'&&<><h2>选择一个病种，从材料开始</h2><div className="care-recommend-chips">{demoCases.map(c=><button key={c.code} aria-pressed={selected===c.code} onClick={()=>setSelected(c.code)}>{c.name}</button>)}</div><pre className="demo-material">{item.text}</pre><p>流程：材料 → 结构化结果 → 痛点 → 温度指引 → 机构参考 → 反馈。运行后进入本次就医总览。</p><button className="care-primary" disabled={busy||!canRun} onClick={()=>onRun(file())}>{busy?'正在启动…':'用该合成材料运行分析'}</button>{!canRun&&<p>请先为当前关怀对象确认资料用途授权。</p>}<p className="muted">照片清晰度检查需通过上传入口选择 JPG／PNG；此处文本案例用于验证后续分析链路。</p></>}
 {tab==='quality'&&<CareRecommendations token={token} demo/>}
 {tab==='acceptance'&&<><h2>界面能力与实际评测分别核验</h2>{[
 ['KR1','结构化 JSON、字段级置信度和原文定位','整体 F1 ≥ 0.90、缺失率 < 5%：待固定数据集实测'],
 ['KR2','临床／费用／体验三类，至少五类痛点及归类原因','以实际运行结果统计，不按标签菜单数量判定覆盖'],
 ['KR3','肺炎、骨折、糖尿病三个案例入口','需逐例运行并检查指引是否符合各自材料'],
 ['KR4','合成画像：3病种 × 每病种5机构，7维；支持按需求给出至少2条理由','演示统计可复算，不代表真实机构排名'],
 ['KR5','上传、分析、引用、指引、机构参考、反馈','本地联调及现场端到端演示后确认'],
 ].map(([kr,ability,limit])=><article className="pain-card" key={kr}><h3>{kr}</h3><p>{ability}</p><small>{limit}</small></article>)}</>}
 </div></main>;
}
