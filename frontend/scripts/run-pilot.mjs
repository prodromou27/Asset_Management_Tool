import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const backend = fileURLToPath(new URL('../../backend/', import.meta.url))
const python = process.env.ITAM_PILOT_PYTHON ?? path.join(backend, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
if (!existsSync(python)) throw new Error('Sync backend dependencies first, or set ITAM_PILOT_PYTHON to the Python executable.')
const child = spawn(python, ['-m', 'pytest', '../ops/pilot/test_browser_pilot.py', '-c', 'pyproject.toml', '-q', '-s', '-p', 'no:cacheprovider'], {
  cwd: backend,
  stdio: 'inherit',
  env: { ...process.env, DJANGO_SETTINGS_MODULE: 'config.settings.test', ITAM_RUN_LOCAL_PILOT: '1' },
})
child.on('error', (error) => { console.error(error.message); process.exitCode = 1 })
child.on('exit', (code) => { process.exitCode = code ?? 1 })
