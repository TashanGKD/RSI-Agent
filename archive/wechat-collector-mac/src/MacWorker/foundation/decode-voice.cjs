const fs=require('fs');
const silk=require('silk-wasm');
(async()=>{
  const input=fs.readFileSync(process.argv[2]);
  if(input.length>16*1024*1024)throw Error('too large');
  const decoded=await silk.decode(input,24000);
  const pcm=Buffer.from(decoded.data);
  if(!pcm.length||pcm.length>64*1024*1024)throw Error('invalid audio');
  const h=Buffer.alloc(44);
  h.write('RIFF');h.writeUInt32LE(36+pcm.length,4);h.write('WAVE',8);h.write('fmt ',12);h.writeUInt32LE(16,16);h.writeUInt16LE(1,20);h.writeUInt16LE(1,22);h.writeUInt32LE(24000,24);h.writeUInt32LE(48000,28);h.writeUInt16LE(2,32);h.writeUInt16LE(16,34);h.write('data',36);h.writeUInt32LE(pcm.length,40);
  fs.writeFileSync(process.argv[3],Buffer.concat([h,pcm]),{mode:0o600});
})().catch(()=>{process.stderr.write('SILK decode failed\n');process.exitCode=1});
