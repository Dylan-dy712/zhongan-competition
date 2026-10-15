import assert from 'node:assert/strict';
import {analysisSteps,analysisStageIndex,estimatedStagePercent,smoothPercent} from '../src/analysisProgress.ts';

assert.equal(analysisSteps.length,5);
assert.equal(analysisStageIndex('parse'),0);
for(const stage of ['extract','insights','reconcile']){
 assert.equal(analysisStageIndex(stage),1,'Concurrent extraction/checking belongs to one unfinished step');
}
assert.equal(analysisStageIndex('guidance'),2,'Extraction/checking completes only when guidance starts');
assert.equal(analysisStageIndex('validate'),3);
assert.equal(analysisStageIndex('narrative'),4,'Writing/reviewing prose is still in progress');
assert.equal(analysisStageIndex(undefined),-1);
assert.equal(analysisStageIndex('unknown'),-1,'Missing server state must not claim a stage has started');
for(let stage=0;stage<5;stage++){
 let previous=stage*20;
 for(const seconds of [0,1,5,15,30,60,300,86400]){
  const value=estimatedStagePercent(stage,seconds);
  assert.ok(value>=previous&&value<stage*20+20,'Simulated progress stays monotone inside the real stage');
  previous=value;
 }
 assert.ok(estimatedStagePercent(stage,10)>stage*20,'Time advances the displayed estimate within a stage');
}
assert.equal(estimatedStagePercent(4,86400),99,'Time alone never reaches 100%');
assert.equal(smoothPercent(21,40),22,'A stage transition advances the numeric display one point at a time');
assert.equal(smoothPercent(39,20),39,'A stale update cannot move the estimate backwards');
console.log('PASS: real stage ownership, bounded within-stage estimates, one-point smoothing and no simulated completion.');
