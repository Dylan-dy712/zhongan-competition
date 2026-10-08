import assert from 'node:assert/strict';
import {estimateWithinStage} from '../src/analysisProgress.ts';

for(let index=0;index<5;index++){
 const base=index*20,cap=index===4?99:base+19;
 let previous=base;
 for(const elapsed of [0,1,3,8,15,30,60,120,3600]){
  const value=estimateWithinStage(base,index,elapsed);
  assert.ok(value>=previous && value<=cap,'Estimate is monotonic and cannot complete a stage');previous=value;
 }
 assert.ok(estimateWithinStage(base,index,8)>base+1 && estimateWithinStage(base,index,8)<cap,'Visible intermediate progress is required');
 assert.equal(estimateWithinStage(base,index,3600),cap);
}
assert.equal(estimateWithinStage(0,0,-1),1);
console.log('PASS: intermediate estimated percentages, monotonic bounds, phase caps and 99% completion guard.');
