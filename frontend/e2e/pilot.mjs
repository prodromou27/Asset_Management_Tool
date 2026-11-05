import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import { chromium, expect } from '@playwright/test'
import { createServer } from 'vite'

// Receives ephemeral fixture credentials over stdin. Never accepts a remote target.
let input = ''
for await (const chunk of process.stdin) input += chunk
const fixture = JSON.parse(input)
input = ''
const target = new URL(fixture.api)
assert.equal(target.protocol, 'http:')
assert.ok(['localhost', '127.0.0.1'].includes(target.hostname))
const origin = 'http://127.0.0.1:5198'
const output = 'test-results/pilot'
await fs.mkdir(output, { recursive: true })
await fs.rm(`${output}/report.json`, { force: true })
const server = await createServer({
  logLevel: 'error',
  server: { host: '127.0.0.1', port: 5198, strictPort: true, proxy: { '/api': { target: fixture.api, changeOrigin: true } } },
})
let browser
const errors = []
const cases = []
const started = new Date().toISOString()
const watchdog = setTimeout(() => {
  console.error('Local pilot exceeded its two-minute browser budget.')
  process.exitCode = 1
  void browser?.close()
  void server.close()
}, 120000)

async function context() {
  const session = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' })
  session.setDefaultTimeout(15000)
  await session.route('**/*', (route) => new URL(route.request().url()).origin === origin ? route.continue() : route.abort())
  session.on('page', (page) => page.on('pageerror', (error) => errors.push(error.message)))
  return session
}

async function login(page, username) {
  await page.goto(`${origin}/login?next=/assets`)
  await page.getByLabel('Username', { exact: true }).fill(username)
  await page.getByLabel('Password', { exact: true }).fill(fixture.password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Assets', exact: true })).toBeVisible()
}

async function api(page, path, method = 'GET', body, extra = {}, csrf = true) {
  return page.evaluate(async ({ path, method, body, extra, csrf }) => {
    const headers = { ...extra }
    if (body !== undefined) headers['Content-Type'] = 'application/json'
    if (csrf && method !== 'GET') {
      const cookie = document.cookie.split('; ').find((value) => value.startsWith('itam_csrftoken='))
      if (cookie) headers['X-CSRFToken'] = decodeURIComponent(cookie.split('=')[1])
    }
    const response = await fetch(`/api/v1${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
    const text = await response.text()
    let data
    try { data = JSON.parse(text) } catch { data = null }
    return { status: response.status, data }
  }, { path, method, body, extra, csrf })
}

try {
  await server.listen()
  browser = await chromium.launch({ channel: process.env.ITAM_UI_BROWSER_CHANNEL === 'msedge' || (process.platform === 'win32' && process.env.ITAM_UI_BROWSER_CHANNEL !== 'chromium') ? 'msedge' : undefined })
  const scoped = await context()
  const page = await scoped.newPage()
  await page.goto(`${origin}/login`)
  assert.equal((await api(page, '/assets/')).status, 401)
  assert.equal((await api(page, '/auth/local/login/', 'POST', {}, {}, false)).status, 403)
  cases.push('anonymous_denied', 'login_requires_csrf')
  await login(page, fixture.username)
  assert.equal((await scoped.cookies()).find((cookie) => cookie.name === 'itam_session')?.httpOnly, true)
  const table = page.getByRole('table', { name: 'Assets', exact: true })
  await expect(table.getByRole('link', { name: 'pilot-hq-laptop', exact: true })).toBeVisible()
  await expect(table.getByText('pilot-hidden-remote', { exact: true })).toHaveCount(0)
  await page.screenshot({ path: `${output}/inventory-desktop.png`, fullPage: true })
  await page.getByRole('link', { name: 'Workstations', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Workstations', exact: true })).toBeVisible()
  await expect(table.getByRole('link', { name: 'pilot-hq-laptop', exact: true })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: `${output}/workstations-mobile.png`, fullPage: true })
  await page.setViewportSize({ width: 1440, height: 900 })
  cases.push('real_login_http_only_session', 'site_scoped_inventory', 'root_category_includes_laptop')

  assert.equal((await api(page, `/assets/${fixture.hidden_id}/`)).status, 404)
  assert.equal((await api(page, `/assets/${fixture.hidden_id}/`, 'PATCH', { name: 'forbidden-change' }, { 'If-Match': '"1"' })).status, 404)
  assert.equal((await api(page, `/assets/${fixture.visible_id}/`, 'PATCH', { name: 'csrf-change' }, { 'If-Match': '"1"' }, false)).status, 403)
  assert.equal((await api(page, '/users/')).status, 403)
  cases.push('cross_site_read_denied', 'cross_site_write_denied', 'mutation_requires_csrf', 'admin_api_permission_denied')

  await page.goto(`${origin}/groups/${fixture.group_id}`)
  await expect(page.getByRole('heading', { name: 'Pilot mixed-site group', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'pilot-hq-laptop', exact: true })).toBeVisible()
  await expect(page.getByText('pilot-hidden-remote', { exact: true })).toHaveCount(0)
  cases.push('group_does_not_widen_site_scope')

  await page.goto(`${origin}/assets/new`)
  await page.getByLabel('Name', { exact: true }).fill('pilot-monitor')
  await page.getByLabel('Category', { exact: true }).selectOption(fixture.monitor_category)
  await page.getByLabel('Site', { exact: true }).selectOption(fixture.site_id)
  await page.getByRole('button', { name: 'Register asset', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'pilot-monitor', exact: true })).toBeVisible()
  cases.push('register_non_network_asset_through_ui')
  const report = await api(page, '/reports/lifecycle/')
  assert.equal(report.status, 200)
  assert.equal(report.data.count, 2)
  assert.ok(report.data.rows.every((row) => row.status === 'unknown'))
  assert.ok(!JSON.stringify(report.data).includes('pilot-hidden-remote'))
  await page.goto(`${origin}/reports?report=lifecycle`)
  await expect(page.getByRole('table', { name: 'Report results' })).toContainText('Unknown')
  cases.push('unassessed_lifecycle_stays_unknown')

  await page.goto(`${origin}/assets`)
  await page.getByRole('button', { name: 'Export', exact: true }).click()
  await page.getByLabel('JSON', { exact: true }).check()
  await page.getByRole('button', { name: 'Start export', exact: true }).click()
  const download = page.getByRole('link', { name: /^Download / }).first()
  await expect(download).toBeVisible({ timeout: 20000 })
  const url = new URL(await download.getAttribute('href'), origin)
  assert.equal(url.origin, origin)
  const response = await scoped.request.get(url.href)
  assert.equal(response.status(), 200)
  const exported = await response.json()
  assert.equal(exported.count, 2)
  assert.ok(JSON.stringify(exported).includes('pilot-hq-laptop'))
  assert.ok(JSON.stringify(exported).includes('pilot-monitor'))
  assert.ok(!JSON.stringify(exported).includes('pilot-hidden-remote'))
  cases.push('ui_export_and_authenticated_scoped_download')

  const administrative = await context()
  const admin = await administrative.newPage()
  await login(admin, fixture.admin)
  const user = await api(admin, `/users/${fixture.user_id}/`)
  assert.equal(user.status, 200)
  assert.equal((await api(admin, `/users/${fixture.user_id}/disable/`, 'POST', { reason: 'Synthetic local pilot revocation' }, { 'If-Match': `"${user.data.version}"` })).status, 200)
  assert.equal((await api(page, '/auth/me/')).status, 401)
  await page.goto(`${origin}/assets`)
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible()
  cases.push('disabled_account_revokes_existing_browser_session')
  assert.deepEqual(errors, [])
  const result = { status: 'browser_passed', synthetic: true, database: fixture.database, transport: 'loopback HTTP', tasks: 'eager', started, finished: new Date().toISOString(), cases, limitations: ['No production TLS or AlmaLinux host proof', 'No live sources, SMTP delivery, worker/broker scheduling or scale proof'] }
  await fs.writeFile(`${output}/report.json`, JSON.stringify(result, null, 2))
  console.log(JSON.stringify(result))
} catch (error) {
  console.error(String(error.stack ?? error).replaceAll(fixture.password, '[redacted]'))
  process.exitCode = 1
} finally {
  clearTimeout(watchdog)
  await browser?.close()
  await server.close()
}
