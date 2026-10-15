import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {loadTestModules} from './test-modules.mjs';

const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});
for(const key of ['window','document','HTMLElement','sessionStorage','localStorage'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const {createRoot}=await import('react-dom/client');
const modules=await loadTestModules();
const root=createRoot(document.getElementById('root'));
const calls=[];
globalThis.fetch=async(url)=>{
  const path=new URL(url,'http://localhost').pathname;calls.push(path);
  if(path==='/v1/conversations')return Response.json([]);
  if(path==='/v1/medical-records')return Response.json({records:[],unorganized_count:0,processing_count:0});
  throw Error('Unexpected request: '+path);
};
try{
  for(const [subject_id,name] of [['a','合成母亲'],['b','合成孩子']]){
    const member={subject_id,name,relationship:'other',gender:'unspecified',birth_date:null};
    await act(async()=>root.render(React.createElement(modules.AccountPage,{token:'synthetic',members:[member],member,
      onSelect:()=>{},onSaved:async()=>{},onRecords:()=>{},onNew:()=>{},onLogout:async()=>{}})));
    await act(async()=>{await new Promise(resolve=>setTimeout(resolve,20));});
    assert.ok(document.body.textContent.includes(name));
    assert.ok(!/关怀记忆|确认保存|管理记忆|记忆来源/.test(document.body.textContent));
  }
  assert.ok(!calls.some(path=>/memor/.test(path)),'Opening/switching account page must not request manual memory settings');
  const chat=await readFile(new URL('../src/App.tsx',import.meta.url),'utf8');
  assert.ok(!/PatientMemory|memoryPanel|选择这条消息作为记忆来源|本对话的关怀记忆/.test(chat));
  console.log('Automatic memory UI: no manual confirmation or memory board; member switching makes no memory-editor requests.');
}finally{
  await act(async()=>root.unmount());await modules.close();
}
