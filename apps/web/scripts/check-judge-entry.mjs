import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {webcrypto} from 'node:crypto';
import vm from 'node:vm';

const code=await readFile(new URL('../../../services/judge_demo/entry.js',import.meta.url),'utf8');
const secret='synthetic-invitation-'+ 'a'.repeat(40);
const storage=()=>{const data=new Map();return {getItem:key=>data.get(key)??null,setItem:(key,value)=>data.set(key,String(value)),removeItem:key=>data.delete(key)};};
async function launch({local=storage(),session=storage(),hash='#'+secret,statusCode=200,networkError=false}={}){
  const nodes={status:{textContent:'',setAttribute(){}},retry:{hidden:true,disabled:false,addEventListener(_event,handler){this.click=handler;}}};
  const calls=[],navigation=[];
  const location={hash,pathname:'/judge/',replace:url=>navigation.push(url)};
  const context={document:{getElementById:id=>nodes[id]},location,localStorage:local,sessionStorage:session,
    history:{replaceState(){location.hash='';}},crypto:webcrypto,AbortController,setTimeout,clearTimeout,
    fetch:async(url,options)=>{calls.push({url,options});if(networkError)throw new Error('synthetic outage');
      return {ok:statusCode===200,status:statusCode,json:async()=>statusCode===200
        ?{access_token:'synthetic-token',user:{display_name:'评委体验 01'}}:{detail:statusCode===409?'50 个体验账号已全部分配':'体验链接无效'}};}};
  vm.runInNewContext(code,context);
  await new Promise(setImmediate);
  return {nodes,calls,navigation,local,session,location};
}
const first=await launch();
assert.deepEqual(first.navigation,['/#/home']);
assert.equal(first.location.hash,'');
assert.equal(first.session.getItem('zhongan_chat_token'),'synthetic-token');
assert.equal(first.session.getItem('zhongan_account_name'),'评委体验 01');
const visitor=JSON.parse(first.calls[0].options.body).visitor_id;
assert.match(visitor,/^[0-9a-f]{64}$/);
assert.equal(first.calls[0].options.headers.Authorization,'Demo '+secret);
const again=await launch({local:first.local});
assert.equal(JSON.parse(again.calls[0].options.body).visitor_id,visitor,'Repeat scans retain one account');
const other=await launch();
assert.notEqual(JSON.parse(other.calls[0].options.body).visitor_id,visitor,'Separate browsers receive separate visitor identities');
const missing=await launch({hash:''});
assert.equal(missing.calls.length,0);
assert.equal(missing.nodes.retry.hidden,true);
const full=await launch({statusCode:409});
assert.equal(full.navigation.length,0);
assert.match(full.nodes.status.textContent,/50/);
assert.equal(full.nodes.retry.hidden,true);
const outage=await launch({networkError:true});
assert.equal(outage.nodes.retry.hidden,false);
await outage.nodes.retry.click();
assert.equal(JSON.parse(outage.calls[1].options.body).visitor_id,JSON.parse(outage.calls[0].options.body).visitor_id,'Retry reuses the allocation identity');
const unavailable=await launch({local:{getItem(){throw new Error('storage denied');}}});
assert.equal(unavailable.calls.length,0,'Blocked storage must never consume an account');
console.log('PASS: automatic session handoff, distinct browsers, repeat scans, hidden invitation, capacity, same-identity retry, blocked storage.');
