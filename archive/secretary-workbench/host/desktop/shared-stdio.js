import net from 'node:net';
import { fileURLToPath } from 'node:url';
import WebSocket from 'ws';
import { readConfig, validateManagedSocket } from './shared-launcher.js';

// JSON lines on stdio; one unchanged line per standard WebSocket message. No RPC
// method interpretation, credential exchange, daemon startup, or retry of input.
export async function bridgeStdio(config, { input = process.stdin, output = process.stdout, maxMessageBytes = 64 * 1024 * 1024, signal, onTraffic } = {}) {
  await validateManagedSocket(config);
  return new Promise(resolve => {
    let finished = false;
    let ended = false;
    let pending = 0;
    let bufferedBytes = 0;
    let pieces = [];
    const highWaterMark = Math.min(maxMessageBytes, 1024 * 1024);
    const socket = new WebSocket('ws://localhost/', {
      createConnection: () => net.createConnection(config.socketPath),
      handshakeTimeout: 5000,
      closeTimeout: 1000,
      maxPayload: maxMessageBytes,
      perMessageDeflate: false,
    });
    const finish = code => {
      if (finished) return;
      finished = true;
      input.pause();
      input.off('data', onData); input.off('end', onEnd); input.off('error', onError);
      output.off('drain', onDrain); output.off('error', onError);
      signal?.removeEventListener('abort', onAbort);
      socket.terminate();
      pieces = [];
      resolve(code);
    };
    const onAbort = () => finish(0);
    const onError = () => finish(1);
    const onDrain = () => { if (!finished) socket.resume(); };
    const maybeClose = () => { if (ended && !pending && !finished) socket.close(1000); };
    const send = bytes => {
      if (bytes.length > maxMessageBytes) return finish(1);
      // Empty separator lines are ignored by the native JSON-lines protocol.
      if (!bytes.length) return;
      pending++;
      socket.send(bytes, { binary: false }, error => {
        pending--;
        if (error) return finish(1);
        if (!finished && !ended && socket.bufferedAmount < highWaterMark) input.resume();
        maybeClose();
      });
      if (socket.bufferedAmount >= highWaterMark) input.pause();
    };
    const onData = chunk => {
      if (finished) return;
      const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      if(bytes.length) onTraffic?.();
      let start = 0;
      for (let end = bytes.indexOf(10, start); end !== -1; end = bytes.indexOf(10, start)) {
        const part = bytes.subarray(start, end);
        bufferedBytes += part.length;
        if (bufferedBytes > maxMessageBytes) return finish(1);
        pieces.push(part);
        const frame = pieces.length === 1 ? pieces[0] : Buffer.concat(pieces, bufferedBytes);
        pieces = []; bufferedBytes = 0;
        send(frame);
        if (finished) return;
        start = end + 1;
      }
      if (start < bytes.length) {
        const part = bytes.subarray(start);
        bufferedBytes += part.length;
        if (bufferedBytes > maxMessageBytes) return finish(1);
        pieces.push(part);
      }
    };
    const onEnd = () => {
      ended = true;
      if (bufferedBytes) return finish(1); // Partial request must never be replayed.
      maybeClose();
    };
    socket.on('error', onError);
    socket.on('open', () => {
      if (signal?.aborted) return finish(0);
      input.on('data', onData); input.once('end', onEnd); input.once('error', onError);
      output.on('drain', onDrain); output.once('error', onError);
      input.resume();
      if (input.readableEnded) onEnd();
    });
    socket.on('message', (data, binary) => {
      if (finished) return;
      if (binary || data.length > maxMessageBytes) return finish(1);
      if(data.length) onTraffic?.();
      if (!output.write(Buffer.concat([data, Buffer.from('\n')]))) socket.pause();
    });
    socket.on('close', () => finish(ended ? 0 : 1));
    signal?.addEventListener('abort', onAbort, { once: true });
    if (signal?.aborted) finish(0);
  });
}

export async function main(args = process.argv.slice(2)) {
  if (args.length !== 2 || args[0] !== '--config') {
    process.stderr.write('Usage: shared-stdio.js --config ABSOLUTE_PRIVATE_CONFIG\n');
    return 1;
  }
  const config = await readConfig(args[1]);
  const controller = new AbortController();
  const stop = () => controller.abort();
  process.once('SIGTERM', stop); process.once('SIGINT', stop);
  try { return await bridgeStdio(config, { signal: controller.signal }); }
  finally { process.off('SIGTERM', stop); process.off('SIGINT', stop); }
}
if (process.argv[1] === fileURLToPath(import.meta.url)) main().then(code => { process.exitCode = code; }).catch(() => {
  process.stderr.write('Shared Desktop connection unavailable; verify the private launcher configuration and managed socket.\n');
  process.exitCode = 1;
});
