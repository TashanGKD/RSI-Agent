import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium,webkit}=require('/home/operator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const ws=mkdtempSync(tmpdir()+'/notebook-work-');
const py=spawn('python3',['-u','-c',`from pathlib import Path
from local_server import make_server
s=make_server(Path(${JSON.stringify(ws)}),port=0);n=s.notebook
t=n.create_task(dict(title='本轮材料交付',state='已完成',assignee='服务对象甲',domain='他山'))
w=dict(start='2026-10-14',end='2026-10-14',participants=['服务对象甲'],organizations=['他山协会'])
n.append_record(dict(text='已交材料；不代表报销已支付。',objectIds=[t['id']],work=w,sourceRefs=[dict(sourceId='wechat:fixture',nativeId='real-test',conversation='协会报销群',sender='服务对象甲',at='2026-10-14',precision='date')]))
n.record(t['id'],dict(expectedRevision=n.get_task(t['id'])['revision'],note='收件方确认收到',work=w))
n.create_task(dict(title='未来仍要做的事',state='待办',assignee='其他人',domain='他山',planDate='2030-01-01'))
print(s.server_port,flush=True);s.serve_forever()`],{cwd:new URL('..',import.meta.url).pathname,stdio:['ignore','pipe','pipe']});
let browser,stderr='';py.stderr.on('data',b=>stderr+=b);
try{
 const port=await new Promise((resolve,reject)=>{py.stdout.once('data',b=>resolve(Number(String(b).trim())));py.once('exit',()=>reject(Error(stderr)));});
 browser=process.env.SCHEDULE_ENGINE==='webkit'?await webkit.launch():await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});let errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:'+port+'/#notebook');
 await page.getByRole('button',{name:'发生的工作',exact:true}).click({timeout:3000});
 await page.getByLabel('发生日期从').fill('2026-10-14');await page.getByLabel('发生日期至').fill('2026-10-14');
 await page.getByRole('button',{name:'查看',exact:true}).click();
 await page.getByRole('button',{name:'本轮材料交付',exact:true}).waitFor();
 assert.equal(await page.locator('.work-row').count(),1);assert.equal(await page.getByText('2条进展',{exact:true}).count(),1);
 await page.getByLabel('实际参与人').selectOption('服务对象甲');await page.getByLabel('组织').selectOption('他山协会');
 await page.getByRole('button',{name:'查看',exact:true}).click();
 await page.locator('.work-row').waitFor();if(process.env.WORK_SCREENSHOTS)await page.screenshot({path:process.env.WORK_SCREENSHOTS+'/work-1440.png'});
 const row=page.locator('.work-row');await row.waitFor();await row.locator('.work-people').click();
 const detail=page.locator('#detail-panel');await detail.getByRole('heading',{name:'工作进展',exact:true}).waitFor();
 assert.ok((await detail.innerText()).includes('协会报销群'));assert.ok((await detail.innerText()).includes('已交材料；不代表报销已支付。'));
 assert.ok((await detail.innerText()).includes('记录于'));assert.ok((await detail.innerText()).includes('2026-10-14'));
 for(const width of [1440,390,320]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.ok(await detail.evaluate(e=>e.scrollWidth<=e.clientWidth+1));if(process.env.WORK_SCREENSHOTS)await page.screenshot({path:process.env.WORK_SCREENSHOTS+'/work-detail-'+width+'.png'});}
 await detail.getByRole('button',{name:'关闭详情',exact:true}).click();await page.getByRole('button',{name:'全部事项',exact:true}).click();
 await page.getByRole('button',{name:'未来仍要做的事',exact:true}).waitFor();
 for(const width of [1440,390,320]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));if(process.env.WORK_SCREENSHOTS)await page.screenshot({path:process.env.WORK_SCREENSHOTS+'/notebook-'+width+'.png'});}
 assert.deepEqual(errors,[]);console.log('PASS unified work filters, one row per object, source detail, all owners and responsive UI');
}finally{await browser?.close();py.kill();await new Promise(r=>py.once('exit',r));rmSync(ws,{recursive:true,force:true});}
