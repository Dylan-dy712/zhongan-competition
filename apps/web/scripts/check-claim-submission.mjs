import assert from 'node:assert/strict';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {JSDOM} from 'jsdom';
import {build} from 'rolldown';
import {mkdir,rm} from 'node:fs/promises';
import {fileURLToPath,pathToFileURL} from 'node:url';
import path from 'node:path';

const app=fileURLToPath(new URL('..',import.meta.url));
const out=path.join(app,'.claim-test');await mkdir(out,{recursive:true});
await build({input:path.join(app,'src/ClaimIntake.tsx'),external:id=>/^(react|react-dom)(\/|$)/.test(id),
  transform:{jsx:{runtime:'automatic'},define:{'import.meta.env':'{}'}},
  plugins:[{name:'test-assets',load(id){if(/\.(css|webp)$/.test(id))return {code:'export default "asset";',moduleType:'js'};}}],
  output:{dir:out,format:'esm',entryFileNames:'ClaimIntake.mjs'}});
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost'});
for(const key of ['window','document','HTMLElement'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
dom.window.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
dom.window.HTMLDialogElement.prototype.close=function(){this.open=false;};
const calls=[],opens=[],dirty=[];
let uploadFailure=true,analysisFailure=true,supplementFailure=true,resolveAnalysis;
globalThis.fetch=async(url,options)=>{
  const p=new URL(url,'http://localhost').pathname;
  calls.push({path:p,body:options.body});
  if(p==='/v1/me/consents')return Response.json({status:'active',version:3,consent_id:'synthetic-consent'});
  if(p==='/v1/conversations')return Response.json({});
  if(p.endsWith('/documents')){
    if(uploadFailure){uploadFailure=false;return Response.json({message:'合成上传失败'},{status:500});}
    if(options.body.get('file').name==='补充复查.pdf'&&supplementFailure){supplementFailure=false;return Response.json({message:'补充上传中断'},{status:500});}
    return Response.json({document_id:'doc-'+calls.length});
  }
  if(p.endsWith('/analyses')){
    if(analysisFailure){analysisFailure=false;return Response.json({message:'合成分析失败'},{status:500});}
    await new Promise(r=>{resolveAnalysis=r;});return Response.json({turn_id:'turn'});
  }
  throw new Error('Unexpected request '+p);
};
const {default:ClaimIntake}=await import(pathToFileURL(path.join(out,'ClaimIntake.mjs')).href);
const root=createRoot(document.getElementById('root'));
let visible=true;
let exits=0;
const props={token:'synthetic-only',subject:'subject',onOpen:async id=>opens.push(id),onExit:()=>exits++,onAuthorize:()=>{},onDirty:value=>dirty.push(value)};
const render=()=>act(async()=>root.render(React.createElement(ClaimIntake,{...props,visible})));
const click=async text=>{
  const button=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===text||b.getAttribute('aria-label')===text);
  assert.ok(button,`Missing ${text}`);assert.equal(button.disabled,false);
  await act(async()=>button.click());
};
const analysisCalls=()=>calls.filter(c=>c.path.endsWith('/analyses'));
const consentCalls=()=>calls.filter(c=>c.path==='/v1/me/consents');
const addFiles=async names=>{
  const picker=document.querySelector('input[type=file]');
  Object.defineProperty(picker,'files',{configurable:true,value:names.map(name=>new File(['synthetic fixture'],name,{type:'application/pdf'}))});
  await act(async()=>picker.dispatchEvent(new window.Event('change',{bubbles:true})));
  document.querySelector('.claim-upload-dialog').close();
};
const agree=()=>act(async()=>document.querySelector('.care-agreement input').click());
async function prepare(){
  await click('填入示例信息');await click('下一步，上传材料');
  for(const category of ['record','invoice']){
    const button=document.querySelector(`[data-claim-action="pick-${category}"]`);assert.ok(button);
    await act(async()=>button.click());
    const picker=document.querySelector('input[type=file]');
    Object.defineProperty(picker,'files',{configurable:true,value:[new File(['synthetic fixture'],'fixture.pdf',{type:'application/pdf'})]});
    await act(async()=>picker.dispatchEvent(new window.Event('change',{bubbles:true})));
    document.querySelector('.claim-upload-dialog').close();
  }
  await click('下一步，核对申请');
  await act(async()=>document.querySelector('.claim-consent input').click());
}
try{
  await render();await prepare();
  visible=false;await render();visible=true;await render();
  assert.match(document.querySelector('.claim-main').textContent,/确认理赔申请/,'Unfinished draft survives navigation');
  await click('确认提交材料');assert.match(document.body.textContent,/合成上传失败/);
  assert.equal(analysisCalls().length,0);await click('重试提交');
  assert.match(document.querySelector('.claim-main').textContent,/本次提交已完成/);
  assert.equal(document.querySelector('.analysis-dialog').open,false);
  assert.equal(analysisCalls().length,0,'Submitting must never start analysis');assert.deepEqual(opens,[]);
  assert.equal(dirty.at(-1),false,'Submitted form must not remain dirty');
  await click('返回首页');assert.equal(exits,1,'Success footer returns home');
  await click('查看就医关怀');
  assert.match(document.querySelector('.care-preparation h1').textContent,/这 2 份，不用再传了/);
  assert.equal(document.querySelectorAll('[aria-label="已上传材料"] li').length,2);
  assert.equal(analysisCalls().length,0);assert.equal(consentCalls().length,0);
  visible=false;await render();visible=true;await render();
  assert.ok(document.querySelector('.care-preparation'),'Preparation survives leaving and reentering before consent');
  await click('带着这些资料问暖暖');
  assert.equal(document.querySelector('.care-primary').disabled,true,'Separate informed consent is mandatory');
  assert.equal(analysisCalls().length,0);assert.equal(consentCalls().length,0);
  assert.match(document.querySelector('.care-privacy-card').textContent,/火山引擎.*百度千帆/);
  await agree();await click('确认提交，开始解读');assert.match(document.body.textContent,/合成分析失败/);
  const authorization=consentCalls().find(call=>call.body);assert.equal(JSON.parse(authorization.body).confirmation,true);
  assert.equal(analysisCalls().length,1);assert.deepEqual(opens,[]);
  await act(async()=>document.querySelector('.analysis-primary').click());
  await act(async()=>document.querySelector('[data-go]').click());
  assert.equal(analysisCalls().length,2,'Double click must not duplicate analysis');
  assert.deepEqual(JSON.parse(analysisCalls()[0].body),JSON.parse(analysisCalls()[1].body),'Retry reuses request and documents');
  await act(async()=>resolveAnalysis());assert.equal(opens.length,1);
  await click('返回资料清单');assert.equal(document.querySelector('.care-outline').disabled,true,'An ambiguous analysis failure freezes the request document set');
  await click('返回提交结果');await click('查看就医关怀');assert.equal(analysisCalls().length,2,'Opening saved analysis must not submit again');
  visible=false;await render();visible=true;await render();
  assert.ok(document.querySelector('.claim-form-shell'));assert.equal(document.querySelector('.claim-result-shell'),null);
  assert.equal(document.querySelector('[data-claim-field=diagnosis]').value,'');
  await prepare();await click('确认提交材料');assert.equal(analysisCalls().length,2);
  const conversations=calls.filter(c=>c.path==='/v1/conversations').map(c=>JSON.parse(c.body).conversation_id);
  assert.equal(conversations[0],conversations[1],'Upload retry retains conversation');
  assert.notEqual(conversations[1],conversations[2],'New submission uses a new conversation');
  await act(async()=>document.querySelector('[data-go]').click());assert.equal(analysisCalls().length,2,'Success card opens materials before analysis');
  await click('＋ 补充看病资料');await addFiles(['可移除.pdf']);
  assert.equal(document.querySelectorAll('[aria-label="补充材料"] li').length,1);
  await click('移除可移除.pdf');assert.equal(document.querySelector('[aria-label="补充材料"]'),null);
  await click('＋ 补充看病资料');await addFiles(['补充用药.pdf','补充复查.pdf']);
  assert.equal(calls.filter(c=>c.path.endsWith('/documents')).length,5,'Supplement selection stays local until final consent');
  await click('带着这些资料问暖暖');assert.equal(document.querySelector('.care-primary').disabled,true);
  await agree();await click('确认提交，开始解读');assert.match(document.body.textContent,/补充上传中断/);
  assert.equal(analysisCalls().length,2,'An incomplete supplementary upload cannot start analysis');
  await click('关闭分析进度');await click('返回资料清单');
  assert.equal(document.querySelector('[aria-label="移除补充用药.pdf"]'),null,'A successfully uploaded supplement cannot be silently excluded');
  await click('带着这些资料问暖暖');await click('确认提交，开始解读');
  assert.equal(analysisCalls().length,3);
  assert.equal(JSON.parse(analysisCalls()[2].body).document_ids.length,4,'Original and supplementary documents share the same analysis');
  assert.equal(calls.filter(c=>c.path.endsWith('/documents')&&c.body.get('file').name==='补充用药.pdf').length,1,'Retry skips uploaded supplementary documents');
  await act(async()=>resolveAnalysis());
  console.log('PASS: uploaded material list, optional supplements/removal, separate consent before analysis, consent recording, home button, supplementary upload retry, request locking and idempotent analysis retry, draft retention and completed form reset.');
}finally{await act(async()=>root.unmount());dom.window.close();await rm(out,{recursive:true,force:true});}
