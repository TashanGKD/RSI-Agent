import fs from 'node:fs';import net from 'node:net';import readline from 'node:readline';
import WebSocket from 'ws';
if(process.argv[2]!=='--connect'){console.log('Usage: native_ws_proxy.mjs --connect (existing private AUP daemon only)');process.exit(0)}
const home=process.env.SECRETARY_CODEX_HOME;if(!home)throw Error('Configure SECRETARY_CODEX_HOME explicitly');
const link=home+'/app-server-control/app-server-control.sock';const uid=process.getuid();
for(const p of [home,home+'/app-server-control']){const s=fs.statSync(p);if(s.uid!==uid||(s.mode&0o077)!==0)throw Error('untrusted native control directory');}
const endpoint=fs.realpathSync(link);const parent=fs.statSync('/tmp/codex-daemon-'+uid);const socket=fs.statSync(endpoint);
if(!new RegExp('^/tmp/codex-daemon-'+uid+'/[a-f0-9]{64}$').test(endpoint)||parent.uid!==uid||(parent.mode&0o077)!==0||socket.uid!==uid||!socket.isSocket())throw Error('untrusted managed native socket');
const ws=new WebSocket('ws://localhost/',{createConnection:()=>net.createConnection(endpoint),handshakeTimeout:5000,maxPayload:64*1024*1024,perMessageDeflate:false});
const pending=[];let ready=false;const input=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
input.on('line',s=>{if(Buffer.byteLength(s)>16*1024*1024)throw Error('request too large');JSON.parse(s);if(ready)ws.send(s);else{if(pending.length>=20)throw Error('startup input overflow');pending.push(s)}});
ws.on('open',()=>{ready=true;for(const s of pending)ws.send(s);pending.length=0});
ws.on('message',b=>process.stdout.write(b.toString()+'\n'));
ws.on('error',()=>{process.stderr.write('native private transport unavailable\n');process.exitCode=2;input.close();ws.terminate()});
ws.on('close',()=>{input.close();process.exit(0)});input.on('close',()=>ws.close());
