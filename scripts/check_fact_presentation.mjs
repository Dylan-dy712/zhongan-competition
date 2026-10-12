import assert from 'node:assert/strict';
import {factValueText} from '../apps/web/src/factPresentation.ts';
assert.equal(factValueText({amount_minor:120001,currency:'CNY'}),'1,200.01 元');
assert.equal(factValueText({amount_minor:0,currency:'CNY'}),'0.00 元');
assert.equal(factValueText({drug_name:'合成药名',phase:'inpatient',dose:null}),'药品：合成药名；阶段：住院期间');
assert.equal(factValueText({amount_minor:Number.MAX_SAFE_INTEGER+1,currency:'CNY'}),'金额需核对原文');
assert.equal(factValueText(null),'暂无明确结果');
console.log('PASS: minor-unit money formatting, missing values and medication phase preserved.');
