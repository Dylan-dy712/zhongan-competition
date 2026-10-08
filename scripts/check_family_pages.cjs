// Actual Chromium layout and interaction checks using synthetic HTTP fixtures.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const root=path.resolve(__dirname,'..'),dist=path.join(root,'apps/web/dist'),out=path.join(root,'output_dir/family-members');
const ids={self:'10000000-0000-4000-8000-000000000001',parent:'10000000-0000-4000-8000-000000000002',child:'10000000-0000-4000-8000-000000000003'};
let members=[{subject_id:ids.self,name:'测试本人',relationship:'self',gender:'female',birth_date:'1990-05-10',profile_completed:true},
  {subject_id:ids.parent,name:'测试父亲',relationship:'parent',gender:'male',birth_date:'1960-03-02',profile_completed:true},
  {subject_id:ids.child,name:'测试孩子',relationship:'child',gender:'unspecified',birth_date:null,profile_completed:true}];
const record=(id,subject,caseId,title,date)=>({conversation_id:id,subject_id:subject,case_id:caseId,title,updated_at:date,created_at:date,recall_enabled:false});
let records=[record('self-latest',ids.self,'self-case','本人最近资料','2026-10-02T08:00:00Z'),record('self-earlier-turn',ids.self,'self-case','本人前一段对话','2026-10-01T08:00:00Z'),record('self-old',ids.self,'self-old-case','本人较早资料','2026-09-01T08:00:00Z'),record('parent-latest',ids.parent,'parent-case','父亲最近资料','2026-10-01T08:00:00Z')];
const consent=new Map([[ids.self,{status:'active',version:1}],[ids.parent,{status:'active',version:1}],[ids.child,{status:'not_granted',version:0}]]);
const errors=[],calls=[];let delayParent=false,releaseParent;
(async()=>{
  fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true,executablePath:path.join(process.env.USERPROFILE,'AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe')});
  try {
    const page=await browser.newPage();page.on('pageerror',e=>errors.push(e.message));
    await page.route('http://127.0.0.1:5188/**',async route=>{
      const url=new URL(route.request().url()),pathname=url.pathname,body=route.request().postDataJSON();calls.push({path:pathname,query:url.search,body});
      let data;
      if(pathname==='/v1/me/members'){
        if(body){const value={...body,subject_id:'10000000-0000-4000-8000-000000000004',profile_completed:true};members.push(value);consent.set(value.subject_id,{status:'not_granted',version:0});data=value;}else data=members;
      }else if(pathname.startsWith('/v1/me/members/')){const id=pathname.split('/').pop();members=members.map(member=>member.subject_id===id?{...member,...body}:member);data=members.find(member=>member.subject_id===id);
      }else if(pathname==='/v1/me/consents'){
        const id=url.searchParams.get('subject_id')||ids.self;
        if(body)consent.set(id,{status:body.confirmation?'active':'revoked',version:consent.get(id).version+1});
        data={subject_id:id,...consent.get(id),notice_version:'account-care-v1',purpose:'case_guidance'};
      }else if(pathname==='/v1/chat/subjects')data=members.filter(member=>consent.get(member.subject_id)?.status==='active').map(member=>({subject_id:member.subject_id,consent_id:'synthetic-consent'}));
      else if(pathname==='/v1/conversations'){
        const id=url.searchParams.get('subject_id');
        if(body){data=record(body.conversation_id,body.subject_id,'new-case','新的关怀对话','2026-10-03T00:00:00Z');records.push(data);}
        else {data=records.filter(item=>(!id||item.subject_id===id)&&consent.get(item.subject_id)?.status==='active');
          if(id===ids.parent&&delayParent){delayParent=false;await new Promise(resolve=>releaseParent=resolve);}}
      }else if(pathname.startsWith('/v1/conversations/'))data={conversation:records.find(item=>item.conversation_id===pathname.split('/')[3]),turns:[],analysis:{status:'not_started'},report:{status:'not_generated'}};
      else if(pathname.endsWith('/deliveries'))data=[];
      else if(pathname==='/v1/auth/logout'){await route.fulfill({status:204});return;}
      if(data!==undefined){await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});return;}
      const target=path.resolve(dist,'.'+(pathname==='/'?'/index.html':pathname));
      if(!target.startsWith(dist+path.sep)||!fs.existsSync(target)){await route.abort();return;}
      await route.fulfill({status:200,contentType:{'.html':'text/html','.js':'text/javascript','.css':'text/css','.webp':'image/webp'}[path.extname(target)]||'application/octet-stream',body:fs.readFileSync(target)});
    });
    await page.addInitScript(()=>{sessionStorage.setItem('zhongan_chat_token','synthetic-session');sessionStorage.setItem('zhongan_account_name','测试账号');});
    const button=name=>page.getByRole('button',{name,exact:true});
    async function select(name){await button('切换人员').click();await page.getByRole('dialog').getByRole('button').filter({hasText:name}).click();}
    async function noOverflow(){assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Viewport must not overflow');}
    for(const width of [320,390,1024]){
      await page.setViewportSize({width,height:900});await page.goto('http://127.0.0.1:5188/#/home');await page.locator('.replica-home').waitFor();
      const home=await page.locator('.replica-home').innerHTML();await button('我的').click();await page.getByText('本人最近资料',{exact:true}).waitFor();
      assert.equal(await page.locator('.care-navigation button').count(),3);assert.equal(await page.getByText('本人较早资料',{exact:true}).count(),0);
      assert.match(await page.locator('.demo-account').innerText(),/已保存 2 段对话/);
      await noOverflow();await page.screenshot({path:path.join(out,`my-${width}.png`),fullPage:true});
      await button('切换人员').click();assert.ok(await page.getByRole('dialog').evaluate(dialog=>dialog.contains(document.activeElement)),'Dialog receives keyboard focus');
      await page.keyboard.press('Escape');assert.equal(await page.getByRole('dialog').count(),0);assert.equal(await button('切换人员').evaluate(node=>node===document.activeElement),true);
      await select('测试父亲');await page.getByText('父亲最近资料',{exact:true}).waitFor();assert.equal(await page.getByText('本人最近资料',{exact:true}).count(),0);
      await button('首页').click();assert.equal(await page.locator('.replica-home').innerHTML(),home,'Viewing a family member must not change home');
      await button('我的').click();await page.getByText('父亲最近资料',{exact:true}).waitFor();
      await button('查看详情').click();await page.locator('.records-detail').waitFor();assert.match(await page.locator('.records-detail').innerText(),/测试父亲/);
      await button('‹ 返回就医记录').click();await page.locator('.member-records-header').waitFor();assert.equal(await page.locator('.records-profile').count(),0);await noOverflow();
      await page.screenshot({path:path.join(out,`records-${width}.png`),fullPage:true});await button('‹ 返回我的').click();
      await select('测试孩子');await page.getByText('还没有就医记录',{exact:true}).waitFor();
      await page.screenshot({path:path.join(out,`empty-${width}.png`),fullPage:true});
      assert.equal(await button('确认并授权关怀').count(),1);await select('测试本人');
    }
    await page.setViewportSize({width:390,height:900});
    // A delayed old-person response must not overwrite the current profile/records.
    delayParent=true;await select('测试父亲');await page.getByText(/正在加载 测试父亲/).waitFor();await select('测试本人');await page.getByText('本人最近资料',{exact:true}).waitFor();
    releaseParent();await page.waitForTimeout(100);assert.equal(await page.getByText('父亲最近资料',{exact:true}).count(),0);
    await select('测试孩子');await button('确认并授权关怀').click();await page.getByText(/状态：已授权/).waitFor();
    await button('首页').click();await button('整理理赔资料，开启专属关怀').click();await page.getByRole('dialog',{name:'选择就医资料所属人员'}).waitFor();
    await page.getByRole('dialog').getByRole('button').filter({hasText:'测试父亲'}).click();assert.match(await page.locator('.member-business-bar').innerText(),/测试父亲/);
    await page.locator('[data-claim-field="diagnosis"]').fill('保留父亲草稿');await button('返回首页').click();await button('我的').click();await select('测试本人');
    await button('首页').click();await button('整理理赔资料，开启专属关怀').click();await page.getByRole('dialog').getByRole('button').filter({hasText:'测试父亲'}).click();
    assert.equal(await page.locator('[data-claim-field="diagnosis"]').inputValue(),'保留父亲草稿','My selection must not reset a business draft');
    await button('返回首页').click();await button('问暖暖').click();await button('历史对话').click();await button('＋ 新的关怀对话').click();
    await page.getByRole('dialog').getByRole('button').filter({hasText:'测试父亲'}).click();await button('开始新的对话').click();await page.locator('.composer').waitFor();
    assert.equal(calls.filter(call=>call.path==='/v1/conversations'&&call.body).at(-1).body.subject_id,ids.parent);
    assert.match(await page.locator('.member-identity').innerText(),/测试父亲/);
    await button('我的').click();await select('测试孩子');await button('问暖暖').click();assert.match(await page.locator('.member-identity').innerText(),/测试父亲/,'Existing conversation ownership is fixed');
    await button('我的').click();await button('添加家人').click();await page.getByLabel('姓名',{exact:true}).fill('测试配偶');await page.getByLabel('与本人关系').selectOption('spouse');await button('保存资料').click();await page.getByRole('heading',{name:'测试配偶 配偶'}).waitFor();
    await page.getByText(/状态：尚未授权/).waitFor();await button('编辑资料').click();await page.getByLabel('姓名',{exact:true}).fill('测试配偶更新');await button('保存资料').click();await page.getByRole('heading',{name:'测试配偶更新 配偶'}).waitFor();
    await page.reload();await page.getByRole('heading',{name:'测试配偶更新 配偶'}).waitFor();
    await button('退出登录').click();await page.getByRole('heading',{name:'欢迎回来'}).waitFor();
    assert.equal(await page.evaluate(()=>sessionStorage.getItem('zhongan_chat_token')),null);
    assert.equal(await page.evaluate(()=>Object.keys(localStorage).filter(key=>key.startsWith('zhongan_view_member:')).length),0);
    assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'verification.json'),JSON.stringify({widths:[320,390,1024],checks:['unchanged home','latest encounter grouping','person filtering','record detail return','no overflow','keyboard dialog focus and escape','stale response isolation','member consent','independent intake owner','draft retention','conversation owner','add and edit member','reload selection','logout cleanup'],errors},null,2));
    console.log('PASS: Chromium family flows and responsive layouts; synthetic data only. Screenshots: output_dir/family-members');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
