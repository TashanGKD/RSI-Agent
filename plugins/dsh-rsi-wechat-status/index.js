import { execFile } from 'node:child_process'
import { isAbsolute } from 'node:path'

export const name = 'rsi-wechat-status'
export const inject = ['tools']

export function apply(ctx, config = {}) {
  const settings = {
    python: '/usr/bin/python3', source: '/opt/rsi-agent/current',
    ownerConfig: '/var/lib/rsi-agent/owner-replies/config.json',
    groupsConfig: '/var/lib/rsi-agent/groups/config.json',
    release: '/var/lib/rsi-agent/release.json', current: '/opt/rsi-agent/current',
    ...config,
  }
  for (const key of Object.keys(settings)) {
    if (!['python', 'source', 'ownerConfig', 'groupsConfig', 'release', 'current'].includes(key)
        || typeof settings[key] !== 'string' || !isAbsolute(settings[key])) {
      throw new Error('RSI status requires fixed absolute administrator paths.')
    }
  }
  ctx.tools.register({
    name: 'rsi_wechat_status',
    description: 'Read sanitized WeChat worker observations and unresolved original engineering work. '
      + 'This does not send messages, execute tasks, retry work, or prove message delivery. '
      + 'needs_review means inspect the original work; never start a replacement.',
    parameters: { type: 'object', properties: {}, additionalProperties: false },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }],
    },
    async execute(args, exec) {
      if (!args || Array.isArray(args) || typeof args !== 'object' || Object.keys(args).length) {
        throw new Error('rsi_wechat_status accepts no arguments.')
      }
      const argv = ['-B', '-m', 'rsi_agent.dsh_status',
        '--owner-config', settings.ownerConfig, '--groups-config', settings.groupsConfig,
        '--release', settings.release, '--current', settings.current]
      return new Promise((resolve, reject) => {
        let closed = false
        let outcome
        const finish = () => {
          if (!closed || !outcome) return
          const [error, stdout] = outcome
          // Child stderr/errors can contain private paths. Do not forward them.
          if (error) return reject(new Error('RSI status unavailable or cancelled; no action was taken.'))
          try {
            const value = JSON.parse(stdout)
            if (value?.schema_version !== 1 || !Array.isArray(value.workers)) throw new Error()
            resolve(value)
          } catch {
            reject(new Error('RSI status returned an invalid observation.'))
          }
        }
        const child = execFile(settings.python, argv, { cwd: settings.source, shell: false,
          signal: exec.signal, timeout: 12000, maxBuffer: 65536, encoding: 'utf8' },
        (error, stdout) => {
          outcome = [error, stdout]
          finish()
        })
        // Abort emits an error before exit: wait for owned work to stop.
        child.once('close', () => { closed = true; finish() })
      })
    },
  })
}
