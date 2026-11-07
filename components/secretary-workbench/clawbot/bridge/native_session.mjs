// Reading a live thread must not repeatedly reconfigure its runtime.
export async function loadedThread(rpc,threadId){
 let result=await rpc.call('thread/read',{threadId,includeTurns:false});
 if(result.thread?.id!==threadId)throw Error('conversation mismatch');
 if(result.thread.status?.type==='notLoaded')result=await rpc.call('thread/resume',{threadId,excludeTurns:true});
 if(result.thread?.id!==threadId||!['active','idle'].includes(result.thread.status?.type))throw Error('native conversation not loaded');
 return result.thread;
}
