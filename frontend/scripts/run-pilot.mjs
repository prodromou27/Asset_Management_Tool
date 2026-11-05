import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import fs from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const backend = fileURLToPath(new URL('../../backend/', import.meta.url))
const python = process.env.ITAM_PILOT_PYTHON ?? path.join(backend, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
const reportPath = fileURLToPath(new URL('../test-results/pilot/report.json', import.meta.url))
if (!existsSync(python)) throw new Error('Sync backend dependencies first, or set ITAM_PILOT_PYTHON to the Python executable.')
await fs.rm(reportPath, { force: true })
const child = spawn(python, ['-m', 'pytest', '../ops/pilot/test_browser_pilot.py', '-c', 'pyproject.toml', '-q', '-s', '-p', 'no:cacheprovider'], {
  cwd: backend,
  stdio: 'inherit',
  env: { ...process.env, DJANGO_SETTINGS_MODULE: 'config.settings.test', ITAM_RUN_LOCAL_PILOT: '1' },
})
child.on('error', (error) => { console.error(error.message); process.exitCode = 1 })
child.on('close', async (code) => {
  try {
    const report = JSON.parse(await fs.readFile(reportPath, 'utf8'))
    const passed = code === 0 && report.status === 'database_passed'
    report.status = passed ? 'passed' : 'failed'
    report.runner = passed ? 'pytest including teardown passed' : 'pytest or teardown failed'
    await fs.writeFile(reportPath, JSON.stringify(report, null, 2) + '\n')
    if (passed) console.log(`Pilot passed: ${report.cases.length} browser scenarios; database assertions and target guards passed.`)
    process.exitCode = passed ? 0 : 1
  } catch {
    console.error('The pilot did not produce complete evidence.')
    process.exitCode = 1
  }
})
