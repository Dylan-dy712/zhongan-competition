import homeChat from '../../../output_dir/product-design/assets/home-chat.webp';
import documentArt from '../../../output_dir/product-design/assets/onboard-document.webp';
export type ClaimFile={id:string;name:string;size:number;category:string;sample:boolean;url:string|null;file:File};
export const initialClaimForm=()=>({kind:'住院医疗',cause:'疾病',diagnosis:'',start:'',end:'',incident:'',description:'',total:'',social:'否',other:'否'});
export type ClaimForm=Record<keyof ReturnType<typeof initialClaimForm>,string>;
const escape=(value:unknown)=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
const paths:Record<string,string>={leaf:'M20 3C8 2 2 8 5 15s15 7 15-12ZM4 21 15 10',chat:'M20 11a8 8 0 0 1-8 8H5l-3 3V11a9 9 0 0 1 18 0ZM7 10h8m-8 4h5',file:'M7 3h10a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2ZM9 8h6m-6 4h6m-6 4h4',arrow:'m9 5 7 7-7 7',back:'m15 5-7 7 7 7',user:'M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM4 21v-2a8 8 0 0 1 16 0v2',cost:'M5 5h14v14H5V5Zm3 3 4 4 4-4m-4 4v5m-4-4h8',care:'M12 20 3 11a5 5 0 0 1 9-5 5 5 0 0 1 9 5l-9 9Z',hospital:'M4 21V5h16v16M2 21h20M9 21v-5h6v5M9 8h6m-3-3v6',send:'m4 4 17 8-17 8 3-8-3-8Zm3 8h14',check:'m5 12 4 4L19 6'};
function icon(name:string,size=21){return `<svg aria-hidden="true" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="${paths[name]||paths.file}"/></svg>`}
export function claimTemplate(form:ClaimForm,selected:ClaimFile[],step:number,finished=false){
  const groups = () => [
    {id:'record',title:'病历相关资料',hint:'病历、诊断证明、出院小结、检查报告、手术记录及处方等，按本次就医情况上传。',required:true},
    {id:'invoice',title:'发票相关资料',hint:'医疗收费票据或电子发票，可一并上传费用明细及结算资料。',required:true},
  ];
  const action = (label:string, name:string, cls = 'claim-primary') => `<button type="button" class="${cls}" data-claim-action="${name}">${label}</button>`;
  const activeFiles = () => selected.filter(f=>groups().some(g=>g.id===f.category));

  const fileTiles = (files:ClaimFile[], group?:{id:string;title:string}) => `<div class="claim-file-grid">${files.map(f => `<div class="claim-file-tile">
    ${f.url?`<button class="claim-image-preview" data-claim-preview="${f.id}" aria-label="查看${escape(f.name)}"><img src="${f.url}" alt="${escape(f.name)}" loading="lazy"></button>`:`<div class="claim-document-preview" aria-label="${f.sample?'示例 PDF':'PDF 文件'}">${icon('file',28)}<b>PDF</b><span>${f.sample?'示例材料':'已选择'}</span></div>`}
    <button class="claim-tile-remove" data-claim-remove="${f.id}" aria-label="移除${escape(f.name)}">×</button>
    <div class="claim-tile-caption"><strong title="${escape(f.name)}">${escape(f.name)}</strong><small>${Math.ceil(f.size/1024)} KB · ${f.sample?'示例':'仅本地'}</small></div>
  </div>`).join('')}${group?`<button class="claim-upload-tile" data-claim-action="pick-${group.id}" aria-label="添加${group.title}"><span aria-hidden="true">＋</span><strong>${files.length?'继续添加':'添加材料'}</strong><small>照片 / PDF</small></button>`:''}</div>`;
  const field = (key:string,label:string,type='text',placeholder='') => `<label class="claim-field"><span>${label}</span><input data-claim-field="${key}" name="${key}" type="${type}" value="${escape(form[key as keyof ClaimForm])}" placeholder="${placeholder}" ${type==='number'?'min="0.01" step="0.01" inputmode="decimal"':''} maxlength="160" autocomplete="off"></label>`;
  const choice = (key:string,label:string,options:string[]) => `<label class="claim-field"><span>${label}</span><select data-claim-field="${key}">${options.map(value=>`<option ${form[key as keyof ClaimForm]===value?'selected':''}>${value}</option>`).join('')}</select></label>`;
  function information() {
    return `<div class="claim-intro claim-intro-illustrated"><span class="claim-eyebrow">医疗保障 · 安心申请</span><h1>申请医疗理赔</h1><p>把这次就医的事，一步步整理好。</p><img src="${homeChat}" alt="" class="claim-intro-mascot"></div>
      <section class="claim-policy"><div class="claim-policy-label"><span>本次申请保单</span><span class="claim-tag">演示保单</span></div><div class="claim-policy-product"><span class="claim-policy-icon">${icon("care",28)}</span><div><h2>个人医疗保险</h2><p>保单号 DEMO · **** 2026</p></div></div><div class="claim-policy-person"><span>被保险人 <strong>小安</strong></span><span>申请关系 <strong>本人</strong></span></div></section>
      <div class="claim-section-heading"><h2>就医信息</h2>${action('填入示例信息','example','claim-samples')}</div>
      <section class="claim-form-card">${choice('kind','就医类型',['住院医疗','门急诊医疗'])}${choice('cause','出险原因',['疾病','意外'])}${field('diagnosis','诊断或症状','text','填写病历上的诊断或症状')}<div class="claim-fields-pair">${field('start',form.kind==='住院医疗'?'入院日期':'就诊日期','date')}${form.kind==='住院医疗'?field('end','出院日期','date'):''}</div>${form.cause==='意外'?`${field('incident','事故发生日期','date')}${field('description','事故经过与地点','text','简述发生时间、地点及经过')}`:''}</section>
      <div class="claim-section-heading"><h2>费用与结算</h2><span class="claim-section-note">以发票金额为准</span></div><section class="claim-form-card">${field('total','医疗费用总额（元）','number','请输入金额')}<p class="claim-field-note">填写医疗费用总额，不是预计赔付金额。</p>${choice('social','是否已经医保结算',['否','是'])}${choice('other','是否已获其他保险或单位赔付',['否','是'])}</section>
      <div class="claim-section-heading"><h2>申请人与收款信息</h2><span class="claim-section-note">示例资料</span></div><section class="claim-form-card"><dl class="claim-info-list"><div><dt>申请人 / 被保险人</dt><dd>小安（本人）</dd></div><div><dt>联系手机</dt><dd>138 **** 0000</dd></div><div><dt>身份资料</dt><dd>身份证正反面 · 示例已备</dd></div><div><dt>收款账户</dt><dd>本人借记卡 · 尾号 0000</dd></div></dl><p class="claim-field-note">示例身份与账户，未完成实名核验或银行卡绑定。</p></section>
      <p class="claim-demo-note">仅使用合成测试信息。资料准备与关怀分析不会向保险公司提交理赔申请。</p>`;
  }

  function upload() {
    const required=groups().filter(g=>g.required),ready=required.filter(g=>selected.some(f=>f.category===g.id)).length;
    return `<div class="claim-intro claim-intro-illustrated"><span class="claim-eyebrow">${escape(form.kind)} · ${escape(form.cause)}</span><h1>准备本次理赔材料</h1><p>分好类，少遗漏，核对起来更轻松。</p><img src="${documentArt}" alt="" class="claim-intro-mascot"></div>
      <section class="claim-case"><span class="claim-case-icon">${icon('file',24)}</span><div><strong>${escape(form.kind)} · ${escape(form.diagnosis)}</strong><small>小安 · ${escape(form.start)}${form.kind==='住院医疗'?' 至 '+escape(form.end):''}</small></div></section>
      <div class="claim-material-progress"><div><strong>材料准备进度</strong><span>必需类别 ${ready} / ${required.length}</span></div><progress value="${ready}" max="${required.length}" aria-label="必需材料类别准备进度"></progress><small>已选择 ${activeFiles().length} 份材料 · 按下方类别补充</small></div><div class="claim-section-heading"><h2>材料清单</h2><span class="claim-section-note">按类别整理</span></div>
      <p class="claim-help">支持 PDF / JPG / PNG，每份不超过 10 MB，上传数量不限，可多次添加。</p>
      ${groups().map((group,index) => `<section class="claim-material"><div class="claim-material-heading"><span class="claim-material-number">${String(index+1).padStart(2,"0")}</span><h3>${group.title}</h3><span class="${group.required?'claim-required':'claim-optional'}">${selected.some(f=>f.category===group.id)?'已添加':group.required?'必需':'选填'}</span></div><p>${group.hint}</p>
        ${fileTiles(selected.filter(f=>f.category===group.id),group)}</section>`).join('')}
      <p class="claim-field-note">本清单用于演示，实际材料要求以对应保险产品为准；请妥善保留原始单据，审核时可能需补充。</p>
      <p class="claim-demo-note">文件在确认前仅在本机预览；确认后上传至当前账号用于关怀分析。仅使用合成测试材料，不提交真实保险理赔。</p>`;
  }
  const summaryRows = () => `<dl class="claim-info-list"><div><dt>理赔类型</dt><dd>${escape(form.kind)} / ${escape(form.cause)}</dd></div><div><dt>诊断或症状</dt><dd>${escape(form.diagnosis)}</dd></div><div><dt>就医日期</dt><dd>${escape(form.start)}${form.kind==='住院医疗'?' 至 '+escape(form.end):''}</dd></div>${form.cause==='意外'?`<div><dt>事故日期</dt><dd>${escape(form.incident)}</dd></div><div><dt>事故经过</dt><dd>${escape(form.description)}</dd></div>`:''}<div><dt>费用总额</dt><dd>¥ ${Number(form.total).toFixed(2)}</dd></div><div><dt>医保结算 / 其他赔付</dt><dd>${form.social} / ${form.other}</dd></div></dl>`;
  function review() {
    return `<div class="claim-intro"><span class="claim-eyebrow">即将完成 · 最后核对一下</span><h1>确认理赔申请</h1><p>确认每一项，再安心提交。</p></div><section class="claim-review-overview"><span>本次申请医疗费用</span><strong><small>¥</small> ${Number(form.total).toLocaleString("zh-CN",{minimumFractionDigits:2,maximumFractionDigits:2})}</strong><div><span>${escape(form.kind)}</span><span>已选 ${activeFiles().length} 份材料</span></div><p>费用总额，以最终审核结果确定赔付。</p></section><section class="claim-form-card"><div class="claim-review-head"><h2>申请信息</h2>${action('修改','step-0','claim-text')}</div>${summaryRows()}</section><section class="claim-form-card"><div class="claim-review-head"><h2>申请人与收款</h2><span class="claim-tag">虚构示例</span></div><p>小安 · 本人申请<br>138 **** 0000<br>本人借记卡 · 尾号 0000</p><p class="claim-field-note">身份资料为演示占位，未完成真实核验。</p></section><section class="claim-form-card"><div class="claim-review-head"><h2>材料共 ${activeFiles().length} 份</h2>${action('修改','step-1','claim-text')}</div>${groups().map(g=>`<div class="claim-review-material"><strong>${g.title}</strong><small>${selected.filter(f=>f.category===g.id).map(f=>escape(f.name)).join('、')||'未提供 · 按需补充'}</small></div>`).join('')}</section><details class="claim-form-card"><summary>申请说明与资料用途</summary><p>正式申请需确认信息与材料真实、完整，资料用于本次理赔受理和审核。是否属于保险责任、赔付金额及补件要求由保险公司审核确定。</p><p>就医关怀为自愿服务，上传前单独确认资料用途，不作为正式理赔提交条件。</p><p>本系统不创建真实理赔申请；确认后将上述合成材料上传并用于关怀分析。</p></details>`;
  }
  function success(done:boolean) {
    return `<div class="claim-success"><div class="claim-success-art" aria-hidden="true"><span class="claim-success-orbit"></span><span class="claim-success-glow"></span><span class="claim-success-medal"><svg viewBox="0 0 80 80" fill="none"><path d="m22 40 13 13 27-29" stroke="white" stroke-width="11" stroke-linecap="round" stroke-linejoin="round"/></svg></span><span class="claim-spark spark-one">✦</span><span class="claim-spark spark-two">✦</span><span class="claim-spark spark-three">✦</span></div><h1>${done?'本次提交已完成':'资料已进入你的关怀空间'}</h1><p>${done?'本次材料已上传。':'材料准备这一步，已经完成了。'}</p></div>
      <section class="claim-receipt"><h2>本次提交</h2><dl><div><dt>理赔类型</dt><dd>${escape(form.kind)}</dd></div><div><dt>材料份数</dt><dd>${activeFiles().length} 份</dd></div><div><dt>当前状态</dt><dd>已上传至关怀账号</dd></div></dl><p>后续流程：受理 → 审核（可能补件）→ 理赔结论。实际进度及赔付结果以保险公司通知为准，本页面未创建真实案件。</p></section>
      <section class="claim-care-card" id="claim-care-entry"><button class="claim-care-hit" data-go="welcome" aria-label="查看相关报告，了解治疗、费用与后续安排" aria-describedby="claim-care-use"></button><img class="claim-care-mascot" src="${homeChat}" alt="暖暖陪你了解就医关怀"><span class="claim-eyebrow">暖愈智护 · 就医关怀</span><h2>理赔之后，<br>你的康复也值得被关心</h2><p>难懂的病历、看不明白的费用，<br>还有回家后的下一步，暖暖陪你一起梳理。</p><ul><li>看懂本次病情与治疗经过</li><li>了解费用，准备下次就医</li><li>整理康复事项，记住复查安排</li></ul><div class="claim-care-card-cta"><strong>查看相关报告</strong><span>看懂病历 · 整理康复安排</span><b aria-hidden="true">›</b></div><small id="claim-care-use">点击查看相关报告后开始分析本次上传材料，分析结果以系统真实处理进度为准。</small></section>`;
  }

return {groups:groups(),html:`<div class="claim-shell ${finished?'claim-result-shell':'claim-form-shell'}"><header class="claim-header"><button type="button" class="claim-back" data-claim-action="exit" aria-label="返回首页"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m15 5-7 7 7 7"/></svg>返回</button><strong>医疗理赔</strong><span>资料准备</span></header><ol class="claim-steps" aria-label="理赔申请步骤">${['填写申请','上传材料','核对提交'].map((label,i)=>`<li class="${finished||step>=i?'active':''}"><button type="button" data-claim-action="step-${i}" ${finished||i>step?'disabled':''} ${!finished&&step===i?'aria-current="step"':''}><span>${finished||step>i?'✓':i+1}</span>${label}</button></li>`).join('')}</ol><div class="claim-main">${finished?success(true):[information,upload,review][step]()}</div></div>`};
}
export function validateClaimInfo(form:ClaimForm){
 if(!form.diagnosis.trim())return '请填写病历上的诊断或症状。';
 if(!form.start)return '请选择就诊或入院日期。';
 if(form.kind==='住院医疗'&&(!form.end||form.end<form.start))return '出院日期不能为空，且不能早于入院日期。';
 if(form.cause==='意外'&&(!form.incident||form.incident>form.start||!form.description.trim()))return '请核对事故日期并填写事故经过。';
 if(!/^\d+(\.\d{1,2})?$/.test(form.total)||!Number.isFinite(Number(form.total))||Number(form.total)<=0)return '费用总额须大于 0，最多保留两位小数。';
 return '';
}
