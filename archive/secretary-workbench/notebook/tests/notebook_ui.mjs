// Isolated notebook fixture: never writes any human record or contacts source services.
import assert from 'node:assert/strict';
import http from 'node:http';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || '/home/operator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=new URL('../web/',import.meta.url);
const common={counterparty:'吕老师',people:['吕老师'],proposedDisplayAt:'2026-10-21',timeRequirement:'时间待定',suggestedState:'待办',selectedState:'待办',confirmed:true,note:'旧备注不应预填',revision:0,active:true,assignee:'我',reminder:null};
let tasks=[{...common,id:'MINE',title:'本人处理事项',sourceChanged:true},{...common,reviewedByHuman:true,id:'AI',title:'交给AI的事项',assignee:'AI'},{...common,reviewedByHuman:true,id:'OTHER',title:'小张的事项',assignee:'小张'},{...common,id:'DUE',title:'等待且到期提醒',selectedState:'等对方',reminder:{kind:'custom',at:'2020-01-01T10:00:00Z',timezone:'UTC'}},{...common,reviewedByHuman:true,id:'DONE',title:'完成事项',selectedState:'已完成'}];
let records=[],created=[],timeline=[],conflict=false;
const server=http.createServer(async(req,res)=>{
 const path=new URL(req.url,'http://127.0.0.1').pathname;
 res.setHeader('Content-Type','application/json;charset=utf-8');
 if(path==='/api/bootstrap')return res.end(JSON.stringify({csrfToken:'fixture',tasks,meta:{},notificationMode:'in_app'}));
 if(path==='/api/reminders')return res.end('{"tasks":[]}');
 if(req.method==='POST'&&path==='/api/tasks'){
  let raw='';for await(const c of req)raw+=c;const body=JSON.parse(raw);created.push(body);
  const task={...common,...body,id:'LOCAL-1',revision:1};tasks.push(task);return res.end(JSON.stringify({task}));
 }
 if(path.startsWith('/api/tasks/')){
  const id=decodeURIComponent(path.split('/')[3]);const task=tasks.find(t=>t.id===id);
  if(req.method==='POST'&&path.endsWith('/record')){
   let raw='';for await(const c of req)raw+=c;const body=JSON.parse(raw);records.push(body);
   if(conflict){conflict=false;task.revision++;task.selectedState='待判断';res.statusCode=409;return res.end(JSON.stringify({error:'新版本冲突'}));}
   if('state'in body){task.selectedState=body.state;task.reviewedByHuman=true;}if('assignee'in body)task.assignee=body.assignee;if('reminder'in body)task.reminder=body.reminder;if(['已完成','不用管了'].includes(task.selectedState))task.reminder=null;
   if(body.note){timeline.push({actor:{name:'测试记录人',kind:'human'},author:'测试记录人',at:new Date().toISOString(),note:body.note});task.note=body.note;}
   task.revision++;return res.end(JSON.stringify({task}));
  }
  return res.end(JSON.stringify({task,timeline,evidence:[],sourceLinks:[],history:[],relatedTasks:[]}));
 }
 const assets={'/':'index.html','/app.js':'app.js','/style.css':'style.css'};const file=assets[path]||(path.startsWith('/fonts/')&&!path.includes('..')?path.slice(1):null);
 try{const data=await readFile(new URL(file||'missing',root));res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.html')?'text/html':'application/octet-stream');res.end(data);}catch{res.statusCode=404;res.end('');}
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));let browser;
try{
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const context=await browser.newContext();const page=await context.newPage();await page.goto('http://127.0.0.1:'+server.address().port);await page.locator('.task-row').first().waitFor();
 assert.equal(await page.locator('.task-row').count(),2,'my-work includes my pending and due waiting, excludes delegated');
 await page.locator('#view').selectOption('全部');const row=()=>page.locator('[data-task-id="MINE"]');
 assert.equal(await row().locator('[role="radio"]').count(),6,'six canonical business states');
 assert.equal(await row().locator('.note').inputValue(),'','old note never becomes a new draft');
 assert.ok(!(await row().innerText()).includes('事项已更新'));
 await row().locator('[data-state="待办"]').click();await row().locator('[data-confirm-for]').click();await page.waitForTimeout(100);assert.equal(records.at(-1).state,'待办');
 await page.locator('#view').selectOption('待办');assert.equal(await page.locator('.task-row').count(),3);await page.locator('#view').selectOption('待我确认');assert.equal(await row().count(),0,'confirmed in-progress item leaves the review queue');await page.locator('#view').selectOption('全部');records.length=0;
 await row().locator('[data-state="等对方"]').click();await row().locator('.note').fill('第一条备注 <img src=x onerror=alert(1)>');
 await row().getByRole('button',{name:'添加备注',exact:true}).click();await page.waitForTimeout(100);
 assert.equal(records.length,1);assert.equal(records[0].note,'第一条备注 <img src=x onerror=alert(1)>');assert.ok(!('state'in records[0]));assert.ok(!('assignee'in records[0]));assert.ok(records[0].requestId);
 assert.equal(await row().locator('[data-state="等对方"]').getAttribute('aria-checked'),'true','note-only preserves unsaved state');
 await row().locator('[data-confirm-for]').click();await page.waitForTimeout(100);assert.equal(records.at(-1).state,'等对方');assert.ok(!('note'in records.at(-1)));
 await row().locator('.assignee-select').selectOption('AI');assert.equal(await row().locator('.reminder-host select').count(),0,'reminder uses direct buttons');assert.equal(await row().getByRole('button',{name:'截止前一天',exact:true}).isDisabled(),true,'unknown deadline cannot generate a reminder');await row().getByRole('button',{name:'2天后',exact:true}).click();assert.equal(await row().getByRole('button',{name:'2天后',exact:true}).getAttribute('aria-pressed'),'true');await row().locator('[data-confirm-for]').click();await page.waitForTimeout(100);
 assert.equal(records.at(-1).state,'等对方');assert.equal(records.at(-1).assignee,'AI');assert.ok(records.at(-1).reminder.at);assert.equal(records.at(-1).reminder.kind,'day2');assert.ok(Math.abs(Date.parse(records.at(-1).reminder.at)-Date.now()-2*86400000)<3000);
 await page.locator('#view').selectOption('交给AI处理');assert.equal(await page.locator('.task-row').count(),2);
 await page.locator('#view').selectOption('分派给他人');assert.equal(await page.locator('.task-row').count(),1);
 await page.locator('#view').selectOption('稍后提醒');assert.equal(await page.locator('.task-row').count(),2);
 await page.locator('#view').selectOption('全部');await row().locator('.assignee-select').selectOption('other');await row().locator('.assignee-name').fill('李老师');
 const before=records.length;await row().locator('.assignee-name').press('Enter');assert.equal(records.length,before,'assignee text Enter cannot submit');
 await row().locator('.note').fill('第二条');await row().locator('.note').press('Shift+Enter');assert.ok((await row().locator('.note').inputValue()).includes('\n'));await row().locator('.note').dispatchEvent('keydown',{key:'Enter',isComposing:true});await row().locator('.note').dispatchEvent('keydown',{key:'Enter',keyCode:229});assert.equal(records.length,before);
 await page.locator('#search').press('Enter');assert.equal(records.length,before);
 await row().locator('.note').press('Enter');await page.waitForTimeout(100);assert.equal(records.length,before+1);assert.equal(records.at(-1).assignee,'李老师');
 await row().locator('[data-state="已完成"]').click();await row().locator('[data-confirm-for]').click();await page.waitForTimeout(100);
 assert.equal(await row().locator('.reminder-choice[aria-pressed="true"]').count(),0,'closed response clears reminder in shared draft');
 await row().locator('[data-state="等对方"]').click();await row().locator('[data-confirm-for]').click();await page.waitForTimeout(100);
 await row().locator('.task-title').click();await page.locator('.timeline-author').first().waitFor();assert.equal(await page.locator('.timeline-author').first().innerText(),'测试记录人');assert.equal(await page.locator('#drawer-content img').count(),0);
 const drawer=page.locator('#drawer-controls');await drawer.locator('.note').fill('冲突草稿');conflict=true;await drawer.locator('[data-confirm-for]').click();await drawer.locator('.resolve-button').waitFor();assert.equal(await drawer.locator('.note').inputValue(),'冲突草稿');
 await drawer.locator('.resolve-button').click();assert.equal(await drawer.locator('[data-state="待判断"]').getAttribute('aria-checked'),'true','untouched status accepts latest version while note stays');await drawer.locator('.note').press('Enter');await page.waitForTimeout(100);assert.equal(records.at(-1).note,'冲突草稿');
 await page.locator('#drawer-close').click();await page.locator('#create-toggle').click();await page.locator('#create-title').fill('新的独立交付');await page.locator('#create-counterparty').fill('吕老师');await page.locator('#create-note').fill('下一阶段');await page.locator('#create-related').selectOption('MINE');await page.locator('#create-submit').click();await page.waitForTimeout(100);
 assert.equal(created.length,1);assert.equal(created[0].state,'待办');assert.equal(created[0].assignee,'我');assert.deepEqual(created[0].relatedRecordIds,['MINE']);assert.ok(created[0].requestId);
 await page.reload();await page.locator('#view').selectOption('全部');assert.equal(await page.locator('[data-task-id="LOCAL-1"]').count(),1,'created item survives readback');
 assert.ok((await page.locator('[data-task-id="DONE"]').getAttribute('class')).includes('is-complete'));
 assert.equal(timeline.length,3,'each free note appends exactly once');
 // Previously persisted drafts migrate without resubmitting the old saved note.
 const mine=tasks.find(task=>task.id==='MINE'),other=tasks.find(task=>task.id==='OTHER');
 await page.evaluate(({mine,other})=>{
  localStorage.removeItem('tashan-personal-actions-drafts-v2');
  localStorage.setItem('tashan-personal-actions-drafts-v1',JSON.stringify({
   MINE:{state:'交给AI处理',baseState:'待办',note:'尚未保存的旧版草稿',baseNote:'旧备注',revision:mine.revision},
   OTHER:{state:'稍后提醒',baseState:'待办',note:'旧版已保存备注',baseNote:'旧版已保存备注',revision:other.revision,reminderKind:'day3',reminderTouched:false}
  }));
 },{mine,other});
 const legacyPage=await page.context().newPage();await legacyPage.goto('http://127.0.0.1:'+server.address().port);await legacyPage.locator('.task-row').first().waitFor();await legacyPage.locator('#view').selectOption('全部');
 const legacyRow=legacyPage.locator('[data-task-id="MINE"]');
 assert.equal(await legacyRow.locator('.note').inputValue(),'尚未保存的旧版草稿');
 assert.equal(await legacyRow.locator('.assignee-select').inputValue(),'AI');
 assert.equal(await legacyRow.locator('[data-state="待办"]').getAttribute('aria-checked'),'true');
 const oldReminder=legacyPage.locator('[data-task-id="OTHER"]');
 assert.equal(await oldReminder.locator('.note').inputValue(),'');assert.equal(await oldReminder.locator('[data-reminder-kind="day3"]').getAttribute('aria-pressed'),'true');
 await legacyPage.setViewportSize({width:1440,height:1000});
 if(process.env.NOTEBOOK_SCREENSHOT)await legacyPage.screenshot({path:process.env.NOTEBOOK_SCREENSHOT,fullPage:true});
 console.log('PASS: notebook create/readback, append notes, independent status/assignee/reminder, filters, drawer actor/text safety, conflicts, legacy drafts and keyboard guards');
}finally{if(browser)await browser.close();await new Promise(r=>server.close(r));}
