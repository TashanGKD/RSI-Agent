import assert from 'node:assert/strict'
import { test } from 'node:test'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { apply, inject } from '../index.js'

function registered(config) {
  let tool
  apply({ tools: { register(value) { tool = value } } }, config)
  return tool
}

test('native contract exposes only a no-argument observation tool', async () => {
  assert.deepEqual(inject, ['tools'])
  const tool = registered()
  assert.equal(tool.name, 'rsi_wechat_status')
  assert.equal(tool.parameters.additionalProperties, false)
  await assert.rejects(tool.execute({ command: 'send' }, { signal: new AbortController().signal }), /no arguments/)
  assert.throws(() => registered({ python: 'python' }), /absolute/)
})

test('fixed argv and cwd reach the reader; subprocess errors stay private', async t => {
  const folder = await mkdtemp(join(tmpdir(), 'rsi-status-plugin-'))
  t.after(() => rm(folder, { recursive: true, force: true }))
  // Node stands in for Python, accepting its fixed -B/-m invocation with a
  // tiny executable fixture. Real Python + DSH acceptance is a separate gate.
  if (process.platform === 'win32') return t.skip('POSIX executable fixture')
  const fake = join(folder, 'reader')
  await writeFile(fake, '#!/usr/bin/env node\n'
    + 'const a=process.argv.slice(2); if(a[0]!=="-B"||a[2]!=="rsi_agent.dsh_status")process.exit(2);'
    + 'console.log(JSON.stringify({schema_version:1,workers:[],scope:"fixture"}));\n', { mode: 0o700 })
  const tool = registered({ python: fake, source: folder })
  const result = await tool.execute({}, { signal: new AbortController().signal })
  assert.equal(result.scope, 'fixture')
  assert.equal(tool.output.render({}, result)[0].text, JSON.stringify(result))
  await writeFile(fake, '#!/usr/bin/env node\nconsole.error("PRIVATE_CANARY");process.exit(2);\n', { mode: 0o700 })
  await assert.rejects(tool.execute({}, { signal: new AbortController().signal }), error =>
    /unavailable/.test(error.message) && !/PRIVATE_CANARY/.test(error.message))
  await writeFile(fake, '#!/usr/bin/env node\nconsole.log("invalid json");\n', { mode: 0o700 })
  await assert.rejects(tool.execute({}, { signal: new AbortController().signal }), /invalid observation/)
})

test('caller cancellation reaches the owned child', async t => {
  if (process.platform === 'win32') return t.skip('POSIX executable fixture')
  const folder = await mkdtemp(join(tmpdir(), 'rsi-status-cancel-'))
  t.after(() => rm(folder, { recursive: true, force: true }))
  const fake = join(folder, 'reader')
  await writeFile(fake, '#!/usr/bin/env node\nsetTimeout(()=>{},30000);\n', { mode: 0o700 })
  const controller = new AbortController()
  const result = registered({ python: fake, source: folder }).execute({}, { signal: controller.signal })
  controller.abort()
  await assert.rejects(result, /cancelled/)
})
