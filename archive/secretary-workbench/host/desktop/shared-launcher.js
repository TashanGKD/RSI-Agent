import fs from 'node:fs/promises';
import { constants } from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import net from 'node:net';
import crypto from 'node:crypto';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const uid = process.getuid();
const fail = message => { throw new Error(message); };
export const defaultConfigPath = path.join(os.homedir(), '.codex/mobile-shared-desktop/shared-desktop.json');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

export async function inspectPath(filename, { missing = false, type, privateMode = false, nativeExecutable = false } = {}) {
  if (typeof filename !== 'string' || !path.isAbsolute(filename) || filename.includes('\0') || path.normalize(filename) !== filename) fail('Expected a normalized absolute path');
  const parts = filename.split(path.sep).filter(Boolean);
  let current = path.parse(filename).root;
  for (let index = 0; index < parts.length; index++) {
    current = path.join(current, parts[index]);
    let stat;
    try { stat = await fs.lstat(current); } catch (error) {
      if (missing && error.code === 'ENOENT') return null;
      throw error;
    }
    if (stat.isSymbolicLink()) fail('Refusing symlink path');
    if (stat.uid !== uid && stat.uid !== 0) fail('Refusing foreign-owned path');
    if (index < parts.length - 1 && !stat.isDirectory()) fail('Path ancestor is not a directory');
    const macApplications = nativeExecutable && process.platform === 'darwin' && current === '/Applications' && stat.uid === 0 && stat.gid === 80 && !(stat.mode & 0o002);
    if (index < parts.length - 1 && (stat.mode & 0o022) && !(stat.uid === 0 && (stat.mode & 0o1000)) && !macApplications) fail('Unsafe writable path ancestor');
    if (index === parts.length - 1) {
      if (stat.uid !== uid && privateMode) fail('Private path must belong to current account');
      if (privateMode && (stat.mode & 0o077)) fail('Private path permissions required');
      if (type === 'file' && !stat.isFile()) fail('Expected regular file');
      if (type === 'directory' && !stat.isDirectory()) fail('Expected directory');
      if (type === 'socket' && !stat.isSocket()) fail('Expected Unix socket');
      return stat;
    }
  }
  fail('Root path is not allowed');
}

export async function privateRead(filename) {
  await inspectPath(filename, { type: 'file', privateMode: true });
  const handle = await fs.open(filename, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const stat = await handle.stat();
    if (!stat.isFile() || stat.uid !== uid || (stat.mode & 0o077) || stat.size > 65536) fail('Unsafe private file');
    return JSON.parse(await handle.readFile('utf8'));
  } finally { await handle.close(); }
}

export async function privateWrite(filename, value) {
  await inspectPath(filename, { type: 'file', privateMode: true, missing: true });
  await inspectPath(path.dirname(filename), { type: 'directory', privateMode: true });
  const temp = `${filename}.${crypto.randomUUID()}.tmp`;
  const handle = await fs.open(temp, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
  try { await handle.writeFile(JSON.stringify(value)); await handle.sync(); }
  finally { await handle.close(); }
  try { await fs.rename(temp, filename); } finally { await fs.unlink(temp).catch(() => {}); }
}

export async function privateDirectory(dirname) {
  const existing = await inspectPath(dirname, { type: 'directory', privateMode: true, missing: true });
  if (!existing) {
    const parent = path.dirname(dirname);
    await inspectPath(parent, { type: 'directory' });
    await fs.mkdir(dirname, { mode: 0o700 }).catch(error => { if (error.code !== 'EEXIST') throw error; });
    await inspectPath(dirname, { type: 'directory', privateMode: true });
  }
}

export async function readConfig(filename = defaultConfigPath) {
  const config = await privateRead(filename);
  if (!Array.isArray(config.nativeCommand) || !config.nativeCommand.length || config.nativeCommand.some(arg => typeof arg !== 'string' || !arg || arg.includes('\0'))) fail('nativeCommand must be a nonempty executable argument array');
  const executableStat = await inspectPath(config.nativeCommand[0], { type: 'file', nativeExecutable: true });
  if (!(executableStat.mode & 0o111) || (executableStat.mode & 0o022)) fail('Native executable permissions are unsafe');
  for (const name of ['stateDir', 'socketPath']) if (typeof config[name] !== 'string' || !path.isAbsolute(config[name]) || config[name].includes('\0') || path.normalize(config[name]) !== config[name]) fail('Invalid private path');
  if (Buffer.byteLength(config.socketPath) > 100 || Buffer.byteLength(path.join(config.stateDir, 'tools.sock')) > 100) fail('Unix socket path is too long');
  await inspectPath(config.stateDir, { type: 'directory', privateMode: true, missing: true });
  await inspectPath(path.dirname(config.socketPath), { type: 'directory', privateMode: true, missing: true });
  await validateManagedSocket(config, { missing: true });
  return { nativeCommand: config.nativeCommand, stateDir: config.stateDir, socketPath: config.socketPath };
}

// Read-only validation shared with the mobile attach-only client. Native CLI
// publishes a control symlink; only our private pinned alias may be followed.
export async function validateManagedSocket(config, { missing = false, allowNewNative = false } = {}) {
  await inspectPath(path.dirname(config.socketPath), { type: 'directory', privateMode: true, missing });
  let stat;
  try { stat = await fs.lstat(config.socketPath); } catch (error) {
    if (missing && error.code === 'ENOENT') return null;
    throw error;
  }
  if (!stat.isSymbolicLink()) {
    const socket = await inspectPath(config.socketPath, { type: 'socket', privateMode: true });
    return { stat: socket, socketAlias: null };
  }
  if (stat.uid !== uid) fail('Refusing foreign symlink socket');
  let pin;
  if (!allowNewNative) {
    const metadata = await privateRead(path.join(config.stateDir, 'engine.json')).catch(error => { if (error.code === 'ENOENT') fail('Refusing unmanaged symlink socket'); throw error; });
    pin = metadata.socketAlias;
    if (!pin || pin.dev !== stat.dev || pin.ino !== stat.ino || pin.ctimeMs !== stat.ctimeMs) fail('Refusing unpinned symlink socket');
  }
  const target = await fs.readlink(config.socketPath);
  const expected = new RegExp(`^/(?:private/)?tmp/codex-daemon-${uid}/[0-9a-f]{64}$`);
  if (!expected.test(target)) fail('Refusing symlink outside native private socket namespace');
  const canonicalTarget = await desktopToolsTarget(target);
  await inspectPath(path.dirname(canonicalTarget), { type: 'directory', privateMode: true });
  await inspectPath(canonicalTarget, { type: 'socket', privateMode: true });
  const targetFingerprint = crypto.createHash('sha256').update(canonicalTarget).digest('hex');
  if (pin && pin.targetFingerprint !== targetFingerprint) fail('Native socket alias target changed');
  return { stat, socketAlias: { dev: stat.dev, ino: stat.ino, ctimeMs: stat.ctimeMs, targetFingerprint } };
}

export function classifyInvocation(args) {
  // Skip only the native global options which can carry an app-server string as a value.
  let index = 0;
  while (index < args.length) {
    if (['-c', '--config', '--enable', '--disable', '-C', '--cd'].includes(args[index])) { index += 2; continue; }
    if (/^(--config|--enable|--disable|--cd)=/.test(args[index])) { index++; continue; }
    break;
  }
  if (args[index] !== 'app-server') return { kind: 'passthrough' };
  const tail = args.slice(index + 1);
  if (tail.some(arg => ['proxy', 'daemon', 'help', '--help', '-h', '--version', '-V', 'generate-ts', 'generate-json-schema'].includes(arg))) return { kind: 'passthrough' };
  for (let i = 0; i < tail.length; i++) {
    if (tail[i] === '--listen' && tail[i + 1] !== 'stdio://') return { kind: 'passthrough' };
    if (tail[i].startsWith('--listen=') && tail[i] !== '--listen=stdio://') return { kind: 'passthrough' };
  }
  return { kind: 'desktop', index };
}

export function engineArgs(args, socketPath) {
  const result = [];
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--stdio') continue;
    if (args[i] === '--listen') { i++; continue; }
    if (args[i].startsWith('--listen=')) continue;
    result.push(args[i]);
  }
  return [...result, '--listen', `unix://${socketPath}`];
}

export async function fingerprint(config, args, env) {
  const stat = await fs.stat(config.nativeCommand[0]);
  const relevantEnv = Object.fromEntries(Object.entries(env).filter(([key]) => key !== 'CODEX_APP_TOOLS_PIPE_PATH').sort(([a], [b]) => a.localeCompare(b)));
  return crypto.createHash('sha256').update(JSON.stringify({ nativeCommand: config.nativeCommand, stateDir: config.stateDir, socketPath: config.socketPath, binary: [stat.dev, stat.ino, stat.size, stat.mtimeMs], args, env: relevantEnv })).digest('hex');
}

export async function desktopToolsTarget(filename) {
  if (!filename) return null;
  if (typeof filename !== 'string' || !path.isAbsolute(filename) || filename.includes('\0') || path.normalize(filename) !== filename) fail('Invalid Desktop app tools path');
  // macOS publishes temporary paths through these two OS-owned aliases. No
  // user-owned symlink, including the final socket, is followed.
  for (const prefix of ['/tmp', '/var']) {
    if (!filename.startsWith(`${prefix}/`)) continue;
    const stat = await fs.lstat(prefix);
    if (stat.isSymbolicLink()) {
      const destination = path.resolve('/', await fs.readlink(prefix));
      if (stat.uid !== 0 || destination !== `/private${prefix}`) fail('Unsafe system path alias');
      filename = `/private${filename}`;
    }
  }
  const stat = await inspectPath(filename, { type: 'socket' });
  if (stat.uid !== uid || (stat.mode & 0o022)) fail('Desktop app tools socket ownership or permissions are unsafe');
  return filename;
}

export async function connectable(socketPath) {
  return new Promise(resolve => {
    const connection = net.createConnection(socketPath);
    const finish = result => { connection.destroy(); resolve(result); };
    connection.once('connect', () => finish(true));
    connection.once('error', () => finish(false));
    connection.setTimeout(300, () => finish(false));
  });
}

export async function managerRequest(socketPath, request) {
  await inspectPath(socketPath, { type: 'socket', privateMode: true });
  return new Promise((resolve, reject) => {
    let data = '';
    const connection = net.createConnection(socketPath);
    const finish = (error, result) => { connection.destroy(); error ? reject(error) : resolve(result); };
    connection.once('connect', () => connection.end(`${JSON.stringify(request)}\n`));
    connection.on('data', chunk => {
      data += chunk;
      if (data.length > 65536) return finish(new Error('Invalid supervisor response'));
      if (data.includes('\n')) {
        try { const result = JSON.parse(data.split('\n')[0]); result.ok ? finish(null, result) : finish(new Error(result.error || 'Supervisor refused connection')); }
        catch (error) { finish(error); }
      }
    });
    connection.once('error', () => finish(new Error('Shared supervisor is unavailable')));
    connection.once('end', () => { if (!data.includes('\n')) finish(new Error('Invalid supervisor response')); });
    connection.setTimeout(2000, () => finish(new Error('Shared supervisor timeout')));
  });
}

// This is an internal manager path, deliberately absent from the launcher's CLI.
// Its caller must independently hold the mobile preparation gate and verify
// Desktop has exited after explicit UI task confirmation. Identity comes only
// from pinned private metadata, never from a browser or a PID lookup.
export async function drainSharedEngine(configPath, { checkSafety, timeoutMs = 45000 } = {}) {
  if (typeof checkSafety !== 'function' || !Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 45000 || await checkSafety() !== true) fail('Shared drain safety gate requires explicit idle confirmation');
  const config = await readConfig(configPath);
  const metadataPath = path.join(config.stateDir, 'engine.json');
  let metadata;
  try { metadata = await privateRead(metadataPath); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  const managerPath = path.join(config.stateDir, 'manager.sock');
  const toolsPath = path.join(config.stateDir, 'tools.sock');
  if (!metadata) {
    const paths = await Promise.all([config.socketPath, managerPath, toolsPath].map(filename => inspectPath(filename, { missing: true })));
    if (paths.some(Boolean)) fail('Shared drain refuses sockets without owned metadata');
    return { drained: false, absent: true };
  }
  if (metadata.version !== 1 || typeof metadata.instance !== 'string' || !/^[0-9a-f-]{36}$/i.test(metadata.instance) || typeof metadata.fingerprint !== 'string' || !/^[0-9a-f]{64}$/.test(metadata.fingerprint)) fail('Shared drain identity metadata is invalid');
  const socket = await validateManagedSocket(config);
  const originals = new Map([[config.socketPath, socket.stat]]);
  for (const filename of [managerPath, toolsPath]) {
    const stat = await inspectPath(filename, { type: 'socket', privateMode: true, missing: filename === toolsPath });
    if (stat) originals.set(filename, stat);
  }
  const originalMetadata = await inspectPath(metadataPath, { type: 'file', privateMode: true });
  if (await checkSafety() !== true) fail('Shared drain safety gate is no longer held');
  const response = await managerRequest(managerPath, { action: 'drain', instance: metadata.instance, fingerprint: metadata.fingerprint });
  if (response.draining !== true || response.instance !== metadata.instance) fail('Shared drain identity acknowledgement is invalid');
  const deadline = Date.now() + timeoutMs;
  while (true) {
    let current;
    try {
      current = await privateRead(metadataPath);
      const stat = await inspectPath(metadataPath, { type: 'file', privateMode: true });
      if (current.instance !== metadata.instance || current.fingerprint !== metadata.fingerprint || stat.dev !== originalMetadata.dev || stat.ino !== originalMetadata.ino) fail('Shared drain metadata identity changed');
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
    let remaining = false;
    for (const [filename, original] of originals) {
      let stat;
      try { stat = await fs.lstat(filename); } catch (error) { if (error.code === 'ENOENT') continue; throw error; }
      if (stat.dev !== original.dev || stat.ino !== original.ino || stat.uid !== original.uid || (!stat.isSocket() && !stat.isSymbolicLink())) fail('Shared drain socket identity changed');
      remaining = true;
    }
    if (!current && !remaining) return { drained: true };
    if (Date.now() >= deadline) fail('Shared drain cleanup timed out; outcome is unknown');
    await sleep(Math.min(100, Math.max(1, deadline - Date.now())));
  }
}

export async function ensureSharedEngine(config, args, env = process.env, { timeoutMs = 10000 } = {}) {
  if (classifyInvocation(args).kind !== 'desktop') fail('Only explicit Desktop app-server startup may start the shared engine');
  const target = await desktopToolsTarget(env.CODEX_APP_TOOLS_PIPE_PATH);
  await privateDirectory(config.stateDir);
  await privateDirectory(path.dirname(config.socketPath));
  const lockPath = path.join(config.stateDir, 'startup.lock');
  const deadline = Date.now() + timeoutMs;
  let acquired = false;
  while (Date.now() < deadline) {
    try { await fs.mkdir(lockPath, { mode: 0o700 }); acquired = true; break; }
    catch (error) {
      if (error.code !== 'EEXIST') throw error;
      await inspectPath(lockPath, { type: 'directory', privateMode: true, missing: true });
      await sleep(40);
    }
  }
  if (!acquired) fail('Shared startup is busy; stale startup locks require manual review');
  try {
    const identity = await fingerprint(config, args, env);
    const metadataPath = path.join(config.stateDir, 'engine.json');
    const managerPath = path.join(config.stateDir, 'manager.sock');
    let metadata;
    try { metadata = await privateRead(metadataPath); } catch (error) { if (error.code !== 'ENOENT') throw error; }
    const socket = await validateManagedSocket(config, { missing: true });
    if (metadata) {
      if (!socket || !(await connectable(config.socketPath))) fail('Existing shared engine is unavailable; manual recovery required');
      if (metadata.fingerprint !== identity) fail('Desktop tool or CLI environment changed; refusing to replace the active shared engine');
      await managerRequest(managerPath, { action: 'reuse', instance: metadata.instance, fingerprint: identity, target });
      return metadata;
    }
    if (socket) fail('Refusing an existing unmanaged socket');
    await inspectPath(managerPath, { type: 'socket', privateMode: true, missing: true }).then(stat => { if (stat) fail('Refusing an existing unmanaged supervisor socket'); });
    const supervisor = spawn(process.execPath, [fileURLToPath(new URL('./shared-supervisor.js', import.meta.url))], { detached: true, stdio: ['ignore', 'ignore', 'ignore', 'ipc'], env: {} });
    supervisor.unref();
    const result = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => { supervisor.disconnect(); reject(new Error('Shared engine startup timed out; inspect private state before retrying')); }, timeoutMs);
      supervisor.once('message', message => {
        clearTimeout(timer);
        if (supervisor.connected) supervisor.disconnect();
        message.ok ? resolve(message.metadata) : reject(new Error(message.error || 'Shared engine failed to start'));
      });
      supervisor.once('error', () => { clearTimeout(timer); reject(new Error('Cannot start shared supervisor')); });
      supervisor.once('exit', () => { clearTimeout(timer); reject(new Error('Shared supervisor exited during startup')); });
      supervisor.send({ config, args, env, fingerprint: identity, target });
    });
    supervisor.unref();
    return result;
  } finally { await fs.rmdir(lockPath); }
}

export async function main(args = process.argv.slice(2), env = process.env) {
  if (!args.length) { process.stderr.write('Desktop shared CLI launcher: pass native CLI arguments; explicit Desktop app-server startup requires private configuration.\n'); return 0; }
  const config = await readConfig(env.TASHAN_DESKTOP_SHARED_CONFIG || defaultConfigPath);
  const shared = classifyInvocation(args).kind === 'desktop';
  if (shared) {
    await ensureSharedEngine(config, args, env);
    const { bridgeStdio } = await import('./shared-stdio.js');
    const controller = new AbortController();
    const stop = () => controller.abort();
    process.once('SIGTERM', stop); process.once('SIGINT', stop);
    try { return await bridgeStdio(config, { signal: controller.signal }); }
    finally { process.off('SIGTERM', stop); process.off('SIGINT', stop); }
  }
  const childArgs = args;
  const child = spawn(config.nativeCommand[0], [...config.nativeCommand.slice(1), ...childArgs], { env, stdio: 'inherit' });
  const forward = signal => { if (!child.killed) child.kill(signal); };
  const term = () => forward('SIGTERM'); const interrupt = () => forward('SIGINT');
  process.on('SIGTERM', term); process.on('SIGINT', interrupt);
  return new Promise(resolve => {
    child.once('error', () => resolve(1));
    child.once('exit', (code, signal) => { process.off('SIGTERM', term); process.off('SIGINT', interrupt); resolve(code ?? (signal === 'SIGINT' ? 130 : 1)); });
  });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main().then(code => { process.exitCode = code; }).catch(() => {
  // Avoid printing argv, env, native diagnostics, file contents, or sensitive paths.
  process.stderr.write('Desktop shared launcher refused startup. Verify the private configuration, ownership, permissions, socket state, and unchanged Desktop tools environment. Existing shared work has not been replaced.\n');
  process.exitCode = 1;
});
