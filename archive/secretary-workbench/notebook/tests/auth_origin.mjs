// Strict fixed-origin auth under no-referrer: real WebKit, isolated fixture only.
import assert from 'node:assert/strict';import http from 'node:http';import {readFile} from 'node:fs/promises';import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{webkit}=require(process.env.PLAYWRIGHT_MODULE||'/home/operator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const files=Object.fromEntries(await Promise.all(['index.html','auth.js','auth.css'].map(async name=>[name,await readFile(new URL('../web-access/'+name,import.meta.url))])));
let base,accepted=0;const origins=[];
const server=http.createServer(async(req,res)=>{
 res.setHeader('Referrer-Policy','no-referrer');res.setHeader('Cache-Control','no-store');
 const path=new URL(req.url,'http://127.0.0.1').pathname;
 if(path==='/api/auth/status'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({authenticated:false,initialized:true,usernameRequired:true}));return;}
 if(req.method==='POST'&&path==='/api/auth/login'){
  let raw='';for await(const x of req)raw+=x;
  origins.push(req.headers.origin||'missing');res.setHeader('Content-Type','application/json');
  if(req.headers.origin!==base){res.writeHead(403);res.end(JSON.stringify({error:'请求来源未获验证',code:'origin'}));return;}
  const body=JSON.parse(raw);if(body.username!=='fixture_owner'||body.password!=='fixture-pass'){res.writeHead(401);res.end(JSON.stringify({error:'账号或密码不正确',code:'authentication'}));return;}
  accepted++;res.end('{"ok":true}');return;
 }
 const name=path==='/login'?'index.html':path.slice(1);
 if(files[name]){res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html');res.end(files[name]);return;}
 res.setHeader('Content-Type','text/html');res.end('<h1>fixture notebook</h1>');
});await new Promise(r=>server.listen(0,'127.0.0.1',r));base='http://127.0.0.1:'+server.address().port;
let browser;try{
 for(const origin of ['null','https://evil.example',base+'.evil.example']){
  const r=await fetch(base+'/api/auth/login',{method:'POST',headers:{Origin:origin,'Content-Type':'application/json'},body:JSON.stringify({username:'fixture_owner',password:'fixture-pass'})});assert.equal(r.status,403);
 }
 browser=await webkit.launch({headless:true});const context=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});const p=await context.newPage();
 await p.goto(base+'/login');await p.locator('#username').waitFor({state:'visible'});await p.locator('#username').fill('fixture_owner');await p.locator('#password').fill('fixture-pass');
 const response=p.waitForResponse(r=>r.url()===base+'/api/auth/login'&&r.request().method()==='POST');await p.locator('#auth-submit').click();const r=await response;
 assert.equal(r.status(),200,'Real WebKit login rejected; observed Origin '+origins.at(-1));await p.waitForURL('**/#today');assert.equal(accepted,1);assert.equal(origins.at(-1),base);
 assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 console.log('PASS: real mobile WebKit sends fixed Origin under no-referrer; null/foreign/lookalike origins remain rejected');
}finally{await browser?.close();await new Promise(r=>server.close(r));}
