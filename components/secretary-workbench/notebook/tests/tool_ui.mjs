import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium,webkit}=require('/home/operator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const workspace=mkdtempSync(tmpdir()+'/notebook-tool-ui-');
const py=spawn('python3',['-u','-c',`from pathlib import Path
from local_server import make_server
from contracts import today
s=make_server(Path(${JSON.stringify(workspace)}),port=0)
n=s.notebook
x=n.create_task(dict(title='复核方案并回复',domain='他山',state='等对方',planDate=today(),confirm=True,summary='原摘要',sourceContacts=[dict(sourceId='wechat:fixture',nativeId='native-real-fixture',conversation='培训工作群',sender='协作者丙')]))
n.record(x['id'],dict(expectedRevision=x['revision'],state='待办',summary='本轮复核课程与收费'))
imp=s.sources.import_records('wechat','fixture',[dict(nativeId='fixture-msg',text='隔离合成原记录',at=today()+'T09:00:00+08:00')])
s.sources.persist_read_receipt('wechat:fixture',imp['snapshot'],imp['recordIds'])
print(s.server_port,flush=True)
s.serve_forever()`],{cwd:new URL('..',import.meta.url).pathname,stdio:['ignore','pipe','pipe']});
let stderr='';py.stderr.on('data',b=>stderr+=b);let browser;
try{
 const port=await new Promise((resolve,reject)=>{py.stdout.once('data',b=>resolve(Number(b.toString().trim())));py.once('exit',()=>reject(new Error(stderr)));});const base='http://127.0.0.1:'+port;
 browser=process.env.SCHEDULE_ENGINE==='webkit'?await webkit.launch({headless:true}):await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base);await page.getByRole('button',{name:'复核方案并回复',exact:true}).click();const dialog=page.getByRole('dialog',{name:'日程详情'});await dialog.getByRole('heading',{name:'群聊与联系人',exact:true}).waitFor();assert.ok((await dialog.innerText()).includes('培训工作群 · 协作者丙'));
 await dialog.locator('.tool-history>summary').click();await dialog.getByRole('button',{name:'读取操作历史',exact:true}).click();const op=dialog.locator('.tool-history article').filter({hasText:'修改：state、summary'});await op.waitFor();await op.locator('summary').click();await op.getByRole('button',{name:'预览恢复',exact:true}).click();await op.getByRole('button',{name:'确认恢复',exact:true}).click();await dialog.getByText('已追加恢复记录',{exact:true}).waitFor();
 let boot=await (await page.request.get(base+'/api/bootstrap')).json();let task=boot.tasks[0];assert.equal(task.state,'等对方');assert.equal(task.summary,'原摘要');assert.equal(await dialog.getByRole('radio',{name:'等对方',exact:true}).getAttribute('aria-checked'),'true','restored actual state rebases clean editor');
 const confirmed=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().includes('/api/schedule/')&&r.url().endsWith('/record'));await dialog.getByRole('button',{name:'确认',exact:true}).click();assert.equal((await confirmed).status(),200);
 await dialog.locator('.tool-metadata>summary').click();await dialog.getByLabel('明确截止日期（北京时间）').fill('2026-11-01');await dialog.getByRole('button',{name:'保存这些字段',exact:true}).click();await dialog.getByText('字段已保存',{exact:true}).waitFor();
 await dialog.locator('.tool-attach>summary').click();await dialog.getByLabel('补充事项附件').setInputFiles({name:'工作说明.txt',mimeType:'text/plain',buffer:Buffer.from('隔离附件内容')});await dialog.getByLabel('附件备注').fill('补充附件，状态不变');await dialog.getByRole('button',{name:'保存附件与备注',exact:true}).click();await dialog.getByText('附件与备注已保存',{exact:true}).waitFor();await page.getByRole('button',{name:'关闭日程详情',exact:true}).click();
 await page.getByRole('button',{name:'记事本',exact:true}).click();await page.getByRole('button',{name:'复核方案并回复',exact:true}).click();const detail=page.locator('#detail-panel');await detail.getByRole('heading',{name:'已保存附件',exact:true}).waitFor();const link=detail.getByRole('link',{name:'工作说明.txt',exact:true});assert.equal(await link.count(),1);assert.equal((await page.request.get(base+await link.getAttribute('href'))).status(),200);
 for(const width of [1440,390,320]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'no document overflow');assert.ok(await detail.evaluate(e=>e.scrollWidth<=e.clientWidth+1),'detail within phone');if(process.env.SCHEDULE_SCREENSHOTS)await page.screenshot({path:process.env.SCHEDULE_SCREENSHOTS+`/tools-detail-${width}.png`});}
 await detail.getByRole('button',{name:'关闭详情',exact:true}).click();await page.getByRole('button',{name:'信源',exact:true}).click();await page.getByText('已有保存资料',{exact:true}).waitFor();assert.ok((await page.locator('#main-content').innerText()).includes('不代表上游完整覆盖'));await page.getByRole('button',{name:'版本与读取收据',exact:true}).click();await page.getByRole('heading',{name:'实际读取收据',exact:true}).waitFor({timeout:5000}).catch(async e=>{console.log(JSON.stringify({errors,dialogs:await page.locator('dialog').evaluateAll(es=>es.map(e=>({open:e.open,label:e.getAttribute('aria-label'),text:e.innerText}))),body:(await page.locator('body').innerText()).slice(-1600)}));throw e;});await page.getByRole('dialog',{name:'信源版本与收据'}).getByRole('button',{name:'关闭信源记录',exact:true}).click();
 boot=await (await page.request.get(base+'/api/bootstrap')).json();task=boot.tasks[0];assert.equal(task.state,'等对方');assert.equal(task.deadlineDate,'2026-11-01');const d=await(await page.request.get(base+'/api/tasks/'+task.id)).json();assert.ok(d.timeline.some(x=>x.note==='补充附件，状态不变'&&x.attachments.length===1));assert.deepEqual(errors,[]);
 console.log('PASS shared tools: restore/rebase, locator, deadline, attachment readback, notebook+schedule details, mobile and source coverage.');
}finally{await browser?.close();py.kill();await new Promise(r=>py.once('exit',r));rmSync(workspace,{recursive:true,force:true});}
