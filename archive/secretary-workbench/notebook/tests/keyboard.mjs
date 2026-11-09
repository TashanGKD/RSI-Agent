// Isolated browser regression: serves fixture APIs in memory, never touches live records.
import assert from 'node:assert/strict';
import http from 'node:http';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || '/home/operator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root = new URL('../web/',import.meta.url);
const states = ['待判断','待办','等对方','暂缓','已完成','不用管了'];
let confirmations = [], delayDetail=false, releaseDetail=null;
const task = {id:'KEY-1',title:'键盘确认测试事项',counterparty:'测试联系人',people:['测试联系人'],proposedDisplayAt:'2026-10-21',timeRequirement:'时间待定',suggestedState:'待判断',selectedState:'待判断',assignee:'我',confirmed:false,note:'',revision:0,active:true};
const server = http.createServer(async(req,res)=>{
  const url = new URL(req.url,'http://127.0.0.1');
  res.setHeader('Content-Type','application/json; charset=utf-8');
  if(url.pathname==='/api/bootstrap')return res.end(JSON.stringify({csrfToken:'fixture',states,tasks:[{...task}],meta:{},notificationMode:'in_app'}));
  if(url.pathname==='/api/reminders')return res.end('{"tasks":[]}');
  if(url.pathname==='/api/tasks/KEY-1'){const send=()=>res.end(JSON.stringify({task:{...task},evidence:[],sourceLinks:[],history:[]}));if(delayDetail){releaseDetail=send;return;}return send();}
  if(url.pathname==='/api/tasks/KEY-1/record'){
    let text='';for await(const chunk of req)text+=chunk;
    const body=JSON.parse(text);confirmations.push(body);
    return res.end(JSON.stringify({task:{...task,note:body.note||'',selectedState:body.state||task.selectedState,confirmed:true,reviewedByHuman:true,revision:1}}));
  }
  const assets={'/':'index.html','/app.js':'app.js','/style.css':'style.css'};
  const file=assets[url.pathname] || (url.pathname.startsWith('/fonts/') && !url.pathname.includes('..') ? url.pathname.slice(1) : null);
  if(!file){res.statusCode=404;return res.end('{}');}
  try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.html')?'text/html':'application/octet-stream');res.end(await readFile(new URL(file,root)));}
  catch{res.statusCode=404;res.end('');}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const base='http://127.0.0.1:'+server.address().port;
let browser;
try{
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  async function fresh(){
    confirmations=[];
    const context=await browser.newContext({timezoneId:'America/New_York'});
    const page=await context.newPage();
    await page.goto(base);await page.waitForSelector('.task-row');
    return {page,context};
  }
  {
    const {page,context}=await fresh();
    const note=page.locator('.task-row .note');await note.fill('备注后直接确认');
    await note.press('Enter');await page.waitForTimeout(150);
    assert.equal(confirmations.length,1,'Enter in note must confirm the row');
    assert.equal(confirmations[0].note,'备注后直接确认');
    await context.close();
  }
  {
    const {page,context}=await fresh();
    const note=page.locator('.task-row .note');await note.fill('第一行');await note.press('Shift+Enter');
    await note.press('a');assert.equal(confirmations.length,0,'Shift+Enter must not submit');
    assert.ok((await note.inputValue()).includes('\n'),'Shift+Enter adds newline');
    await note.dispatchEvent('keydown',{key:'Enter',code:'Enter',isComposing:true});
    await note.dispatchEvent('keydown',{key:'Enter',code:'Enter',keyCode:229});
    await note.dispatchEvent('keydown',{key:'Enter',code:'Enter',repeat:true});
    assert.equal(confirmations.length,0,'IME and repeated keydown must not submit');
    await page.locator('#search').focus();await page.keyboard.press('Enter');
    assert.equal(confirmations.length,0,'Search Enter must not submit');
    await context.close();
  }
  {
    const {page,context}=await fresh();
    await page.locator('.task-title').click();await page.waitForTimeout(50);
    const note=page.locator('#drawer .note');await note.fill('详情内确认');
    await note.press('Enter');await page.waitForTimeout(150);
    assert.equal(confirmations.length,1,'Drawer Enter must confirm once');
    assert.equal(confirmations[0].note,'详情内确认');
    await context.close();
  }
  {
    const {page,context}=await fresh();
    const choice=page.locator('.task-row [data-state="等对方"]');
    await choice.click();await choice.press('Enter');await page.waitForTimeout(150);
    assert.equal(confirmations.length,1,'Enter on selected radio must confirm, not just select');
    assert.equal(confirmations[0].state,'等对方');
    await context.close();
  }
  {
    const {page,context}=await fresh();
    await page.locator('.task-row [data-confirm-for]').press('Enter');
    await page.waitForTimeout(150);
    assert.equal(confirmations.length,1,'Confirm button Enter must not double-submit');
    await context.close();
  }
  {
    const {page,context}=await fresh();
    await page.locator('.task-row [data-reminder-kind="day2"]').click();
    const active=await page.evaluate(()=>document.activeElement.outerHTML.slice(0,150));
    await page.keyboard.press('Enter');await page.waitForTimeout(150);
    assert.equal(confirmations.length,1,`Enter after reminder click confirms; active element was ${active}`);
    assert.equal(confirmations[0].reminder.kind,'day2','Enter must not toggle the reminder again');
    await context.close();
  }
  {
    const {page,context}=await fresh();
    await page.locator('.task-row [data-reminder-kind="day1"]').click();
    await page.locator('.task-row [data-reminder-kind="day1"]').click();
    await page.keyboard.press('Enter');await page.waitForTimeout(150);
    assert.equal(confirmations.length,1);assert.equal(confirmations[0].reminder,null,'Enter saves cancellation');
    await context.close();
  }
  {
    const {page,context}=await fresh();
    // Safari/WKWebView pointer clicks need not focus a button by default.
    await page.locator('.task-row [data-state="待办"]').dispatchEvent('click');
    await page.keyboard.press('Enter');await page.waitForTimeout(150);
    assert.equal(confirmations.length,1,'clicking status establishes the current keyboard item');
    assert.equal(confirmations[0].state,'待办');await context.close();
  }
  {
    const {page,context}=await fresh();
    await page.locator('.task-title').click();await page.locator('#drawer-content .detail-heading').waitFor();await page.waitForTimeout(100);
    await page.keyboard.press('Enter');await page.waitForTimeout(150);
    assert.equal(confirmations.length,1,'opening details makes Enter confirm its current selection');
    await context.close();
  }
  {
    const {page,context}=await fresh();delayDetail=true;releaseDetail=null;
    await page.locator('.task-title').click();while(!releaseDetail)await new Promise(r=>setTimeout(r,10));
    await page.locator('#drawer-controls .note').fill('迟到详情仍能回车确认');
    releaseDetail();delayDetail=false;await page.waitForTimeout(100);
    await page.keyboard.press('Enter');await page.waitForTimeout(150);
    assert.equal(confirmations.length,1,'late detail render preserves editing focus');
    assert.equal(confirmations[0].note,'迟到详情仍能回车确认');await context.close();
  }
  console.log('PASS: Enter list/drawer/radio; Shift+Enter newline; reminder selection/cancel, Safari focus, late drawer focus; IME/repeat/search guards');
}finally{
  if(browser)await browser.close();
  await new Promise(resolve=>server.close(resolve));
}
