import assert from 'node:assert/strict';
import {analysisSteps,analysisStageIndex} from '../src/analysisProgress.ts';

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
console.log('PASS: server-owned progress stages, grouped concurrent analysis and no invented stage for missing state.');
