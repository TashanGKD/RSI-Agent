// Uses an isolated fixture server; no actual notebook decisions are changed.
import assert from 'node:assert/strict';
import http from 'node:http';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require('/home/operator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=new URL('../web/',import.meta.url);
const common={counterparty:'协作者丙／吕老师',people:['协作者丙','吕老师'],proposedDisplayAt:'2026-10-20',timeRequirement:'日期待定',note:'',assignee:'我',revision:0,active:true,confirmed:false,stateUpdatedBy:'AI',stateUpdatedAt:'2026-10-21T10:00:00Z',progressCount:1};
const tasks=[
 {...common,reviewedByHuman:true,id:'REVIEW',title:'复核示例城市培训方案',selectedState:'已完成',suggestedState:'已完成',lastKnownState:'本人已经回复没问题，很细致',relatedRecordIds:['WAIT']},
 {...common,reviewedByHuman:true,id:'WAIT',title:'等吕老师反馈示例城市方案',selectedState:'等对方',suggestedState:'等对方',relatedRecordIds:['REVIEW']},
 {...common,id:'OPEN',deadlineDate:'2026-12-31',title:'需要本人处理的事项',selectedState:'待处理',suggestedState:'待处理'},
 {...common,id:'LATER',title:'通过邮件向通知者甲反馈年度考核报告题目',selectedState:'待处理',suggestedState:'待处理',deadlineDate:'2026-10-23',reminder:{kind:'day1',at:'2026-10-21T12:01:00Z',timezone:'UTC'}},
 {...common,reviewedByHuman:true,id:'AI',title:'已交AI的事项',selectedState:'待处理',suggestedState:'待处理',assignee:'AI'}
];
const server=http.createServer(async(req,res)=>{
 const path=new URL(req.url,'http://127.0.0.1').pathname;
 res.setHeader('Content-Type','application/json;charset=utf-8');
 if(path==='/api/bootstrap')return res.end(JSON.stringify({csrfToken:'fixture',tasks,meta:{},notificationMode:'in_app'}));
 if(path==='/api/reminders')return res.end('{"tasks":[]}');
 if(path.startsWith('/api/tasks/')){
  const id=path.split('/')[3],task=tasks.find(t=>t.id===id);
  return res.end(JSON.stringify({task,evidence:[],sourceLinks:[],history:[],timeline:[{author:'AI',at:common.stateUpdatedAt,state:task.selectedState,body:task.lastKnownState||'等待回复',sources:[]}],relatedTasks:(task.relatedRecordIds||[]).map(id=>tasks.find(t=>t.id===id))}));
 }
 const assets={'/':'index.html','/app.js':'app.js','/style.css':'style.css'};
 const f=assets[path]||(path.startsWith('/fonts/')&&!path.includes('..')?path.slice(1):null);
 try{const data=await readFile(new URL(f||'missing',root));res.setHeader('Content-Type',f.endsWith('.js')?'text/javascript':f.endsWith('.css')?'text/css':f.endsWith('.html')?'text/html':'application/octet-stream');res.end(data);}catch{res.statusCode=404;res.end('');}
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
let browser;
try{
 browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const page=await browser.newPage();
 await page.clock.install({time:new Date('2026-10-21T12:00:00Z')});
 await page.goto('http://127.0.0.1:'+server.address().port);await page.locator('.task-row').first().waitFor();
 assert.equal(await page.locator('#view').inputValue(),'待我确认');
 assert.equal(await page.locator('.task-row').count(),1);
 assert.ok((await page.locator('.task-row').innerText()).includes('需要本人处理'));
 await page.locator('#view').selectOption('稍后提醒');assert.equal(await page.locator('[data-task-id="LATER"]').count(),1,'snoozed task remains available outside default view');
 await page.locator('#view').selectOption('待我确认');assert.equal(await page.locator('[data-task-id="LATER"]').count(),0,'future reminders hide pending tasks from current work');
 await page.clock.runFor(61000);await page.locator('[data-task-id="LATER"]').waitFor();assert.equal(await page.locator('.task-row').count(),2,'due reminder automatically returns without refresh');
 await page.locator('#view').selectOption('全部');
 const done=page.locator('[data-task-id="REVIEW"]');
 assert.ok((await done.getAttribute('class')).includes('is-complete'));
 const color=await done.evaluate(el=>getComputedStyle(el).backgroundColor);
 assert.notEqual(color,'rgb(255, 255, 255)');
 await done.locator('.task-title').click();
 await page.locator('#drawer-content .related-task').waitFor();
 assert.ok((await page.locator('#drawer-content').innerText()).includes('已处理：已完成'));
 await page.locator('.related-task').click();
 await page.waitForFunction(()=>document.querySelector('#drawer-content h3').textContent==='等吕老师反馈示例城市方案');
 console.log('PASS: human-work default, green closed row, explicit AI state, linked next stage; future reminders hidden until due');
}finally{if(browser)await browser.close();server.close();}
