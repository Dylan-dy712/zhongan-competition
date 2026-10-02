// Source-level checks; no browser automation or visual/layout assertions.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '../output_dir/product-design');
const listeners = {};
const classes = new Set();
const main = {
  innerHTML: '', scrollTop: 0,
  classList: { toggle(name, on) { on ? classes.add(name) : classes.delete(name); } },
  querySelector() { return { focus() {} }; },
};
const nodes = {main, nav:{style:{}}, reminder:{}, toast:{textContent:''}};
const historyStack = [{state:null, hash:'#/records'}];
const context = vm.createContext({
  document: {
    getElementById(id) { return nodes[id]; },
    addEventListener(name, fn) { (listeners[name] ||= []).push(fn); },
  },
  location:{hash:'#/records'},
  setTimeout, clearTimeout,
});
context.history = {
  state:null,
  pushState(state, _, hash) { this.state=state; context.location.hash=hash; historyStack.push({state,hash}); },
  replaceState(state, _, hash) { this.state=state; context.location.hash=hash; historyStack[historyStack.length-1]={state,hash}; },
  back() { if(historyStack.length>1) historyStack.pop(); const entry=historyStack.at(-1); this.state=entry.state; context.location.hash=entry.hash; },
};
const evaluate = code => vm.runInContext(code, context);
evaluate(fs.readFileSync(path.join(root,'encounter-data.js'),'utf8'));
evaluate(fs.readFileSync(path.join(root,'proposal.js'),'utf8'));
// Exercise the actual navigation implementation without unrelated upload/DOM setup.
evaluate('const parentPage={}; function saveDraft(){}; const uploadSheet={open:false};');
const flow=fs.readFileSync(path.join(root,'proposal-flow.js'),'utf8');
evaluate(flow.slice(flow.indexOf("const navKey="),flow.indexOf('function fileList()')).replace(/const parentPage=.*?;\r?\n/,''));
// The complete flow renderer records the rendered page after restoring its scroll.
evaluate('const testBaseRender=render; render=function(){testBaseRender();renderedPage=pageId();};');
evaluate(fs.readFileSync(path.join(root,'records-page.js'),'utf8'));
const click = dataset => listeners.click.forEach(fn => fn({target:{closest:()=>({dataset})}}));
const html = () => main.innerHTML;
const count = token => html().split(token).length-1;
assert.equal(count('class="records-encounter"'),4);
assert.equal(count('class="records-group"'),3);
assert.match(html(),/性别未填写/);
assert.match(html(),/虚构档案/);

click({recordsFilter:'pneumonia'});
assert.equal(count('class="records-encounter"'),2);
assert.doesNotMatch(html(),/data-go="encounter-fracture-visit"/);
main.scrollTop=156;
evaluate("go('encounter-pneumonia-stay')");
assert.match(html(),/DEMO-002/);
assert.doesNotMatch(html(),/1,200\.00|10 月 12 日|DEMO-001|DEMO-003/);
assert.match(html(),/data-go="encounter-pneumonia-followup"/);
evaluate("go('encounter-pneumonia-followup')");
assert.match(html(),/DEMO-003/);
assert.doesNotMatch(html(),/DEMO-002|data-go="recovery"/);
assert.match(html(),/data-go="chat"/);
assert.match(html(),/data-go="evidence"/);
assert.match(html(),/data-go="materials"/);
evaluate('back(); render();');
assert.match(html(),/DEMO-002/);
evaluate('back(); render();');
assert.equal(count('class="records-encounter"'),2);
assert.equal(main.scrollTop,156);
assert.match(html(),/data-records-filter="pneumonia" aria-pressed="true"/);

click({recordsFilter:'all'});
click({recordsView:'time'});
assert.equal(count('class="records-group"'),0);
const order=[...html().matchAll(/class="records-title-link" data-go="([^"]+)"/g)].map(match=>match[1]);
assert.deepEqual(order,['encounter-current','encounter-pneumonia-followup','encounter-pneumonia-stay','encounter-fracture-visit']);
click({recordsFilter:'fracture'});
assert.equal(count('class="records-encounter"'),1);
evaluate("go('encounter-fracture-visit')");
assert.match(html(),/DEMO-001/);
assert.doesNotMatch(html(),/1,200\.00|data-go="recovery"/);
assert.match(html(),/data-go="chat"/);
evaluate("go('encounter-current')");
assert.match(html(),/1,200\.00/);
assert.match(html(),/data-go="recovery"/);
assert.doesNotMatch(html(),/DEMO-001|DEMO-002|DEMO-003/);
evaluate("go('home', {tab:true})");
assert(!classes.has('records-screen'));
assert(!classes.has('records-detail-screen'));
assert.equal(nodes.nav.style.display,'flex');
assert.match(html(),/小安，你好/);

// Every referenced script/style is present and parseable, including the new module.
const entry=fs.readFileSync(path.join(root,'home-proposal.html'),'utf8');
for(const match of entry.matchAll(/(?:src|href)="([\w-]+\.(js|css))\?/g)) {
  const source=fs.readFileSync(path.join(root,match[1]),'utf8');
  if(match[2]==='js') new vm.Script(source,{filename:match[1]});
}
console.log('PASS: grouping, filters, chronological order, encounter isolation, navigation/scroll restoration, root cleanup and entry references. Visual layout not tested.');
