import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';
import {loadTestModules} from './test-modules.mjs';

const dom=new JSDOM('<button id="trigger">引用</button><div id="root"></div>',{url:'http://localhost/'});
for(const key of ['window','document','HTMLElement'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
dom.window.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
dom.window.HTMLDialogElement.prototype.close=function(){this.open=false;};
const created=[],revoked=[],requests=[];
const originalCreate=URL.createObjectURL,originalRevoke=URL.revokeObjectURL;
URL.createObjectURL=blob=>{const url='blob:synthetic-'+created.length;created.push({url,blob});return url;};
URL.revokeObjectURL=url=>revoked.push(url);
const {default:React,act}=await import('react');
const {createRoot}=await import('react-dom/client');
const modules=await loadTestModules();
const evidence={evidence_id:'synthetic-pdf-evidence',case_id:'synthetic-case',document_id:'synthetic-document',
  document_version:2,page_index:1,source_name:'合成病历.pdf',document_type:'复查记录',media_type:'application/pdf',
  text_span:{text:'合成原文：两周后复查。'},bbox:null};
const root=createRoot(document.getElementById('root'));
const flush=()=>act(async()=>{await new Promise(resolve=>setTimeout(resolve,15));});
const render=async item=>{await act(async()=>root.render(React.createElement(modules.EvidencePanel,{evidence:item,token:'synthetic-token',onClose(){}})));await flush();};
let respond=()=>new Response(new Blob(['synthetic-page'],{type:'image/png'}),{
  headers:{'Content-Type':'image/png','X-Evidence-Regions':JSON.stringify([[.1,.2,.7,.25],[.1,.3,.6,.35]])}});
globalThis.fetch=async(url,options)=>{requests.push({url,options});return respond();};
try{
  await render(evidence);
  assert.equal(requests[0].url,'/v1/evidence/synthetic-pdf-evidence/page-image');
  assert.equal(requests[0].options.headers.Authorization,'Bearer synthetic-token');
  assert.equal(document.querySelector('.source-image img').alt,'PDF 第 2 页原文预览');
  assert.equal(document.querySelectorAll('[aria-label="原文所在区域"]').length,2);
  assert.equal(document.querySelector('[aria-label="原文所在区域"]').style.top,'20%');
  assert.match(document.querySelector('blockquote').textContent,/两周后复查/);
  assert.match(document.body.textContent,/第 2 页/);

  respond=()=>new Response('synthetic-photo',{headers:{'X-Evidence-Regions':'[[0.2,0.4,0.8,0.6]]'}});
  await render({...evidence,evidence_id:'synthetic-photo',media_type:'image/jpeg',bbox:null});
  assert.equal(requests.at(-1).url,'/v1/evidence/synthetic-photo/page-image');
  assert.equal(document.querySelectorAll('[aria-label="原文所在区域"]').length,1);
  assert.equal(document.querySelector('[aria-label="原文所在区域"]').style.top,'40%');
  assert.ok(revoked.includes(created[0].url),'Replacing evidence releases the old page image');

  respond=()=>new Response('page',{headers:{'X-Evidence-Regions':'[[0.1,0.2,0.6,0.3],[-1,0,1,1],[0,0,2,1],[0.7,0.7,0.2,0.2]]'}});
  await render({...evidence,evidence_id:'synthetic-invalid-boxes'});
  assert.equal(document.querySelectorAll('[aria-label="原文所在区域"]').length,1,'Invalid boxes cannot render outside the page');

  respond=()=>new Response('page',{headers:{'X-Evidence-Regions':'[]'}});
  await render({...evidence,evidence_id:'synthetic-no-match'});
  assert.ok(document.querySelector('.source-image img'));
  assert.equal(document.querySelectorAll('[aria-label="原文所在区域"]').length,0);
  assert.match(document.body.textContent,/暂未定位到准确区域/);

  respond=()=>new Response('unavailable',{status:404});
  await render({...evidence,evidence_id:'synthetic-error'});
  assert.equal(document.querySelector('.source-image img'),null);
  assert.match(document.body.textContent,/页面预览暂不可用/);
  assert.match(document.querySelector('blockquote').textContent,/两周后复查/);

  let release;
  respond=()=>new Promise(resolve=>{release=resolve;});
  await render({...evidence,evidence_id:'synthetic-slow'});
  assert.match(document.body.textContent,/正在加载 PDF 对应页/);
  respond=()=>new Response('new-page',{headers:{'X-Evidence-Regions':'[]'}});
  await render({...evidence,evidence_id:'synthetic-new'});
  const current=document.querySelector('.source-image img').src;
  await act(async()=>release(new Response('old-page')));await flush();
  assert.equal(document.querySelector('.source-image img').src,current,'Late old requests cannot overwrite the current citation');
  assert.ok(revoked.includes(created.at(-1).url),'Late page URLs are released');
  console.log('PASS: PDF page image, authenticated request, page index, multiple highlight regions, image compatibility, no-match/error fallback, invalid box filtering, stale request isolation and object URL cleanup. Synthetic fixtures only.');
}finally{
  await act(async()=>root.unmount());await modules.close();dom.window.close();
  URL.createObjectURL=originalCreate;URL.revokeObjectURL=originalRevoke;
}
