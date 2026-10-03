// Standalone interaction prototype: no medical files leave the browser.
const uploadSheet=document.getElementById('upload-sheet');
let consent=false,imported=false,draft='',files=[],fileSequence=0,chatScroll=0;
const originalRender=render,originalMaterials=details.materials[1];
function saveDraft(){const q=document.getElementById('question');if(q)draft=q.value;const t=document.querySelector('.chat-thread');if(t)chatScroll=t.scrollTop;}
const navKey='warm-care-nav-v1';
const parentPage={'raw-cost':'evidence','claim-record':'evidence','raw-treatment':'materials','raw-other':'materials',summary:'records','raw-record':'materials','raw-test':'materials',consent:'welcome',intake:'consent',discharge:'materials',evidence:'materials',test:'materials',materials:'records',guide:'records',appointment:'home',visit:'home',privacy:'records',feedback:'guide'};
let renderedPage=pageId();
function rememberPosition(){saveDraft();positions[renderedPage]=main.scrollTop;}
function trail(){return history.state?.navKey===navKey ? history.state.trail||[] : [];}
function navigationState(id,parents){return {navKey,page:id,trail:parents,encounterId:careContext.activeId};}
go=function(id,options={}){
 if(id===pageId())return;
 rememberPosition();
 const root=options.tab||id==='home';
 const parents=root?[]:[...trail(),pageId()];
 history[root?'replaceState':'pushState'](navigationState(id,parents),'',`#/${id}`);
 render();
};
back=function(){
 if(uploadSheet.open){uploadSheet.close();return;}if(dialog.open){dialog.close();return;}
 rememberPosition();
 if(trail().length){history.back();return;}
 const id=pageId(),parent=id.startsWith('file-')?'materials':parentPage[id];
 if(parent){history.replaceState(navigationState(parent,[]),'',`#/${parent}`);render();}
};
function fileList(){return files.map(f=>`<div class="material-file"><strong>${escape(f.name)}</strong><p>${(f.size/1024).toFixed(0)} KB · 仅本地预览，未分析</p><div class="material-actions"><button data-go="file-${f.id}">查看</button><button data-remove="${f.id}" aria-label="移除 ${escape(f.name)}">移除</button></div></div>`).join('');}
function uploadButton(){return '<button class="outline" data-action="upload">＋ 补充看病资料</button>';}
function docIcon(kind){return `<span class="doc-icon">${kind==='cost'?'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2h9l4 4v16H5V2Zm3 7 3 4 3-4m-3 4v6m-3-6h6m-6 3h6"/></svg>':kind==='test'?'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6M10 3v7L5 19q-1 2 2 2h10q3 0 2-2l-5-9V3M8 15h8"/></svg>':icon('file',24)}</span>`;}
function welcome(){return `<img class="onboard-art welcome-art" src="assets/onboard-welcome.webp?img=20261002c" alt="暖暖陪你看懂看病资料"><div class="welcome-copy"><h1>出院后，<br>有不明白的慢慢问</h1><p>没看懂的报告、没算清的费用，<br>还有回家后要注意的事，都可以问暖暖。</p></div><section class="card"><h2>交过的资料，不用再传</h2><p>你同意后，暖暖可以结合理赔时交过的看病资料帮你解释。后来拿到的新报告，也可以补进来。</p><ul class="intake-list">${[['document','看懂这次治疗和费用'],['heart','记下回家后要注意的事'],['chat','带着你的资料问暖暖']].map(([im,t])=>`<li><img class="list-art" src="assets/onboard-${im}.webp?img=20261002c" alt=""><span>${t}</span></li>`).join('')}</ul>${btn('了解资料怎么使用 '+icon('arrow',16),'consent')}${btn('先去首页看看 '+icon('arrow',15),'home','link')}</section><p class="notice"></p>`;}
function consentPage(){return `<img class="onboard-art consent-art" src="assets/onboard-consent.webp?img=20261002c" alt="暖暖为你解释资料"><section class="card consent-card"><div class="card-copy"><h2>让暖暖结合你的资料回答</h2><p>你同意后，暖暖会结合你提供的病历、检查报告和用药记录，整理看病经过，并单独解释费用。门诊、住院都可以。</p></div><div class="consent-docs">${[['file','这次看病的总结','summary'],['cost','这次看病的费用','evidence']].map(([ic,t,to])=>`<button class="row" data-go="${to}">${docIcon(ic)}<span><strong>${t}</strong></span>${icon('arrow',16)}</button>`).join('')}</div><p class="card-copy">原始病历、检查报告等会保留在“看病资料”里，方便你查看和补充。</p>${btn('查看看病资料','materials','link')}<p class="card-copy">可以先不使用这些资料，之后再决定。</p><label class="consent-check"><input id="consent-check" type="checkbox" ${consent?'checked':''}><span>我已了解上述用途，同意使用我提供的看病资料为我提供帮助。</span></label><button class="primary" data-action="accept" ${consent?'':'disabled'}>继续</button>${btn('暂不使用，先问问暖暖 '+icon('arrow',15),'chat','link')}</section><p class="notice">你的资料仅用于你同意的用途。</p>`;}
function intake(){return `<img class="onboard-art materials-art" src="assets/onboard-materials.webp?img=20261002c" alt="本次看病的资料"><section class="card materials-card"><h2>这次看病的资料，放在一起</h2><p class="episode">门诊、住院资料都可以添加</p><ul class="intake-list">${[['file','病历记录'],['cost','费用单'],['test','检查报告'],['file','用药与治疗'],['file','其他资料']].map(([ic,t])=>`<li>${docIcon(ic)}<span>${t}</span><small>按实际资料整理</small></li>`).join('')}</ul><p>还有后来拿到的资料？可以一起补充。没有也可以直接继续。</p>${fileList()}${uploadButton()}${btn('带着这些资料问暖暖','chat')}<p class="notice">补充文件仅在当前页面预览；关闭或刷新页面后需要重新选择。</p></section>`;}
chat=function(){return `<div class="chat-context"><span>${imported?'本次就医 · 看病资料':'还没有使用你的理赔资料'}</span><button data-go="${imported?'materials':'consent'}">${imported?'查看资料':'使用已有资料'}</button></div><div class="chat-thread" aria-label="聊天记录"><div class="chat-intro"><img src="assets/home-chat.webp?img=20261002c" alt=""><div><h2>有不明白的，慢慢问</h2><small>${imported?'可以从你最在意的一件事开始。':'先了解资料怎么使用，也可以补充资料。'}</small></div></div><div class="bubble">${imported?'你想先了解看病经过、检查结果，还是费用？资料尚未读取的部分，需要补充后再看。':'我是暖暖。你可以在下方添加看病资料，或先看看已有理赔资料怎么使用。'}</div>${messages.map(m=>`<div class="bubble ${m.me?'me':''}">${!m.me?'<small>问答服务暂不可用</small><br>':''}${escape(m.text)}${m.to?btn(m.label,m.to,'link'):''}</div>`).join('')}</div><div class="chat-dock">${files.length?`<button class="home-material-link" data-go="materials">已选 ${files.length} 份补充资料 · 尚未分析 ${icon('arrow',14)}</button>`:''}<div class="suggestions">${(imported?['费用总额就是自付吗？','复诊要准备什么？']:['我该准备哪些资料？']).map(q=>`<button data-question="${q}">${q}</button>`).join('')}</div><form class="composer" id="chat-form"><button class="attach" type="button" data-action="upload" aria-label="上传看病资料">＋</button><textarea id="question" aria-label="想问暖暖的问题" placeholder="有哪里没看懂，问问暖暖" rows="1">${escape(draft)}</textarea><button type="submit" aria-label="发送">${icon('send',20)}</button></form><p class="notice">问答服务暂不可用 · 所选文件仅保存在当前页面</p></div>`;};
render=function(){
 const id=pageId(); main.classList.toggle('expense-reference',id==='evidence'); main.classList.toggle('is-chat',id==='chat');main.classList.toggle('document-page',['discharge','evidence','test','summary','raw-record','raw-test','raw-treatment','raw-other','raw-cost','claim-record','guide'].includes(id)); main.classList.toggle('onboarding',['welcome','consent','intake'].includes(id));
 details.materials[1]=typeof buildCaseMaterials==='function'?buildCaseMaterials():originalMaterials+`<section class="card"><h2>我补充的资料</h2>${files.length?fileList():'<p>后来拿到的病历、检查报告，也可以放在这里。</p>'}${uploadButton()}<p class="notice">当前仅本地预览，未上传或分析。</p></section>`;
 originalRender();
 if(id==='chat'){main.innerHTML=header('问暖暖')+chat();document.querySelector('.chat-thread').scrollTop=chatScroll;}
 const screens={welcome:['暖愈智护',welcome],consent:['资料怎么使用',consentPage],intake:['这次看病的资料',intake]};
 if(screens[id]){const [title,fn]=screens[id];main.innerHTML=header(title)+`<div class="page">${fn()}</div>`;}
 if(id.startsWith('file-')){const f=files.find(f=>String(f.id)===id.slice(5));main.innerHTML=header('查看补充资料')+`<div class="page"><section class="card">${f?`<h2>${escape(f.name)}</h2><p>仅本地预览，未上传或分析。</p>${f.type.startsWith('image/')?`<img class="local-preview" src="${f.url}" alt="所选测试资料">`:`<a class="outline" href="${f.url}" target="_blank" rel="noopener">打开 PDF 预览</a>`}`:'<p>这份资料已移除，请重新选择。</p>'}</section></div>`;}
 if(id==='home'&&!main.querySelector('.care-home-compact,.replica-home'))main.querySelector('.footnote').insertAdjacentHTML('beforebegin',`<button class="home-material-link" data-go="${imported?'materials':'welcome'}">${imported?'补充看病资料':'第一次来？了解如何使用理赔资料'} ${icon('arrow',15)}</button>`);
 const roots=['home','records','welcome'];
 const contextualChat=id==='chat'&&trail().length>0;
 const backButton=main.querySelector('.topbar [data-action="back"]');
 if(backButton&&((roots.includes(id)&&!trail().length)||(id==='chat'&&!contextualChat))){backButton.replaceWith(Object.assign(document.createElement('span'),{className:'nav-placeholder'}));}
 main.scrollTop=positions[id]||0;renderedPage=id;

};
function send(text){text=text.trim();if(!text)return;messages.push({me:true,text});draft='';let answer;
 if(files.length)answer={text:'你选择的补充资料还没有上传或分析。资料读取服务暂不可用，请稍后再试。',to:'materials',label:'查看已选资料'};
 else if(!imported)answer={text:'可以先使用这次理赔已提交的资料；出院后新拿到的报告、用药单，也可以通过输入框左侧的“＋”补充。',to:'consent',label:'了解已有资料怎么使用'};
 else if(text.includes('自付')||text.includes('费用'))answer={text:'费用单里的 1,200 元是总额。还没有报销信息，不能据此判断最后自付多少。',to:'evidence',label:'查看费用单原文'};
 else if(text.includes('复诊'))answer={text:'出院记录写了 10 月 12 日上午复诊并复查血常规，携带本次就医材料。具体几点、科室和预约方式仍需向医院核对。',to:'appointment',label:'看看复查安排'};
 else answer={text:'问题已保留在当前页面。问答服务暂不可用，请稍后再试。',to:'guide',label:'先看看住院说明'};
 answer.text='问答服务暂不可用，暂时无法回答这条问题。你输入的内容已保留在当前页面。';messages.push({me:false,...answer});chatScroll=1e9;render();
}
function selectFiles(list){saveDraft();let added=0,errors=[];for(const f of list){
 const ext=f.name.split('.').pop().toLowerCase(); const valid=['jpg','jpeg','png','pdf'].includes(ext)&&(!f.type||['image/jpeg','image/png','application/pdf'].includes(f.type));
 if(!valid){errors.push('仅支持 JPG、PNG、PDF');continue;}if(!f.size||f.size>10*1024*1024){errors.push('文件需大于 0 且不超过 10 MB');continue;}
 if(files.some(x=>x.name===f.name&&x.size===f.size&&x.modified===f.lastModified)){errors.push('重复文件未添加');continue;}if(files.length>=20){errors.push('最多添加 20 份');continue;}
 files.push({id:++fileSequence,name:f.name,size:f.size,modified:f.lastModified,type:f.type|| (ext==='pdf'?'application/pdf':`image/${ext==='png'?'png':'jpeg'}`),url:URL.createObjectURL(f)});added++;
 }uploadSheet.close();render();toast([added?`已选择 ${added} 份，仅本地预览`:'',...new Set(errors)].filter(Boolean).join('；'));}
document.addEventListener('click',e=>{const el=e.target.closest('button');if(!el)return;
 if(el.dataset.documentQuestion){saveDraft();const question=el.dataset.documentQuestion;go('chat');draft=question;render();return;}if(el.dataset.go){go(el.dataset.go,{tab:!!el.closest('#nav')});return;}if(el.dataset.question){send(el.dataset.question);return;}
 if(el.dataset.remove){saveDraft();const f=files.find(f=>String(f.id)===el.dataset.remove);if(f)URL.revokeObjectURL(f.url);files=files.filter(f=>f!==f);render();return;}
 switch(el.dataset.action){case'back':back();break;case'upload':saveDraft();uploadSheet.showModal();break;case'close-upload':uploadSheet.close();break;case'camera':document.getElementById('upload-camera').click();break;case'choose-files':document.getElementById('upload-files').click();break;case'accept':if(consent){imported=true;go('intake');}break;
 case'remind':for(const r of dialog.querySelectorAll('input[name=time]'))r.checked=r.value===(reminder||'10 月 11 日 20:00');dialog.showModal();break;case'close-dialog':dialog.close();break;case'cancel-reminder':reminder='';render();break;case'feedback':feedback=document.getElementById('correction').value.trim();toast(feedback?'问题已记在当前页面，尚未提交客服':'请先写下需要核对的内容');break;}
});
document.addEventListener('input',e=>{if(e.target.id==='question')draft=e.target.value;});
document.addEventListener('change',e=>{if(e.target.id==='consent-check'){consent=e.target.checked;document.querySelector('[data-action=accept]').disabled=!consent;}if(e.target.id.startsWith('upload-')&&e.target.files){selectFiles([...e.target.files]);e.target.value='';}if(e.target.id==='scenario'){scenario=e.target.value;go('home');}});
document.addEventListener('submit',e=>{if(e.target.id==='chat-form'){e.preventDefault();send(document.getElementById('question').value);}if(e.target.id==='reminder-form'){e.preventDefault();reminder=new FormData(e.target).get('time');dialog.close();render();toast('时间已记下，尚不能发送通知');}});
addEventListener('popstate',()=>{rememberPosition();dialog.close();uploadSheet.close();render();});
const resize=()=>document.documentElement.style.setProperty('--available-height',`${window.visualViewport?.height||innerHeight}px`);resize();window.visualViewport?.addEventListener('resize',resize);
const initialPage=location.hash.slice(2)||'welcome';
if(history.state?.navKey!==navKey||history.state.page!==initialPage)history.replaceState(navigationState(initialPage,[]),'',`#/${initialPage}`);
render();
