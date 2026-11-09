import test from 'node:test';
import assert from 'node:assert/strict';

const implementation=await import('../bridge/desktop_invocation.mjs').catch(()=>({}));
const classify=args=>{
  assert.equal(typeof implementation.isDesktopFrontendInvocation,'function','desktop frontend discriminator exists');
  return implementation.isDesktopFrontendInvocation(args);
};
const marker='plugins.codex-app-tools@openai-bundled.mcp_servers.codex_app.enabled=true';

// Only the observed Desktop frontend may claim its shared engine/socket.
// Breaking inputs: bare helper stdio app-server, marker hidden inside a config
// value, or a disabled marker must never claim/replace the Desktop engine.
test('computer-use helper app-server passes through untouched',()=>{
  assert.equal(classify(['app-server','--listen','stdio://']),false);
  assert.equal(classify(['app-server']),false);
});
test('a marker embedded in an unrelated setting is not a Desktop launch',()=>{
  assert.equal(classify(['app-server','--analytics-default-enabled','-c',`note="${marker}"`]),false);
});
test('missing or disabled Desktop marker does not claim shared state',()=>{
  assert.equal(classify(['app-server','--analytics-default-enabled']),false);
  assert.equal(classify(['app-server','--analytics-default-enabled','-c',marker.replace('=true','=false')]),false);
});
test('the observed Desktop frontend still starts through the shared adapter',()=>{
  assert.equal(classify(['-c','features.code_mode_host=true','app-server','--analytics-default-enabled','-c',marker]),true);
});
test('help, explicit other transports, and no arguments stay safe',()=>{
  assert.equal(classify([]),false);
  assert.equal(classify(['app-server','--help','--analytics-default-enabled','-c',marker]),false);
  assert.equal(classify(['app-server','--listen','unix:///private/tmp/other.sock','--analytics-default-enabled','-c',marker]),false);
});
