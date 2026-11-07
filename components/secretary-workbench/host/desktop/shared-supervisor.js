import fs from 'node:fs/promises';
import net from 'node:net';
import crypto from 'node:crypto';
import { spawn } from 'node:child_process';
import { inspectPath, privateWrite, privateRead, connectable, engineArgs, desktopToolsTarget, validateManagedSocket } from './shared-launcher.js';

// This process has no stdout/stderr log. Private Desktop argv and environment arrive
// only through the inherited IPC channel and are never written to state files.
process.umask(0o077);
let initialized = false;
let stage = 'initialize';
let ready = false;
let stopping = false;
let draining = false;
let engine;
let config;
let metadata;
let ownedMetadata;
let target;
let hasTools;
const ownedSockets = new Map();
const servers = [];
const streams = new Set();
const managementConnections = new Set();

const targetSocket = desktopToolsTarget;
async function listen(server, filename) {
  if (await inspectPath(filename, { missing: true })) throw new Error('Refusing existing supervisor socket');
  servers.push(server);
  server.on('error', () => { if (ready) void shutdown(1); });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(filename, resolve); });
  await fs.chmod(filename, 0o600);
  ownedSockets.set(filename, await fs.lstat(filename));
}
async function removeOwnSocket(filename, original) {
  const current = await fs.lstat(filename).catch(() => null);
  if ((current?.isSocket() || current?.isSymbolicLink()) && current.uid === process.getuid() && current.dev === original.dev && current.ino === original.ino) await fs.unlink(filename).catch(() => {});
}
async function shutdown(code) {
  if (stopping) return;
  stopping = true;
  if (engine && engine.exitCode === null && engine.signalCode === null) {
    const exited = new Promise(resolve => engine.once('exit', resolve));
    engine.kill('SIGTERM');
    if (ready) {
      // Native CLI owns its graceful drain. Never force-kill a ready engine or
      // sever its app-tools relay while it may still be completing a turn.
      await exited;
    } else {
      await Promise.race([exited, new Promise(resolve => setTimeout(resolve, 1500))]);
      if (engine.exitCode === null && engine.signalCode === null) engine.kill('SIGKILL');
    }
  }
  for (const connection of [...streams, ...managementConnections]) connection.destroy();
  for (const server of servers) server.close();
  for (const [filename, original] of ownedSockets) await removeOwnSocket(filename, original);
  if (config && metadata) {
    const filename = `${config.stateDir}/engine.json`;
    const current = await privateRead(filename).catch(() => null);
    const stat = await fs.lstat(filename).catch(() => null);
    if (current?.instance === metadata.instance && current?.fingerprint === metadata.fingerprint && stat?.isFile() && stat.dev === ownedMetadata?.dev && stat.ino === ownedMetadata?.ino && stat.uid === process.getuid()) await fs.unlink(filename).catch(() => {});
  }
  process.exit(code);
}
process.on('SIGTERM', () => void shutdown(0));
process.on('SIGINT', () => void shutdown(0));
process.on('disconnect', () => { if (!ready) void shutdown(1); });

process.once('message', async payload => {
  if (initialized) return;
  initialized = true;
  try {
    config = payload.config;
    target = await targetSocket(payload.target);
    hasTools = Boolean(target);
    const toolsPath = `${config.stateDir}/tools.sock`;
    if (hasTools) {
      stage = 'tools-relay';
      const relay = net.createServer(incoming => {
        if (draining || stopping) { incoming.destroy(); return; }
        streams.add(incoming);
        const currentTarget = target;
        let outgoing;
        const close = () => { streams.delete(incoming); incoming.destroy(); outgoing?.destroy(); };
        incoming.once('close', close); incoming.once('error', close);
        void targetSocket(currentTarget).then(() => {
          if (incoming.destroyed) return;
          outgoing = net.createConnection(currentTarget);
          outgoing.once('error', close); outgoing.once('close', close);
          incoming.pipe(outgoing); outgoing.pipe(incoming);
        }).catch(close);
      });
      await listen(relay, toolsPath);
    }
    stage = 'manager';
    const manager = net.createServer({ allowHalfOpen: true }, connection => {
      managementConnections.add(connection);
      connection.once('close', () => managementConnections.delete(connection));
      connection.on('error', () => {});
      connection.setTimeout(2000, () => connection.destroy());
      let input = ''; let handled = false;
      connection.on('data', chunk => {
        if (handled) return;
        input += chunk;
        if (input.length > 65536) { connection.destroy(); return; }
        if (!input.includes('\n')) return;
        handled = true;
        void (async () => {
          try {
            const request = JSON.parse(input.split('\n')[0]);
            if (!request || typeof request !== 'object' || Array.isArray(request) || !metadata || request.instance !== metadata.instance || request.fingerprint !== metadata.fingerprint) throw new Error('Shared engine identity mismatch');
            const fields = request.action === 'drain' ? ['action', 'instance', 'fingerprint'] : ['action', 'instance', 'fingerprint', 'target'];
            if (!['reuse', 'drain'].includes(request.action) || Object.keys(request).length !== fields.length || !fields.every(key => Object.hasOwn(request, key))) throw new Error('Invalid shared manager request');
            if (draining || stopping || !ready) throw new Error('Shared engine is not ready or already draining');
            if (request.action === 'drain') {
              if (streams.size) throw new Error('Desktop app tools streams have active work; refusing drain');
              draining = true;
              connection.end(`${JSON.stringify({ ok: true, draining: true, instance: metadata.instance })}\n`, () => void shutdown(0));
              return;
            }
            const nextTarget = await targetSocket(request.target);
            if (draining || stopping) throw new Error('Shared engine is already draining');
            if (Boolean(nextTarget) !== hasTools) throw new Error('Desktop app tools environment changed; active engine cannot be replaced');
            if (nextTarget !== target && streams.size) throw new Error('Desktop app tools target changed during active work; refusing reuse');
            target = nextTarget;
            connection.end(`${JSON.stringify({ ok: true })}\n`);
          } catch (error) {
            const safeError = /active work|environment changed|identity mismatch|manager request|already draining/.test(error.message) ? error.message : 'Unsafe Desktop app tools target';
            connection.end(`${JSON.stringify({ ok: false, error: safeError })}\n`);
          }
        })();
      });
    });
    await listen(manager, `${config.stateDir}/manager.sock`);
    const nativeEnv = { ...payload.env };
    if (hasTools) nativeEnv.CODEX_APP_TOOLS_PIPE_PATH = toolsPath;
    stage = 'native-start';
    engine = spawn(config.nativeCommand[0], [...config.nativeCommand.slice(1), ...engineArgs(payload.args, config.socketPath)], { env: nativeEnv, stdio: 'ignore' });
    let exited = false;
    engine.once('error', () => { exited = true; });
    engine.once('exit', () => { exited = true; if (ready) void shutdown(1); });
    const deadline = Date.now() + 8000;
    let socketReady = false;
    while (!exited && Date.now() < deadline) {
      if (await connectable(config.socketPath)) { socketReady = true; break; }
      await new Promise(resolve => setTimeout(resolve, 40));
    }
    if (!socketReady) throw new Error('Native shared engine did not become ready');
    stage = 'native-socket';
    const socket = await validateManagedSocket(config, { allowNewNative: true });
    ownedSockets.set(config.socketPath, socket.stat);
    if (!socket.socketAlias) await fs.chmod(config.socketPath, 0o600);
    metadata = { version: 1, instance: crypto.randomUUID(), supervisorPid: process.pid, enginePid: engine.pid, fingerprint: payload.fingerprint, startedAt: new Date().toISOString(), socketAlias: socket.socketAlias };
    stage = 'metadata';
    await privateWrite(`${config.stateDir}/engine.json`, metadata);
    ownedMetadata = await fs.lstat(`${config.stateDir}/engine.json`);
    ready = true;
    if (process.connected) process.send({ ok: true, metadata });
  } catch {
    if (process.connected) process.send({ ok: false, error: `Shared engine startup refused (${stage}); inspect private configuration and socket state` });
    await shutdown(1);
  }
});
