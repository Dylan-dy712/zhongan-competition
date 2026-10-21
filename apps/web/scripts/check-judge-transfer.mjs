import assert from 'node:assert/strict';
import {loadTestModules} from './test-modules.mjs';
const modules=await loadTestModules();
const sample={sample_id:'synthetic-thirteen',version:'images-v1',documents:Array.from({length:13},(_,i)=>({id:String(i),name:`合成第${i+1}页.jpg`,sha256:'synthetic-'+i,media_type:'image/jpeg',document_type:i<8?'出院记录':'费用清单'}))};
const calls=new Map();let active=0,maximum=0,failLast=true,attachments=0;
globalThis.fetch=async(url,options)=>{
  const parsed=new URL(url,'http://localhost');
  if(parsed.pathname.endsWith('/sample-documents')){
    attachments++;assert.equal(typeof options.body,'string');
    assert.equal(JSON.parse(options.body).sample_document_id,'12');
    if(attachments===1)throw new TypeError('Synthetic connection lost after committing');
    return Response.json({document_id:'same-synthetic-document'});
  }
  assert.equal(parsed.searchParams.get('preview'),'true','Preparation requests only small previews');
  const id=parsed.pathname.split('/').at(-1);calls.set(id,(calls.get(id)||0)+1);
  return {ok:true,headers:new Headers({'Content-Type':'image/jpeg'}),arrayBuffer:async()=>{
    active++;maximum=Math.max(maximum,active);
    try{
      await new Promise(resolve=>setTimeout(resolve,3));
      if(id==='12'&&failLast)throw new DOMException('Synthetic last-file body interruption','AbortError');
      return new Uint8Array([255,216,255,224,0,255,217]).buffer;
    }finally{active--;}
  }};
};
try{
  await assert.rejects(modules.api.chooseJudgeSampleFiles('synthetic-token',sample),/已完成的资料会保留/);
  assert.ok(maximum<=3,'Preparation bounds simultaneous response bodies');
  assert.equal(calls.get('12'),3,'The interrupted last response body gets two automatic retries');
  failLast=false;const progress=[];
  const files=await modules.api.chooseJudgeSampleFiles('synthetic-token',sample,n=>progress.push(n));
  assert.equal(files.length,13);assert.deepEqual(files.map(f=>f.documentId),sample.documents.map(d=>d.id));
  assert.ok([...calls].filter(([id])=>id!=='12').every(([,n])=>n===1),'Completed previews must not redownload after a group retry');
  assert.equal(calls.get('12'),4);assert.equal(progress.at(-1),13);
  const attached=await modules.api.attachJudgeSampleDocument('synthetic-token','synthetic-conversation',sample,'12');
  assert.equal(attached.document_id,'same-synthetic-document');assert.equal(attachments,2);
  console.log('PASS: thirteen previews, concurrency bound, last response interruption, automatic retries, completed-file reuse, ordered completion and idempotent metadata-only submission. Synthetic only.');
}finally{await modules.close();}
