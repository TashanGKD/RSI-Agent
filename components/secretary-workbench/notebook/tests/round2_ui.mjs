// In-memory fixture only: no source connectors or live notebook writes.
import assert from 'node:assert/strict';
import http from 'node:http';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || '/home/operator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=new URL('../web/',import.meta.url), records=[];
const common={counterparty:'吕老师',people:['吕老师'],timeRequirement:'时间待定',assignee:'我',revision:0,active:true,reviewedByHuman:false,selectedState:'待判断',reviewRound:'round2',kind:'action',note:''};
const tasks=[
 {...common,id:'A',title:'复核方案并反馈',recommendation:{state:'待办',reason:'本轮需要明确回复'},completionCriterion:'向吕老师发送完整修改意见',sourceContacts:[{channel:'微信',conversationName:'科学智能工作群',senderName:'协作者丙',replyToName:'吕老师',at:'2026-10-21T10:00:00Z'},{channel:'微信',conversationName:'<img src=x onerror=alert(1)>',senderName:'真实显示名'}]},
 {...common,id:'OLD',title:'旧历史待核事项',deadlineDate:'2020-01-01',recommendation:{state:'待判断',reason:'只有历史要求，当前执行结果未知'}},
 {...common,id:'B',title:'等待下一轮意见',recommendation:{state:'等对方',reason:'等待收件人回复'}},
 {...common,id:'M',title:'一次想法的备忘',kind:'memo',recommendation:{reason:'暂时没有明确交付'}},
 {...common,id:'P',title:'科研平台建设',kind:'project'},
 {...common,id:'G',title:'培养长期研究能力',kind:'goal'},
 {...common,id:'EXEC',title:'未来提醒仍需执行',selectedState:'待处理',reviewedByHuman:true,assignee:'AI',reminder:{kind:'day7',at:'2026-12-21T10:00:00Z',timezone:'UTC'}},
 {...common,id:'PAUSE',title:'暂缓到期复查',selectedState:'暂缓',reviewedByHuman:true,needsReview:true,reminder:{kind:'custom',at:'2026-10-20T10:00:00Z',timezone:'UTC'}},
 {...common,id:'DONE',title:'已经完成保持原样',selectedState:'已完成',reviewedByHuman:true},
 {...common,id:'CONF',title:'本人确认保留原选项',selectedState:'等对方',reviewedByHuman:true,recommendation:{state:'待办',reason:'旧建议'}},
 {...common,id:'END',title:'不用再处理',selectedState:'已结束',reviewedByHuman:true},
];
tasks[0].sourceContacts.push(...Array.from({length:30},(_,i)=>({...tasks[0].sourceContacts[0],messageId:'copy-'+i})),{channel:'腾讯会议',conversationName:'方案复盘会议',senderName:'发言人1'});
const server=http.createServer(async(req,res)=>{
 const path=new URL(req.url,'http://127.0.0.1').pathname;res.setHeader('Content-Type','application/json;charset=utf-8');
 if(path==='/api/bootstrap')return res.end(JSON.stringify({csrfToken:'fixture',tasks,meta:{}}));
 if(path==='/api/reminders')return res.end('{"tasks":[]}');
 if(path.startsWith('/api/tasks/')){
  const task=tasks.find(t=>t.id===path.split('/')[3]);
  if(path.endsWith('/record')){let raw='';for await(const c of req)raw+=c;const body=JSON.parse(raw);records.push({id:task.id,...body});
   assert.equal(body.expectedRevision,task.revision);assert.ok(body.requestId);task.revision++;
   if(body.state){task.selectedState=body.state;task.reviewedByHuman=true;task.needsReview=false;}
   if(body.kind){task.kind=body.kind;task.reviewedByHuman=true;task.needsReview=false;}
   if(body.note)task.note=body.note;
   return res.end(JSON.stringify({task}));}
  return res.end(JSON.stringify({task,evidence:[],sourceLinks:[],timeline:task.id==='A'?[{actor:{name:'秘书',kind:'ai'},at:'2026-10-21T10:00:00Z',sources:[{label:'原始群消息',quote:'本轮向吕老师反馈课程意见'}]}]:[]}));
 }
 const f=({'/':'index.html','/app.js':'app.js','/style.css':'style.css'})[path]||(path.startsWith('/fonts/')&&!path.includes('..')?path.slice(1):null);
 try{res.setHeader('Content-Type',f?.endsWith('.js')?'text/javascript':f?.endsWith('.css')?'text/css':f?.endsWith('.html')?'text/html':'application/octet-stream');res.end(await readFile(new URL(f||'missing',root)));}catch{res.statusCode=404;res.end('');}
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));let browser;
try{
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const context=await browser.newContext({permissions:['clipboard-read','clipboard-write']});
 const page=await context.newPage();page.setDefaultTimeout(3000);await page.goto('http://127.0.0.1:'+server.address().port);await page.locator('[data-task-id="A"]').waitFor();
 const a=page.locator('[data-task-id="A"]');
 const order=await page.locator('.task-row').evaluateAll(rows=>rows.map(x=>x.dataset.taskId));assert.ok(order.indexOf('A')<order.indexOf('OLD'),'current actionable recommendations precede old uncertain deadlines');
 assert.equal(await a.locator('.source-contact').count(),2,'list compresses repeated message identities to two primary source rows');
 assert.equal(await a.locator('.actual-state').innerText(),'待判断');
 assert.equal(await a.locator('[data-state="待办"]').getAttribute('aria-checked'),'true');
 assert.match(await a.locator('.recommendation').innerText(),/AI建议.*待办/);assert.equal(await a.locator('.recommendation-reason').count(),0,'reason is available in detail without crowding the list');
 assert.match(await a.locator('.source-contacts').innerText(),/科学智能工作群.*协作者丙.*吕老师.*18:00/s);
 assert.equal(await a.locator('img').count(),0,'source strings render as text');
 await a.locator('.source-copy').first().click();assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),'科学智能工作群');
 await page.evaluate(()=>{navigator.clipboard.writeText=async()=>{throw Error('clipboard unavailable');};document.execCommand=()=>{window.copiedFallback=document.querySelector('.clipboard-fallback').value;return true;};});
 await a.locator('.source-copy').nth(1).click();assert.equal(await page.evaluate(()=>window.copiedFallback),'协作者丙','clipboard fallback copies the exact display name');
 await a.locator('.task-title').click();await page.locator('#drawer-content').getByText('向吕老师发送完整修改意见',{exact:true}).waitFor();
 const evidenceSection=page.locator('#drawer-content .detail-section').filter({has:page.getByRole('heading',{name:'原文依据',exact:true})});await evidenceSection.getByText('本轮向吕老师反馈课程意见',{exact:true}).waitFor();assert.equal(await evidenceSection.getByText('本轮向吕老师反馈课程意见',{exact:true}).count(),1,'new item event sources appear directly in the evidence section');assert.ok(!(await evidenceSection.innerText()).includes('暂无可读取'));
 assert.equal(await page.locator('#drawer-content .source-contact').count(),3,'detail retains all distinct source identities');
 await page.locator('#drawer-controls [data-state="等对方"]').click();assert.equal(await page.locator('#drawer-content .state-badge').innerText(),'待判断','draft never changes actual badge');
 await page.locator('#drawer-close').click();assert.equal(await a.locator('[data-state="等对方"]').getAttribute('aria-checked'),'true');
 await a.locator('[data-state="待办"]').click();await a.locator('.note').fill('只补充信息');await a.locator('.add-note').click();await page.waitForFunction(()=>document.querySelector('[data-task-id="A"] .note').value==='');
 assert.equal(records.at(-1).state,undefined,'note alone does not adopt recommendation');assert.equal(records.at(-1).kind,undefined);
 assert.equal(await a.locator('.actual-state').innerText(),'待判断');assert.equal(await a.locator('[data-state="待办"]').getAttribute('aria-checked'),'true');
 await a.locator('.note').fill('确认意见');await a.locator('.note').press('Shift+Enter');await a.locator('.note').dispatchEvent('keydown',{key:'Enter',isComposing:true});await a.locator('.note').dispatchEvent('keydown',{key:'Enter',repeat:true});assert.equal(records.length,1);
 await a.locator('.note').press('Enter');await page.waitForFunction(()=>!document.querySelector('[data-task-id="A"]'));
 assert.equal(records.at(-1).state,'待办');
 assert.equal(await page.evaluate(()=>document.activeElement.closest('[data-editor-for]')?.dataset.editorFor),'B','continuous confirmation advances focus');
 await page.keyboard.press('Enter');await page.waitForFunction(()=>!document.querySelector('[data-task-id="B"]'));assert.equal(records.at(-1).state,'等对方');
 assert.equal(await page.locator('[data-task-id="M"]').count(),0,'main review queue contains actionable deliveries; memos stay in their view');
 await page.locator('#view').selectOption('备忘');
 const m=page.locator('[data-task-id="M"]');assert.equal(await m.locator('.choice').count(),0,'memo has no business status requirement');
 await m.locator('[data-confirm-for]').click();await page.waitForFunction(()=>document.querySelector('[data-task-id="M"] .confirm-state')?.textContent.includes('已确认'));assert.equal(records.at(-1).kind,'memo');assert.equal(records.at(-1).state,undefined);
 await page.locator('#view').selectOption('备忘');assert.equal(await page.locator('[data-task-id="M"]').count(),1);
 await page.locator('#view').selectOption('项目');const p=page.locator('[data-task-id="P"]');await p.locator('.convert-action').click();await p.locator('[data-state="待办"]').click();await p.locator('[data-confirm-for]').click();await page.waitForFunction(()=>!document.querySelector('[data-task-id="P"]'));assert.equal(records.at(-1).kind,'action');assert.equal(records.at(-1).state,'待办');
 await page.locator('#view').selectOption('目标');assert.equal(await page.locator('[data-task-id="G"]').count(),1);
 await page.locator('#view').selectOption('待办');assert.equal(await page.locator('[data-task-id="EXEC"]').count(),1,'future reminder does not hide execution view');
 await page.locator('#owner').selectOption('AI');assert.equal(await page.locator('.task-row').count(),1);await page.locator('#owner').selectOption('');
 await page.locator('#view').selectOption('待我确认');assert.equal(await page.locator('[data-task-id="PAUSE"]').count(),1,'due paused item can return for review');assert.equal(await page.locator('[data-task-id="DONE"]').count(),0);
 await page.locator('#view').selectOption('全部');assert.match(await page.locator('[data-task-id="DONE"]').getAttribute('class'),/is-complete/);assert.match(await page.locator('[data-task-id="END"]').getAttribute('class'),/is-ended/);
 assert.equal(await page.locator('[data-task-id="EXEC"] [data-state="待办"]').getAttribute('aria-checked'),'true','old alias maps to canonical draft');
 assert.equal(await page.locator('[data-task-id="CONF"] [data-state="等对方"]').getAttribute('aria-checked'),'true','human choice takes precedence over AI recommendation');
 if(process.env.ROUND2_SCREENSHOT){await page.setViewportSize({width:1440,height:1000});await page.screenshot({path:process.env.ROUND2_SCREENSHOT,fullPage:true});}
 console.log('PASS: round2 recommendation vs actual, kind confirmation/conversion, source copy/XSS/time, owner/execution views, note-only, continuous Enter, drawer parity, paused review and closed aliases');
}finally{if(browser)await browser.close();await new Promise(r=>server.close(r));}
