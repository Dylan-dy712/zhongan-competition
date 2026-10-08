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
let uploadFailure=true,analysisFailure=true,resolveAnalysis;
globalThis.fetch=async(url,options)=>{
  const p=new URL(url,'http://localhost').pathname;
  calls.push({path:p,body:options.body});
  if(p==='/v1/conversations')return Response.json({});
  if(p.endsWith('/documents')){
    if(uploadFailure){uploadFailure=false;return Response.json({message:'合成上传失败'},{status:500});}
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
const props={token:'synthetic-only',subject:'subject',onOpen:async id=>opens.push(id),onExit:()=>{},onAuthorize:()=>{},onDirty:value=>dirty.push(value)};
const render=()=>act(async()=>root.render(React.createElement(ClaimIntake,{...props,visible})));
const click=async text=>{
  const button=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===text);
  assert.ok(button,`Missing ${text}`);assert.equal(button.disabled,false);
  await act(async()=>button.click());
};
const analysisCalls=()=>calls.filter(c=>c.path.endsWith('/analyses'));
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
  await click('查看相关报告');assert.match(document.body.textContent,/合成分析失败/);
  assert.equal(analysisCalls().length,1);assert.deepEqual(opens,[]);
  await act(async()=>document.querySelector('.analysis-primary').click());
  await act(async()=>document.querySelector('[data-go]').click());
  assert.equal(analysisCalls().length,2,'Double click must not duplicate analysis');
  assert.deepEqual(JSON.parse(analysisCalls()[0].body),JSON.parse(analysisCalls()[1].body),'Retry reuses request and documents');
  await act(async()=>resolveAnalysis());assert.equal(opens.length,1);
  await click('查看相关报告');assert.equal(analysisCalls().length,2,'Opening saved analysis must not submit again');
  visible=false;await render();visible=true;await render();
  assert.ok(document.querySelector('.claim-form-shell'));assert.equal(document.querySelector('.claim-result-shell'),null);
  assert.equal(document.querySelector('[data-claim-field=diagnosis]').value,'');
  await prepare();await click('确认提交材料');assert.equal(analysisCalls().length,2);
  const conversations=calls.filter(c=>c.path==='/v1/conversations').map(c=>JSON.parse(c.body).conversation_id);
  assert.equal(conversations[0],conversations[1],'Upload retry retains conversation');
  assert.notEqual(conversations[1],conversations[2],'New submission uses a new conversation');
  await act(async()=>document.querySelector('[data-go]').click());assert.equal(analysisCalls().length,3,'Success card also starts analysis');
  await act(async()=>resolveAnalysis());
  console.log('PASS: upload retry, success before analysis, explicit report click, idempotent retry/double click, draft retention, completed form reset, distinct new submission, report card.');
}finally{await act(async()=>root.unmount());dom.window.close();await rm(out,{recursive:true,force:true});}
