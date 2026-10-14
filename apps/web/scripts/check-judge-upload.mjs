import assert from 'node:assert/strict';
import {build} from 'rolldown';
import {mkdir,rm} from 'node:fs/promises';
import {fileURLToPath,pathToFileURL} from 'node:url';
import path from 'node:path';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';

const rootDir=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const out=path.resolve(rootDir,'.test-judge-upload');assert.ok(out.startsWith(rootDir+path.sep));
await mkdir(out,{recursive:true});
await build({input:path.join(rootDir,'src/ClaimIntake.tsx'),external:id=>/^(react|react-dom)(\/|$)/.test(id),
  transform:{jsx:{runtime:'automatic'},define:{'import.meta.env':'{}'}},
  plugins:[{name:'test-assets',load(id){if(/\.(css|webp)$/.test(id))return {code:'export default "asset";',moduleType:'js'};}}],
  output:{dir:out,format:'esm',entryFileNames:'ClaimIntake.mjs'}});
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost'});
for(const key of ['window','document','HTMLElement'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
dom.window.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
dom.window.HTMLDialogElement.prototype.close=function(){this.open=false;};
const oldCreate=URL.createObjectURL,oldRevoke=URL.revokeObjectURL;
URL.createObjectURL=()=> 'blob:synthetic-preview';URL.revokeObjectURL=()=>{};
const {createRoot}=await import('react-dom/client');
const {default:ClaimIntake}=await import(pathToFileURL(path.join(out,'ClaimIntake.mjs')).href);
const sample={sample_id:'synthetic-01',version:'v1',data_origin:'official_deidentified',title:'合成病例流程测试',summary:'测试',notice:'合成测试，非患者资料',file_count:3,page_count:5,
  claim_info:{kind:'住院医疗',cause:'疾病',diagnosis:'合成肺炎样例',start:'2026-09-20',end:'2026-09-25',total:'1200.00',social:'是',other:'否'},
  documents:[{id:'discharge',name:'合成出院记录.pdf',document_type:'出院记录',page_count:2},{id:'costs',name:'合成费用清单.pdf',document_type:'费用清单',page_count:2},{id:'settlement',name:'合成结算单.pdf',document_type:'医保结算单',page_count:1}]};
const calls=[],opens=[];let uploadCount=0,failSecond=true;
globalThis.fetch=async(url,options={})=>{
  const p=new URL(url,'http://localhost').pathname;
  const body=typeof options.body==='string'?JSON.parse(options.body):options.body;
  calls.push({path:p,method:options.method||'GET',body});
  if(p==='/judge/sample')return options.headers.Authorization.includes('ordinary')?Response.json({}, {status:403}):Response.json(sample);
  if(p.startsWith('/judge/sample/files/'))return new Response('%PDF-1.4\nSynthetic '+p,{headers:{'Content-Type':'application/pdf'}});
  if(p==='/v1/me/consents')return Response.json({status:'active',consent_id:'synthetic-consent'});
  if(p==='/v1/cases')return Response.json({case_id:'synthetic-case'});
  if(p==='/v1/conversations')return Response.json({});
  if(p.endsWith('/documents')){
    uploadCount++;
    if(uploadCount===2&&failSecond){failSecond=false;return Response.json({message:'合成上传中断'},{status:500});}
    return Response.json({document_id:'synthetic-doc-'+uploadCount});
  }
  if(p.endsWith('/analyses'))return Response.json({turn_id:'synthetic-turn'});
  throw Error('Unexpected request '+p);
};
let root=createRoot(document.getElementById('root'));
const flush=()=>act(async()=>{await new Promise(r=>setTimeout(r,15));});
const button=text=>[...document.querySelectorAll('button')].find(node=>node.textContent.replace(/\s*→\s*$/,'').trim()===text||node.getAttribute('aria-label')===text);
async function click(text){const node=button(text);assert.ok(node,'Missing button '+text);assert.equal(node.disabled,false);await act(async()=>node.click());await flush();}
const props={token:'synthetic-judge',subject:'synthetic-subject',visible:true,onAuthorize:()=>{},onExit:()=>{},onOpen:async id=>opens.push(id)};
try{
  await act(async()=>root.render(React.createElement(ClaimIntake,props)));await flush();
  await click('导入示例病例');
  assert.equal(document.querySelectorAll('.claim-file-tile').length,3);
  assert.match(document.body.textContent,/尚未提交/);
  assert.equal(calls.filter(call=>call.method==='POST').length,0,'Sample selection must stay in the browser');
  await click('查看合成出院记录.pdf');assert.ok(document.querySelector('iframe.claim-pdf-preview'));
  await click('关闭图片预览');
  await click('下一步，核对申请');
  assert.equal(button('确认提交材料').disabled,true,'Confirmation is required before real upload');
  await act(async()=>document.querySelector('.claim-consent input').click());
  await click('确认提交材料');assert.match(document.body.textContent,/合成上传中断/);
  await click('重试提交');assert.match(document.body.textContent,/本次提交已完成/);
  assert.equal(uploadCount,4,'Retry must preserve the successfully uploaded first file');
  assert.equal(calls.filter(call=>call.path==='/v1/cases').length,1,'Retry retains one case');
  const created=calls.find(call=>call.path==='/v1/cases').body;
  assert.equal(created.data_origin,'official_deidentified');assert.equal(created.user_context.judge_demo,true);
  const uploads=calls.filter(call=>call.path.endsWith('/documents'));
  assert.deepEqual(uploads.map(call=>call.body.get('file').name),['合成出院记录.pdf','合成费用清单.pdf','合成费用清单.pdf','合成结算单.pdf']);
  assert.equal(calls.filter(call=>call.path.endsWith('/analyses')).length,0,'Successful upload must precede analysis');
  await click('查看相关报告');
  const analysis=calls.find(call=>call.path.endsWith('/analyses'));
  assert.equal(analysis.body.document_ids.length,3);assert.match(analysis.body.message,/不代表账号使用者本人病史/);
  assert.equal(opens.length,1);
  await act(async()=>root.unmount());
  root=createRoot(document.getElementById('root'));
  await act(async()=>root.render(React.createElement(ClaimIntake,{...props,token:'ordinary'})));await flush();
  assert.equal(document.querySelector('.judge-sample-card'),null,'Ordinary users do not receive the judge library');
  console.log('PASS: sample selection has no writes, previews and confirmation, real multipart upload, retry preserves files/case, analysis starts only after report click, account library scope.');
}finally{
  await act(async()=>root.unmount());dom.window.close();URL.createObjectURL=oldCreate;URL.revokeObjectURL=oldRevoke;
  assert.ok(out.startsWith(rootDir+path.sep));await rm(out,{recursive:true,force:true});
}
