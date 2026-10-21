import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {loadTestModules} from './test-modules.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#/chat'});
for(const key of ['window','document','sessionStorage','localStorage','HTMLElement'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
dom.window.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
dom.window.HTMLDialogElement.prototype.close=function(){this.open=false;};
const originalNow=Date.now,originalInterval=globalThis.setInterval,originalClear=globalThis.clearInterval;
let now=1000;Date.now=()=>now;
const timers=new Map();let timerId=0;
globalThis.setInterval=fn=>{timers.set(++timerId,fn);return timerId;};globalThis.clearInterval=id=>timers.delete(id);
const modules=await loadTestModules(),root=createRoot(document.getElementById('root'));
let snapshot={conversation:{conversation_id:'synthetic-conversation'},turns:[],analysis:{run_id:'demo-run',status:'queued'},report:{status:'not_released'}};
const render=async(open=true)=>act(async()=>root.render(React.createElement(modules.AnalysisFlow,{open,snapshot,onClose(){},onReport(){},onRetry(){}})));
try{
 await render();
 now=2000;snapshot={...snapshot,analysis:{...snapshot.analysis,status:'waiting_review',stage_results:{performance:{judge_experience:{mode:'prepared_sample',duration_ms:8000}}}},
  turns:[{input_kind:'analysis_ready',status:'completed',answer:{text:'合成示例报告。',analysis_run_id:'demo-run'}}]};
 await render();
 assert.match(document.querySelector('.analysis-eyebrow').textContent,/评委体验.*示例报告/);
 assert.match(document.querySelector('.analysis-percent').textContent,/演示进度/);
 assert.ok(document.querySelector('progress').value>0&&document.querySelector('progress').value<100);
 now=6000;await act(async()=>{for(const fn of [...timers.values()])fn();});
 assert.ok(document.querySelector('progress').value>=60&&document.querySelector('progress').value<100);
 now=9100;await act(async()=>{for(const fn of [...timers.values()])fn();});
 assert.equal(document.querySelector('progress').value,100);
 assert.match(document.querySelector('h2').textContent,/解读已准备好/);
 await render(false);await render(true);
 assert.equal(document.querySelector('progress').value,100,'Reopening the same report must not replay the demo');
 snapshot={...snapshot,turns:[],analysis:{run_id:'ordinary-run',status:'running',stage:'parse'}};await render();
 assert.doesNotMatch(document.querySelector('.analysis-eyebrow').textContent,/示例报告/);
 assert.doesNotMatch(document.querySelector('.analysis-percent').textContent,/演示进度/);
 console.log('PASS: explicit sample experience, eight-second progress, completed report access, no replay and ordinary flow isolation. Synthetic only.');
}finally{await act(async()=>root.unmount());await modules.close();Date.now=originalNow;globalThis.setInterval=originalInterval;globalThis.clearInterval=originalClear;dom.window.close();}
