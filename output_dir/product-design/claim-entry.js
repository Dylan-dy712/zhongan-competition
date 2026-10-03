// Claim entry for the standalone proposal. Selection is local; no claim is sent.
(() => {
  const baseRender = render;
  let selected = [], sequence = 0, category = '', issue = '', submitted = false, step = 0, confirmed = false;
  const form = { kind:'住院医疗', cause:'疾病', diagnosis:'', start:'', end:'', incident:'', description:'', total:'', social:'否', other:'否' };
  const groups = () => [
    {id:'record',title:form.kind==='住院医疗'?'病历与出院小结':'门急诊病历',hint:form.kind==='住院医疗'?'住院病历、出院小结及诊断证明，包含姓名、就诊日期和医院信息。':'门急诊病历及诊断证明，包含姓名、就诊日期和医院信息。',required:true},
    {id:'invoice',title:'医疗费用发票',hint:'上传清晰完整的医疗收费票据或电子发票，保留票据号码与金额。',required:true},
    {id:'detail',title:'费用明细清单',hint:'包含药品、检查、治疗等项目与金额，拍清全部页。',required:true},
    ...(form.social==='是'?[{id:'social',title:'医保结算单',hint:'已通过医保结算时提供，用于核对基金支付与个人承担金额。',required:true}]:[]),
    ...(form.other==='是'?[{id:'other',title:'其他渠道赔付证明',hint:'提供其他保险公司或单位的赔付、分割单据。',required:true}]:[]),
    ...(form.cause==='意外'?[{id:'accident',title:'意外事故证明',hint:'按事故情况提供相应证明；具体以保险公司要求为准。',required:false}]:[]),
    {id:'extra',title:'检查、手术与用药资料',hint:'与本次治疗相关的检查报告、手术记录、处方及用药明细，按实际情况补充。',required:false},
  ];
  const picker = document.createElement('input');
  picker.type = 'file'; picker.multiple = true; picker.hidden = true;
  picker.accept = 'image/jpeg,image/png,.jpg,.jpeg,.png'; picker.id = 'claim-file-picker';
  document.body.append(picker);
  const pdfPicker = document.createElement('input');
  pdfPicker.type='file'; pdfPicker.multiple=true; pdfPicker.hidden=true;
  pdfPicker.accept='application/pdf,.pdf'; pdfPicker.id='claim-pdf-picker';
  document.body.append(pdfPicker);
  const sourceDialog=document.createElement('dialog');
  sourceDialog.className='claim-upload-dialog';
  sourceDialog.setAttribute('aria-label','选择材料来源');
  sourceDialog.innerHTML='<div class="claim-preview-head"><strong>添加理赔材料</strong><button data-claim-action="close-source" aria-label="关闭材料来源">×</button></div><button class="claim-source-option" data-claim-action="choose-photo"><span>从相册选择图片</span><small>JPG、PNG 格式</small></button><button class="claim-source-option" data-claim-action="choose-pdf"><span>从文件选择 PDF</span><small>打开手机文件管理器，选择已保存的 PDF</small></button><p>每份不超过 10 MB，仅在本机选择</p>';
  document.body.append(sourceDialog);
  sourceDialog.addEventListener('click',e=>{if(e.target===sourceDialog)sourceDialog.close();});
  const action = (label, name, cls = 'claim-primary') => `<button type="button" class="${cls}" data-claim-action="${name}">${label}</button>`;
  const activeFiles = () => selected.filter(f=>groups().some(g=>g.id===f.category));
  const releaseFile = file => { if(file?.url) URL.revokeObjectURL(file.url); };
  const fileTiles = (files, group) => `<div class="claim-file-grid">${files.map(f => `<div class="claim-file-tile">
    ${f.url?`<button class="claim-image-preview" data-claim-preview="${f.id}" aria-label="查看${escape(f.name)}"><img src="${f.url}" alt="${escape(f.name)}" loading="lazy"></button>`:`<div class="claim-document-preview" aria-label="${f.sample?'示例 PDF':'PDF 文件'}">${icon('file',28)}<b>PDF</b><span>${f.sample?'示例材料':'已选择'}</span></div>`}
    <button class="claim-tile-remove" data-claim-remove="${f.id}" aria-label="移除${escape(f.name)}">×</button>
    <div class="claim-tile-caption"><strong title="${escape(f.name)}">${escape(f.name)}</strong><small>${Math.ceil(f.size/1024)} KB · ${f.sample?'示例':'仅本地'}</small></div>
  </div>`).join('')}${group?`<button class="claim-upload-tile" data-claim-action="pick-${group.id}" aria-label="添加${group.title}"><span aria-hidden="true">＋</span><strong>${files.length?'继续添加':'添加材料'}</strong><small>照片 / PDF</small></button>`:''}</div>`;
  const previewDialog = document.createElement('dialog');
  previewDialog.className='claim-preview-dialog';
  previewDialog.setAttribute('aria-label','材料图片预览');
  document.body.append(previewDialog);
  previewDialog.addEventListener('click',e=>{if(e.target===previewDialog||e.target.closest('[data-close-preview]'))previewDialog.close();});
  previewDialog.addEventListener('close',()=>{previewDialog.innerHTML='';});
  const field = (key,label,type='text',placeholder='') => `<label class="claim-field"><span>${label}</span><input data-claim-field="${key}" name="${key}" type="${type}" value="${escape(form[key])}" placeholder="${placeholder}" ${type==='number'?'min="0.01" step="0.01" inputmode="decimal"':''} maxlength="160" autocomplete="off"></label>`;
  const choice = (key,label,options) => `<label class="claim-field"><span>${label}</span><select data-claim-field="${key}">${options.map(value=>`<option ${form[key]===value?'selected':''}>${value}</option>`).join('')}</select></label>`;
  function information() {
    return `<div class="claim-intro claim-intro-illustrated"><span class="claim-eyebrow">医疗保障 · 安心申请</span><h1>申请医疗理赔</h1><p>把这次就医的事，一步步整理好。</p><img src="assets/home-chat.webp?img=20261002c" alt="" class="claim-intro-mascot"></div>
      <section class="claim-policy"><div class="claim-policy-label"><span>本次申请保单</span><span class="claim-tag">演示保单</span></div><div class="claim-policy-product"><span class="claim-policy-icon">${icon("care",28)}</span><div><h2>个人医疗保险</h2><p>保单号 DEMO · **** 2026</p></div></div><div class="claim-policy-person"><span>被保险人 <strong>小安</strong></span><span>申请关系 <strong>本人</strong></span></div></section>
      <div class="claim-section-heading"><h2>就医信息</h2>${action('填入示例信息','example','claim-samples')}</div>
      <section class="claim-form-card">${choice('kind','就医类型',['住院医疗','门急诊医疗'])}${choice('cause','出险原因',['疾病','意外'])}${field('diagnosis','诊断或症状','text','填写病历上的诊断或症状')}<div class="claim-fields-pair">${field('start',form.kind==='住院医疗'?'入院日期':'就诊日期','date')}${form.kind==='住院医疗'?field('end','出院日期','date'):''}</div>${form.cause==='意外'?`${field('incident','事故发生日期','date')}${field('description','事故经过与地点','text','简述发生时间、地点及经过')}`:''}</section>
      <div class="claim-section-heading"><h2>费用与结算</h2><span class="claim-section-note">以发票金额为准</span></div><section class="claim-form-card">${field('total','医疗费用总额（元）','number','请输入金额')}<p class="claim-field-note">填写医疗费用总额，不是预计赔付金额。</p>${choice('social','是否已经医保结算',['否','是'])}${choice('other','是否已获其他保险或单位赔付',['否','是'])}</section>
      <div class="claim-section-heading"><h2>申请人与收款信息</h2><span class="claim-section-note">示例资料</span></div><section class="claim-form-card"><dl class="claim-info-list"><div><dt>申请人 / 被保险人</dt><dd>小安（本人）</dd></div><div><dt>联系手机</dt><dd>138 **** 0000</dd></div><div><dt>身份资料</dt><dd>身份证正反面 · 示例已备</dd></div><div><dt>收款账户</dt><dd>本人借记卡 · 尾号 0000</dd></div></dl><p class="claim-field-note">示例身份与账户，未完成实名核验或银行卡绑定。</p></section>
      <p class="claim-demo-note">流程演示，请使用测试信息。刷新后清空，不发起真实理赔。</p>`;
  }

  function upload() {
    const required=groups().filter(g=>g.required),ready=required.filter(g=>selected.some(f=>f.category===g.id)).length;
    return `<div class="claim-intro claim-intro-illustrated"><span class="claim-eyebrow">${escape(form.kind)} · ${escape(form.cause)}</span><h1>准备本次理赔材料</h1><p>分好类，少遗漏，核对起来更轻松。</p><img src="assets/onboard-document.webp?img=20261002c" alt="" class="claim-intro-mascot"></div>
      <section class="claim-case"><span class="claim-case-icon">${icon('file',24)}</span><div><strong>${escape(form.kind)} · ${escape(form.diagnosis)}</strong><small>小安 · ${escape(form.start)}${form.kind==='住院医疗'?' 至 '+escape(form.end):''}</small></div></section>
      <div class="claim-material-progress"><div><strong>材料准备进度</strong><span>必需类别 ${ready} / ${required.length}</span></div><progress value="${ready}" max="${required.length}" aria-label="必需材料类别准备进度"></progress><small>已选择 ${activeFiles().length} 份材料 · 按下方类别补充</small></div><div class="claim-section-heading"><h2>材料清单</h2><span class="claim-section-note">按类别整理</span></div>
      <p class="claim-help">支持 PDF / JPG / PNG，每份不超过 10 MB，最多 20 份。</p>
      ${groups().map((group,index) => `<section class="claim-material"><div class="claim-material-heading"><span class="claim-material-number">${String(index+1).padStart(2,"0")}</span><h3>${group.title}</h3><span class="${group.required?'claim-required':'claim-optional'}">${selected.some(f=>f.category===group.id)?'已添加':group.required?'必需':'选填'}</span></div><p>${group.hint}</p>
        ${fileTiles(selected.filter(f=>f.category===group.id),group)}</section>`).join('')}
      <p class="claim-field-note">本清单用于演示，实际材料要求以对应保险产品为准；请妥善保留原始单据，审核时可能需补充。</p>
      <p class="claim-demo-note">原型演示：文件仅在本机选择，不上传、不保存，刷新后需重新选择。关怀用途将在进入暖愈后单独说明并征求同意。当前关怀内容为预置示例，不是所选文件的分析结果。</p>`;
  }
  const summaryRows = () => `<dl class="claim-info-list"><div><dt>理赔类型</dt><dd>${escape(form.kind)} / ${escape(form.cause)}</dd></div><div><dt>诊断或症状</dt><dd>${escape(form.diagnosis)}</dd></div><div><dt>就医日期</dt><dd>${escape(form.start)}${form.kind==='住院医疗'?' 至 '+escape(form.end):''}</dd></div>${form.cause==='意外'?`<div><dt>事故日期</dt><dd>${escape(form.incident)}</dd></div><div><dt>事故经过</dt><dd>${escape(form.description)}</dd></div>`:''}<div><dt>费用总额</dt><dd>¥ ${Number(form.total).toFixed(2)}</dd></div><div><dt>医保结算 / 其他赔付</dt><dd>${form.social} / ${form.other}</dd></div></dl>`;
  function review() {
    return `<div class="claim-intro"><span class="claim-eyebrow">即将完成 · 最后核对一下</span><h1>确认理赔申请</h1><p>确认每一项，再安心提交。</p></div><section class="claim-review-overview"><span>本次申请医疗费用</span><strong><small>¥</small> ${Number(form.total).toLocaleString("zh-CN",{minimumFractionDigits:2,maximumFractionDigits:2})}</strong><div><span>${escape(form.kind)}</span><span>已选 ${activeFiles().length} 份材料</span></div><p>费用总额，以最终审核结果确定赔付。</p></section><section class="claim-form-card"><div class="claim-review-head"><h2>申请信息</h2>${action('修改','step-0','claim-text')}</div>${summaryRows()}</section><section class="claim-form-card"><div class="claim-review-head"><h2>申请人与收款</h2><span class="claim-tag">虚构示例</span></div><p>小安 · 本人申请<br>138 **** 0000<br>本人借记卡 · 尾号 0000</p><p class="claim-field-note">身份资料为演示占位，未完成真实核验。</p></section><section class="claim-form-card"><div class="claim-review-head"><h2>材料共 ${activeFiles().length} 份</h2>${action('修改','step-1','claim-text')}</div>${groups().map(g=>`<div class="claim-review-material"><strong>${g.title}</strong><small>${selected.filter(f=>f.category===g.id).map(f=>escape(f.name)).join('、')||'未提供 · 按需补充'}</small></div>`).join('')}</section><details class="claim-form-card"><summary>申请说明与资料用途</summary><p>正式申请需确认信息与材料真实、完整，资料用于本次理赔受理和审核。是否属于保险责任、赔付金额及补件要求由保险公司审核确定。</p><p>就医关怀为自愿服务，在提交后的独立页面说明用途并征求同意，不作为理赔提交条件。</p><p>本原型不创建真实理赔申请，此处勾选仅演示确认步骤。</p></details>`;
  }
  function success(done) {
    return `<div class="claim-success"><div class="claim-success-art" aria-hidden="true"><span class="claim-success-orbit"></span><span class="claim-success-glow"></span><span class="claim-success-medal"><svg viewBox="0 0 80 80" fill="none"><path d="m22 40 13 13 27-29" stroke="white" stroke-width="11" stroke-linecap="round" stroke-linejoin="round"/></svg></span><span class="claim-spark spark-one">✦</span><span class="claim-spark spark-two">✦</span><span class="claim-spark spark-three">✦</span></div><h1>${done?'本次提交已完成':'理赔材料提交成功'}</h1><p>${done?'本次流程演示已完成。':'材料准备这一步，已经完成了。'}</p></div>
      <section class="claim-receipt"><h2>本次提交</h2><dl><div><dt>理赔类型</dt><dd>${escape(form.kind)}</dd></div><div><dt>材料份数</dt><dd>${activeFiles().length} 份</dd></div><div><dt>当前状态</dt><dd>模拟待受理</dd></div></dl><p>后续流程：受理 → 审核（可能补件）→ 理赔结论。实际进度及赔付结果以保险公司通知为准，本页面未创建真实案件。</p></section>
      <section class="claim-care-card" id="claim-care-entry"><button class="claim-care-hit" data-go="welcome" aria-label="获取康复指引，了解治疗、费用与后续安排" aria-describedby="claim-care-use"></button><img class="claim-care-mascot" src="assets/home-chat.webp?img=20261002c" alt="暖暖陪你了解就医关怀"><span class="claim-eyebrow">暖愈智护 · 就医关怀</span><h2>理赔之后，<br>你的康复也值得被关心</h2><p>难懂的病历、看不明白的费用，<br>还有回家后的下一步，暖暖陪你一起梳理。</p><ul><li>看懂本次病情与治疗经过</li><li>了解费用，准备下次就医</li><li>整理康复事项，记住复查安排</li></ul><div class="claim-care-card-cta"><strong>获取康复指引</strong><span>看懂病历 · 整理康复安排</span><b aria-hidden="true">›</b></div><small id="claim-care-use">自愿使用，进入后单独确认资料用途。当前为预置病例，不分析所选文件。</small></section>`;
  }
  render = function() {
    baseRender();
    const id = pageId(), isClaim = ['claim','claim-success','claim-done'].includes(id);
    main.classList.toggle('claim-page',isClaim);
    if (!isClaim) return;
    if(id==='claim'&&submitted){submitted=false;confirmed=false;}
    const validResult = id!=='claim' && submitted;
    nav.style.display='none';
    main.innerHTML = `<div class="claim-shell ${validResult?'claim-result-shell':'claim-form-shell'}"><header class="claim-header"><strong>医疗理赔</strong><span>流程演示</span></header><ol class="claim-steps" aria-label="理赔申请步骤">${['填写申请','上传材料','核对提交'].map((label,i)=>`<li class="${validResult||step>=i?'active':''}"><button data-claim-action="step-${i}" ${validResult||i>step?'disabled':''} ${!validResult&&step===i?'aria-current="step"':''}><span>${validResult||step>i?'✓':i+1}</span>${label}</button></li>`).join('')}</ol><div class="claim-main">${validResult?success(id==='claim-done'):[information,upload,review][step]()}</div><div class="claim-error" role="alert" ${issue?'':'hidden'}>${escape(issue)}</div><footer class="claim-footer ${!validResult&&step===2?'claim-review-footer':''}">${!validResult&&step===2?`<label class="claim-consent claim-submit-check"><input type="checkbox" id="claim-confirm" ${confirmed?'checked':''}><span>我已核对信息并了解申请说明<small>流程演示，不产生真实理赔或法律授权</small></span></label>`:''}${validResult?`${action(id==='claim-done'?'申请详情':'完成',id==='claim-done'?'edit':'done','claim-finish')}<button class="claim-primary" data-go="welcome">获取康复指引 ${icon('arrow',16)}</button>`:`${step>0?action("返回修改",`step-${step-1}`,"claim-finish"):`<span>${step===1?`已添加 <strong>${activeFiles().length}</strong> 份`:`第 ${step+1} 步 / 共 3 步`}</span>`}${action(['下一步，上传材料','下一步，核对申请','确认提交申请'][step],step===2?'submit':'next')}`}</footer></div>`;
    // Bind the rendered controls directly; mobile WebViews must not depend on
    // a synthetic click reaching the shared document-level navigation handler.
    main.querySelectorAll('button[data-claim-action],button[data-claim-remove],button[data-claim-preview],button[data-go]').forEach(button=>{
      button.type='button';
      button.onclick=handleClaimClick;
    });
  };
  function validateInfo() {
    if(!form.diagnosis.trim())return ['请填写病历上的诊断或症状。','diagnosis'];
    if(!form.start)return ['请选择就诊或入院日期。','start'];
    if(form.kind==='住院医疗'&&(!form.end||form.end<form.start))return ['请填写出院日期，且不能早于入院日期。','end'];
    if(form.cause==='意外'&&(!form.incident||form.incident>form.start))return ['事故发生日期不能为空，且不能晚于首次就医日期。','incident'];
    if(form.cause==='意外'&&!form.description.trim())return ['请简述事故经过与地点。','description'];
    if(!/^\d+(\.\d{1,2})?$/.test(form.total)||!Number.isFinite(Number(form.total))||Number(form.total)<=0)return ['请填写大于 0 的费用总额，最多保留两位小数。','total'];
    return null;
  }
  function validateMaterials() {
    const missing=groups().filter(g=>g.required&&!selected.some(f=>f.category===g.id));
    return missing.length?'请补充：'+missing.map(g=>g.title).join('、')+'。':'';
  }
  function moveStep(next) {
    step=next;issue='';render();
    const title=main.querySelector('h1');if(title){title.tabIndex=-1;title.focus();}
  }
  function showIssue(text) {
    issue=text; const el=main.querySelector('.claim-error');
    if(el){el.hidden=!text;el.textContent=text;}
  }
  function handleClaimClick(e) {
    const button=e.currentTarget?.tagName==='BUTTON'?e.currentTarget:e.target?.closest?.('button'); if(!button||button.disabled)return;
    e.stopPropagation();
    if(button.dataset.go){go(button.dataset.go);return;}
    const preview=selected.find(f=>f.id===button.dataset.claimPreview);
    if(preview?.url){
      previewDialog.innerHTML=`<div class="claim-preview-head"><strong>${escape(preview.name)}</strong><button data-close-preview aria-label="关闭图片预览">×</button></div><img src="${preview.url}" alt="${escape(preview.name)}"><p>仅在本机预览，未上传</p>`;
      previewDialog.showModal();return;
    }
    const remove=button.dataset.claimRemove;
    if(remove){const top=main.querySelector('.claim-main')?.scrollTop||0;releaseFile(selected.find(f=>f.id===remove));selected=selected.filter(f=>f.id!==remove);confirmed=false;showIssue('');render();main.querySelector('.claim-main').scrollTop=top;return;}
    const key=button.dataset.claimAction;if(!key)return;
    if(key==='find-care'){const card=main.querySelector('#claim-care-entry');card?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'center'});card?.querySelector('.claim-care-hit')?.focus({preventScroll:true});return;}
    if(key.startsWith('pick-')){category=key.slice(5);sourceDialog.showModal();return;}
    if(key==='close-source'){sourceDialog.close();return;}
    if(key==='choose-photo'||key==='choose-pdf'){sourceDialog.close();(key==='choose-pdf'?pdfPicker:picker).click();return;}
    if(key.startsWith('step-')){const next=Number(key.slice(5));if(next<=step&&!submitted)moveStep(next);return;}
    if(key==='example'){
      Object.assign(form,{kind:'住院医疗',cause:'疾病',diagnosis:'肺炎（虚构示例）',start:'2026-09-20',end:'2026-09-25',total:'1200.00',social:'是',other:'否',incident:'',description:''});confirmed=false;issue='';render();return;
    }
    if(key==='next'){
      const invalid=validateInfo();
      if(invalid){moveStep(0);showIssue(invalid[0]);main.querySelector(`[data-claim-field="${invalid[1]}"]`)?.focus();return;}
      if(step===1&&validateMaterials()){showIssue(validateMaterials());return;}
      moveStep(Math.min(2,step+1));
    }
    if(key==='submit'){
      const invalid=validateInfo();if(invalid){moveStep(0);showIssue(invalid[0]);return;}
      if(validateMaterials()){moveStep(1);showIssue(validateMaterials());return;}
      confirmed=!!main.querySelector('#claim-confirm')?.checked;
      if(!confirmed){showIssue('请先勾选按钮上方的申请说明确认。');main.querySelector('#claim-confirm')?.focus();return;}
      submitted=true;issue='';go('claim-success');
    }
    if(key==='done'){
      selected.forEach(releaseFile);selected=[];step=0;submitted=false;confirmed=false;issue='';
      Object.assign(form,{kind:'住院医疗',cause:'疾病',diagnosis:'',start:'',end:'',incident:'',description:'',total:'',social:'否',other:'否'});
      go('claim');
    }
    if(key==='edit'){submitted=false;confirmed=false;step=2;go('claim');}
  }
  sourceDialog.querySelectorAll('button[data-claim-action]').forEach(button=>{button.type='button';button.onclick=handleClaimClick;});
  document.addEventListener('input', e=>{
    const key=e.target.dataset.claimField;
    if(key&&Object.hasOwn(form,key)){form[key]=e.target.value;confirmed=false;showIssue('');}
  });
  document.addEventListener('change', e=>{
    if(e.target.id==='claim-confirm'){confirmed=e.target.checked;showIssue('');return;}
    const key=e.target.dataset.claimField;
    if(key&&Object.hasOwn(form,key)){
      form[key]=e.target.value;confirmed=false;
      if(e.target.tagName==='SELECT'){
        if(key==='kind'){selected.filter(f=>f.category==='record').forEach(releaseFile);selected=selected.filter(f=>f.category!=='record');}
        const scroller=main.querySelector('.claim-main'),scrollTop=scroller?.scrollTop||0;
        render();main.querySelector('.claim-main').scrollTop=scrollTop;main.querySelector(`[data-claim-field="${key}"]`)?.focus({preventScroll:true});
      }
    }
  });
  function acceptSelectedFiles(input) {
    const scrollTop=main.querySelector('.claim-main')?.scrollTop||0;
    const errors=[];
    for(const file of input.files){
      if(!/\.(pdf|jpe?g|png)$/i.test(file.name)){errors.push('仅支持 PDF、JPG、PNG');continue;}
      if(!file.size||file.size>10*1024*1024){errors.push('文件须非空且不超过 10 MB');continue;}
      if(selected.some(f=>f.name===file.name&&f.size===file.size&&f.category===category))continue;
      if(selected.length>=20){errors.push('最多添加 20 份材料');break;}
      selected.push({id:`local-${++sequence}`,name:file.name,size:file.size,category,sample:false,url:/\.(jpe?g|png)$/i.test(file.name)?URL.createObjectURL(file):null});
    }
    input.value='';confirmed=false;issue=[...new Set(errors)].join('；');render();
    main.querySelector('.claim-main').scrollTop=scrollTop;
  }
  picker.addEventListener('change',()=>acceptSelectedFiles(picker));
  pdfPicker.addEventListener('change',()=>acceptSelectedFiles(pdfPicker));
  parentPage.claim='welcome'; parentPage['claim-success']='claim'; parentPage['claim-done']='claim-success';
  render();
})();
