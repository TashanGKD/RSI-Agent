import {classifyInvocation} from '../../host/desktop/shared-launcher.js';

// CODEX_CLI_PATH is inherited by Computer Use and other helper processes.
// Only the actual Desktop frontend should claim the shared Desktop engine.
export function isDesktopFrontendInvocation(args) {
 const invocation=classifyInvocation(args);
 if(invocation.kind!=='desktop')return false;
 const tail=args.slice(invocation.index+1);
 if(!tail.includes('--analytics-default-enabled'))return false;
 const marker='plugins.codex-app-tools@openai-bundled.mcp_servers.codex_app.enabled=true';
 return tail.some((arg,index)=>
  (['-c','--config'].includes(arg)&&tail[index+1]===marker)||arg===`--config=${marker}`);
}
