import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const enabled=process.env.TASHAN_TEST_DESKTOP_STARTUP==='1';
const launcher=fileURLToPath(new URL('../bridge/desktop_launcher.mjs',import.meta.url));
const node='/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node';
const args=['app-server','--analytics-default-enabled','-c','analytics.enabled=false','-c','plugins.codex-app-tools@openai-bundled.mcp_servers.codex_app.enabled=true'];

async function fallback(root,script=launcher){
 const shell=script.endsWith('/entry');
 const child=spawn(shell?script:node,shell?args:[script,...args],{env:{...process.env,TASHAN_DESKTOP_SOCKET_ROOT:root},stdio:['pipe','pipe','pipe']});
 let output='',errors='';child.stderr.on('data',b=>{errors=(errors+b).slice(-5000)});
 try{
  const reply=await new Promise((resolve,reject)=>{
   const timer=setTimeout(()=>reject(Error('no initialize response: '+errors)),12000);
   child.once('exit',()=>{clearTimeout(timer);reject(Error('launcher exited: '+errors))});
   child.stdout.on('data',b=>{output+=b;let i;while((i=output.indexOf('\n'))>=0){const line=output.slice(0,i);output=output.slice(i+1);try{const msg=JSON.parse(line);if(msg.id===1){clearTimeout(timer);resolve(msg)}}catch{}}});
   child.stdin.write(JSON.stringify({id:1,method:'initialize',params:{clientInfo:{name:'fallback_readonly_fixture',version:'1'},capabilities:{experimentalApi:true}}})+'\n');
  });
  assert.equal(typeof reply.result?.userAgent,'string',JSON.stringify(reply));
  assert.match(errors,/official native|native startup/i);
 }finally{
  child.stdin.end();
  if(child.exitCode===null){const done=once(child,'exit');child.kill('SIGTERM');await done;}
 }
}

for(const scenario of ['root-is-file','metadata-symlink','unknown-live-socket','missing-shared-modules','missing-runtime-shell','missing-launcher-shell','syntax-error-launcher-shell']){
 test(`Desktop initializes through official fallback: ${scenario}`,{skip:!enabled,timeout:15000},async()=>{
  const dir=fs.mkdtempSync('/private/tmp/wx-fallback-');fs.chmodSync(dir,0o700);
  const root=path.join(dir,'state');let server;
  try{
   if(scenario==='root-is-file')fs.writeFileSync(root,'keep',{mode:0o600});
   else fs.mkdirSync(root,{mode:0o700});
   if(scenario==='metadata-symlink'){
    fs.writeFileSync(path.join(dir,'keep'),'keep',{mode:0o600});
    fs.symlinkSync(path.join(dir,'keep'),path.join(root,'engine.json'));
   }
   if(scenario==='unknown-live-socket'){
    server=net.createServer(s=>s.end());await new Promise(r=>server.listen(path.join(root,'control.sock'),r));
   }
   let script=launcher;
   if(scenario==='missing-shared-modules'){script=path.join(dir,'copy.mjs');fs.copyFileSync(launcher,script);}
   if(scenario.endsWith('-shell')){
    script=path.join(dir,'entry');
    let text=fs.readFileSync('/var/lib/secretary-clawbot/desktop/codex-shared-entry','utf8');
    text=text.replace(/^export TASHAN_DESKTOP_SOCKET_ROOT=.*$/m,'export TASHAN_DESKTOP_SOCKET_ROOT='+root);
    fs.writeFileSync(path.join(root,'bridge-state.json'),'{"version":1,"enabled":true}',{mode:0o600});
    if(scenario==='missing-runtime-shell')text=text.replaceAll(node,path.join(dir,'absent-node'));
    else{
     const substitute=path.join(dir,'absent.mjs');
     if(scenario==='syntax-error-launcher-shell')fs.writeFileSync(substitute,'function {');
     text=text.replaceAll(launcher,substitute);
    }
    fs.writeFileSync(script,text,{mode:0o700});
   }
   await fallback(root,script);
   if(scenario.endsWith('-shell'))assert.equal(JSON.parse(fs.readFileSync(path.join(root,'bridge-state.json'),'utf8')).enabled,false);
   if(scenario==='root-is-file')assert.equal(fs.readFileSync(root,'utf8'),'keep');
   if(scenario==='metadata-symlink')assert.ok(fs.lstatSync(path.join(root,'engine.json')).isSymbolicLink());
   if(scenario==='unknown-live-socket')assert.ok(fs.lstatSync(path.join(root,'control.sock')).isSocket());
  }finally{if(server)await new Promise(r=>server.close(r));fs.rmSync(dir,{recursive:true,force:true});}
 });
}
