import net from 'node:net';
import fs from 'node:fs';
import WebSocket from 'ws';
import path from 'node:path';
import {validateManagedSocket} from '../../host/desktop/shared-launcher.js';

export class RPC {
  constructor(socketPath){this.path=socketPath;this.next=1;this.pending=new Map();}
  async connect(){
    await validateManagedSocket({socketPath:this.path,stateDir:path.dirname(this.path)});
    const endpoint=fs.realpathSync(this.path);
    // The native server returns normalized image/audio data URLs with queue receipts.
    // Attachments are independently limited to 32MiB before submission.
    this.ws=new WebSocket('ws://localhost/',{createConnection:()=>net.createConnection(endpoint),handshakeTimeout:4000,maxPayload:64*1024*1024,perMessageDeflate:false});
    this.ws.on('message',raw=>{let r;try{r=JSON.parse(raw)}catch{return};const p=this.pending.get(r.id);if(!p)return;this.pending.delete(r.id);clearTimeout(p.timer);r.error?p.reject(Error('native request rejected '+r.error.code)):p.resolve(r.result);});
    this.ws.on('close',()=>{for(const p of this.pending.values()){clearTimeout(p.timer);p.reject(Error('native connection closed'));}this.pending.clear();});
    await new Promise((resolve,reject)=>{this.ws.once('open',resolve);this.ws.once('error',reject)});
    await this.call('initialize',{clientInfo:{name:'tashan_weixin_transport',version:'0.2'},capabilities:{experimentalApi:true}});
    this.ws.send(JSON.stringify({method:'initialized',params:{}}));
  }
  call(method,params){
    const id=this.next++;
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{this.pending.delete(id);reject(Error('native request outcome unknown'));},8000);
      this.pending.set(id,{resolve,reject,timer});
      this.ws.send(JSON.stringify({id,method,params}),err=>{if(err){clearTimeout(timer);this.pending.delete(id);reject(Error('native request outcome unknown'));}});
    });
  }
  close(){this.ws?.terminate();}
}

export const marker=id=>`【微信本人消息 ${id}】`;
export const unpackItems=entries=>entries.map(entry=>entry?.item??entry);
export function finalReply(items){
  return unpackItems(items).filter(i=>i.type==='agentMessage'&&['final_answer','final'].includes(i.phase)&&typeof i.text==='string').map(i=>i.text).join('\n\n');
}
export function matchesInput(items,id){
  return unpackItems(items).some(i=>i.type==='userMessage'&&(i.id===id||(i.content||[]).some(c=>c.type==='text'&&typeof c.text==='string'&&c.text.startsWith(marker(id)+'\n'))));
}
