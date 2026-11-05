import { createServer } from 'vite'
import { chromium } from '@playwright/test'
import fs from 'node:fs/promises'

// Synthetic API responses only. No backend, vendor connector or SMTP service is contacted.
const output = 'test-results/task021-review'
await fs.mkdir(output, { recursive: true })
let screenshots = 0
const capture = async (page, name, fullPage = true) => {
  await page.screenshot({ path: `${output}/${name}.png`, fullPage })
  screenshots++
}

const source = await fs.readFile('src/test/api.tsx', 'utf8')
const permissions = JSON.parse(source.match(/const ALL_ADMIN = (\[[\s\S]*?\])/)[1].replaceAll("'", '"').replace(/,\s*]/, ']'))
const me = { id: 'fixture-admin', username: 'fixture.admin', display_name: 'Fixture Admin', email: '', roles: [{ code: 'system_admin', name: 'System Admin' }], permissions, all_sites: true, must_change_password: false }
const policy = { enabled: false, hour_utc: 2, rpo_hours: 24, rto_hours: 4, keep_daily: 30, keep_weekly: 8, keep_monthly: 12, retention_enabled: false, version: 1, modified_at: '2026-11-05T00:00:00Z' }
const general = { organization_name: 'ITAM', timezone: 'Asia/Nicosia', date_format: 'day_month_year', language: 'en', support_contact: '', version: 1, modified_at: '2026-11-05T00:00:00Z', modified_by: null }
me.display_preferences = { ...general }
const site = { id: 'site', code: 'HQ', name: 'Headquarters', is_active: true, parent: null }
const category = { id: 'switch', code: 'switch', name: 'Switch', path: 'Networking / Switch', parent: null, depth: 0, is_active: true }
const assets = Array.from({ length: 28 }, (_, i) => ({
  id: `asset-${i}`, name: `sw-floor-${String(i + 1).padStart(2, '0')}`, asset_tag: `IT-${1000 + i}`,
  category, manufacturer: 'Fixture Networks', model: 'Fixture 48', serial_number: `TEST-SERIAL-${i}`,
  primary_hostname: `sw-floor-${i + 1}.example.invalid`, primary_ip: `192.0.2.${i + 1}`,
  site, location: null, owner: null, business_status: 'deployed', observation_status: 'manual_only',
  support_status: 'unknown', is_archived: false, last_seen_at: null, source_count: 0,
  modified_at: '2026-11-05T00:00:00Z', version: 1,
}))
const pageData = (items) => ({ items, next_cursor: null, previous_cursor: null, count: items.length })
const fixtureSource = { code: 'fixture', name: 'Sanitized fixture import', kind: 'import', availability: 'available', description: 'Synthetic review source', instance_count: 1, has_adapter: false, required_permissions: [] }
const fixtureIntegration = {
  id: 'fixture-integration', source: fixtureSource,
  name: 'Fixture inventory connection with a deliberately long display name',
  status: 'available', is_enabled: false, default_site: site, default_vrf: '',
  freshness: 'never', last_success_at: null, has_adapter: false,
  active_links: 0, stale_links: 0, open_candidates: 0,
}
const routes = {
  '/groups/': [],
  '/reports/schedules/': [],
  '/settings/general/': general,
  '/health/operations/': { checked_at: '2026-11-05T12:00:00Z', production_readiness: 'incomplete', components: [
    { id: 'database', label: 'Database', status: 'up', detail: 'Reachable.', href: '/' },
    { id: 'redis', label: 'Redis', status: 'up', detail: 'Reachable.', href: '/' },
    { id: 'scratch', label: 'Application scratch storage', status: 'up', detail: 'Synthetic capacity fixture; database/off-host storage not measured.', href: '/' },
    { id: 'workers', label: 'Workers and scheduler', status: 'unknown', detail: 'No worker heartbeat available; queue depth does not establish worker health.', href: '/' },
    { id: 'backups', label: 'Encrypted backup jobs', status: 'disabled', detail: 'No verified recovery point recorded.', href: '/admin/backups' },
  ], integrations: [{ id: 'fixture', label: 'Synthetic disabled source', status: 'disabled', detail: 'Disabled; no successful sync implied.', href: '/admin/integrations/fixture' }], queues: ['Imports', 'Exports', 'Backups'].map((name) => ({ name, queued: 0, running: 0, failed: 0, worker_status: 'unknown' })), checklist: [
    { id: 'https', label: 'Trusted HTTPS and secure cookies', status: 'unknown', detail: 'Verify the deployed certificate and cookies on the target host.', href: '/admin/security' },
    { id: 'recovery', label: 'Off-host backup and restore rehearsal', status: 'needs_attention', detail: 'Approve destination, key custody and timed staging recovery.', href: '/admin/backups' },
  ] },
  '/auth/me/': me, '/backups/policy/': policy, '/backups/jobs/': [], '/backups/drills/': [],
  '/backups/summary/': { execution_allowed: false, target_label: 'Not configured', encryption: 'Restic authenticated encryption; key custody approval required', off_host: 'SFTP repository required; validate physical separation at commissioning', last_backup: null, last_drill: null, problems: ['Setup incomplete: deployment approval and repository/key provisioning needed (DEC-09).', 'Nightly backups are disabled.', 'No verified backup recorded.', 'No isolated restore drill recorded.'] },
  '/assets/': pageData(assets), '/asset-categories/': [category], '/sites/': [site], '/saved-views/': [],
  '/integrations/': [fixtureIntegration], '/health/ready/': { status: 'ok', dependencies: { database: { status: 'up', detail: '' }, redis: { status: 'up', detail: '' } } },
  '/locations/': [], '/departments/': [], '/domains/': pageData([]),
  '/certificates/': pageData([]), '/tls-endpoints/': pageData([]),
  '/software/products/': pageData([]), '/software/installations/': pageData([]),
  '/discovery/candidates/': pageData([]), '/discovery/sources/': [fixtureSource, { ...fixtureSource, code: 'librenms', name: 'LibreNMS', kind: 'network', availability: 'beta', has_adapter: true, description: 'Read-only network inventory; fixture tested.' }, { ...fixtureSource, code: 'future', name: 'Future provider', availability: 'planned', instance_count: 0, description: 'No adapter implemented.' }],
  '/integrations/fixture-integration/runs/': pageData([]),
  '/discovery/field-authority/': { precedence: {}, version: 1, modified_at: '2026-11-05T00:00:00Z', modified_by: null },
  '/lifecycle/summary/': [], '/lifecycle/findings/': pageData([]),
  '/lifecycle/policy/': { warning_days: [180, 90], count_extended_support: false, max_exception_days: 365, today: '2026-11-05' },
  '/settings/security/': { session_idle_timeout_minutes: 30, session_absolute_timeout_hours: 12, lockout_threshold: 5, lockout_duration_minutes: 15, password_min_length: 12, version: 1, modified_by: null, modified_at: '2026-11-05T00:00:00Z' },
  '/settings/smtp/': { enabled: false, host: '', port: 587, security: 'starttls', username: '', password_ref: '', password_status: 'not_set', ca_bundle_ref: '', from_address: '', from_name: 'ITAM', reply_to: '', timeout_seconds: 15, max_per_minute: 60, last_test_at: null, last_test_ok: null, last_test_error: '', last_test_email_at: null, version: 1, modified_by: null, modified_at: '2026-11-05T00:00:00Z' },
  '/notifications/outbox/stats/': { counts: { queued: 0, sending: 0, retrying: 0, sent: 0, dead: 0, cancelled: 0, expired: 0 }, oldest_waiting_at: null, dead_last_24h: 0, problems: [], enabled: false, configured: false },
  '/asset-categories/switch/fields/': [],
  '/assets/asset-0/': { ...assets[0], os_name: 'Fixture OS', os_version: '1.0', firmware_version: '', department: null, notes: 'Synthetic visual-review fixture', custom_fields: {}, missing_required_fields: [], retained_custom_fields: [], hostnames: [], interfaces: [], ip_addresses: [], archived_at: null, archived_by: null, archive_reason: '', created_at: '2026-11-05T00:00:00Z', created_by: 'fixture.admin', modified_by: 'fixture.admin' },
}
for (const kind of ['inventory', 'lifecycle', 'coverage', 'groups']) {
  const columns = kind === 'inventory' ? [{ key: 'label', label: 'Breakdown' }, { key: 'total', label: 'Assets' }]
    : [{ key: 'name', label: kind === 'groups' ? 'Group' : 'Asset' }, { key: 'site', label: 'Site' }, { key: 'status', label: kind === 'coverage' ? 'Recorded source state' : 'Status' }]
  routes[`/reports/${kind}/`] = { report: kind, label: `${kind} report`, note: 'Synthetic report fixture. Current site and field permissions apply; no compliance or agent absence is inferred.', generated_at: '2026-11-05T12:00:00Z', count: 2, columns, rows: kind === 'inventory' ? [{ label: 'Headquarters', total: 28 }, { label: 'Remote office', total: 12 }] : [{ id: 'asset-0', name: 'Synthetic report asset', site: 'HQ', status: kind === 'coverage' ? 'Not reported' : 'unknown' }, { id: 'asset-1', name: 'Synthetic second record', site: 'HQ', status: kind === 'coverage' ? 'Reported (active link)' : 'eos' }], offset: 0, limit: 50 }
}
const reportFixture = (kind, fields, rows) => Object.assign(routes[`/reports/${kind}/`], { columns: fields.map(([key, label]) => ({ key, label })), rows })
reportFixture('inventory', [['label', 'Breakdown'], ['total', 'Assets'], ['model_unknown', 'Model unknown'], ['not_observed', 'No source link']], [{ label: 'Headquarters', total: 28, model_unknown: 4, not_observed: 3 }, { label: 'Remote office', total: 12, model_unknown: 1, not_observed: 2 }])
reportFixture('lifecycle', [['name', 'Asset'], ['site', 'Site'], ['dimension', 'Dimension'], ['status', 'Effective status'], ['base_status', 'Evidence status'], ['milestone', 'Milestone'], ['date', 'Milestone date'], ['quality', 'Evidence quality'], ['assessed_at', 'Assessed at']], [{ id: 'asset-0', name: 'Synthetic unassessed asset', site: 'HQ', dimension: 'hardware', status: 'unknown', base_status: 'unknown', milestone: '', date: '', quality: '', assessed_at: '' }, { id: 'asset-1', name: 'Synthetic EOS record', site: 'HQ', dimension: 'hardware', status: 'eos', base_status: 'eos', milestone: 'end_of_support', date: '2026-10-01', quality: 'manual', assessed_at: '2026-11-05T00:00:00Z' }])
reportFixture('coverage', [['name', 'Asset'], ['site', 'Site'], ['category', 'Category'], ['endpoint_central', 'Endpoint Central link'], ['defender', 'Defender link']], [{ id: 'asset-0', name: 'Synthetic report asset', site: 'HQ', category: 'Switch', endpoint_central: 'Not reported', defender: 'Not reported' }, { id: 'asset-1', name: 'Synthetic endpoint', site: 'HQ', category: 'Laptop', endpoint_central: 'Reported (active link)', defender: 'Stale or disabled link' }])
reportFixture('groups', [['name', 'Group'], ['kind', 'Kind'], ['members', 'Visible members'], ['eos', 'Verified EOS assets'], ['owner_missing', 'Assets without owner'], ['owner', 'Group owner']], [{ id: 'group-0', name: 'Synthetic replacement group', kind: 'static', members: 2, eos: 1, owner_missing: 1, owner: 'Fixture Admin' }, { id: 'group-1', name: 'Synthetic empty group', kind: 'dynamic', members: 0, eos: 0, owner_missing: 0, owner: '' }])
routes['/exports/families/'] = ['inventory', 'lifecycle', 'coverage', 'groups'].map((kind) => ({ code: `report_${kind}`, label: `${kind} report`, description: 'Scoped synthetic report export', allowed: true, filter_keys: ['site', 'group', 'q', 'breakdown', 'dimension', 'status', 'coverage'], columns: routes[`/reports/${kind}/`].columns.map((column) => ({ ...column, personal: false, allowed: true })), related: [], personal_data_allowed: false }))
const server = await createServer({ server: { host: '127.0.0.1', port: 5197, strictPort: true } })
await server.listen()
const browser = await chromium.launch({ channel: process.env.ITAM_UI_BROWSER_CHANNEL === 'chromium' ? undefined : 'msedge', headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' })
  const errors = []
  const unmapped = new Set()
  const responses = new Map()
  page.on('pageerror', (error) => errors.push(error.message))
  await page.route('**/api/v1/**', async (route) => {
    const key = new URL(route.request().url()).pathname.replace('/api/v1', '')
    if (key === '/reports/schedules/' && route.request().method() === 'POST') {
      const schedule = { ...route.request().postDataJSON(), id: 'fixture-schedule', version: 1, created_at: '2026-11-05T00:00:00Z', modified_at: '2026-11-05T00:00:00Z' }
      routes['/reports/schedules/'] = [schedule]
      await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(schedule) })
      return
    }
    if (key === '/settings/general/' && route.request().method() === 'PATCH') {
      const body = route.request().postDataJSON()
      if (body.timezone === 'Invalid/Zone') {
        await route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ error: { code: 'VALIDATION_ERROR', message: 'Check the settings.', field_errors: { timezone: ['Enter a valid IANA timezone.'] } } }) })
      } else {
        Object.assign(general, body, { version: general.version + 1 })
        me.display_preferences = { ...general }
        await route.fulfill({ contentType: 'application/json', body: JSON.stringify(general) })
      }
      return
    }
    if (!(key in routes)) unmapped.add(key)
    const response = responses.get(key)
    await route.fulfill({ status: response?.status ?? (key in routes ? 200 : 404), contentType: 'application/json', body: JSON.stringify(response?.body ?? routes[key] ?? { error: { message: `Unmocked ${key}` } }) })
  })
  await page.route(/^(?!http:\/\/127\.0\.0\.1:5197\/).*/, (route) => route.abort())
  await page.goto('http://127.0.0.1:5197/admin/backups')
  await page.getByRole('heading', { level: 1, name: 'Backups & Recovery' }).waitFor()
  await capture(page, 'backups-desktop')
  await page.getByRole('button', { name: 'Edit policy' }).click()
  await capture(page, 'backup-policy')
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  await page.goto('http://127.0.0.1:5197/assets')
  await page.getByRole('table', { name: 'Assets', exact: true }).waitFor()
  await page.getByLabel('Select sw-floor-01', { exact: true }).check()
  await capture(page, 'assets-selection-desktop')
  await page.setViewportSize({ width: 390, height: 844 })
  await capture(page, 'assets-mobile')
  await page.goto('http://127.0.0.1:5197/admin/backups')
  await page.getByRole('heading', { level: 1, name: 'Backups & Recovery' }).waitFor()
  await capture(page, 'backups-mobile')
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  if (overflow) throw new Error('Mobile page overflows viewport')
  for (const [url, label] of [
    ['/assets/asset-0', 'asset-detail'], ['/discovery', 'discovery'],
    ['/lifecycle', 'lifecycle'], ['/admin/integrations', 'integrations'],
    ['/software', 'software'], ['/domains', 'domains'], ['/admin/sites', 'sites'],
    ['/admin/categories', 'categories'], ['/admin/security', 'security-settings'],
    ['/admin/smtp', 'smtp-settings'],
    ['/admin/general', 'general-settings'], ['/', 'operational-health'], ['/admin/integrations?tab=catalogue', 'provider-catalogue'],
    ...['inventory', 'lifecycle', 'coverage', 'groups'].map((kind) => [`/reports?report=${kind}`, `report-${kind}`]),
  ]) {
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
      await page.goto(`http://127.0.0.1:5197${url}`)
      await page.waitForLoadState('networkidle')
      if (await page.locator('.state--error, .error-summary').count()) throw new Error(`Unexpected error on ${url}; check fixture coverage`)
      await capture(page, `${label}-${width}`)
      if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) {
        console.log(await page.evaluate(() => [...document.querySelectorAll('*')].map((element) => ({ tag: element.tagName, class: element.className?.toString(), right: element.getBoundingClientRect().right, position: getComputedStyle(element).position })).filter((element) => element.right > innerWidth).slice(-12)))
        throw new Error(`${label} overflows at ${width}`)
      }
    }
  }
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
    await page.goto('http://127.0.0.1:5197/reports?report=lifecycle')
    await page.getByRole('table', { name: 'Report results' }).waitFor()
    await page.getByRole('button', { name: 'Schedule digest' }).click()
    await page.getByRole('dialog', { name: 'Schedule report digest' }).waitFor()
    await capture(page, `report-digest-dialog-${width}`, false)
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'Export report' }).click()
    await page.getByRole('dialog', { name: 'Export lifecycle report' }).waitFor()
    await capture(page, `report-export-dialog-${width}`, false)
    await page.keyboard.press('Escape')
  }
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('http://127.0.0.1:5197/admin/general')
  await page.getByLabel('Display timezone').fill('Invalid/Zone')
  await page.getByRole('button', { name: 'Save general settings' }).click()
  await page.getByRole('alert').waitFor()
  await capture(page, 'general-validation-1440')
  await page.getByLabel('Display timezone').fill('UTC')
  await page.getByLabel('Organization name').fill('Synthetic organization with a long but valid display name')
  await page.getByRole('button', { name: 'Save general settings' }).click()
  await page.getByText('General settings saved.', { exact: true }).waitFor()
  await capture(page, 'general-saved-1440')
  if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error('Long organization label overflows')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('http://127.0.0.1:5197/admin/backups')
  await page.getByRole('button', { name: 'Edit policy' }).click()
  const saveBounds = await page.getByRole('button', { name: 'Save policy' }).boundingBox()
  if (!saveBounds || saveBounds.y < 0 || saveBounds.y + saveBounds.height > 844) throw new Error('Dialog action clipped')
  await capture(page, 'backup-policy-mobile')
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Open navigation' }).click()
  const close = page.getByRole('button', { name: 'Close navigation' })
  if (!(await close.evaluate((element) => element === document.activeElement))) throw new Error('Navigation focus missing')
  await page.keyboard.press('Escape')
  if (!(await page.getByRole('button', { name: 'Open navigation' }).evaluate((element) => element === document.activeElement))) throw new Error('Navigation focus did not return')
  const job = { id: 'synthetic-backup', kind: 'backup', status: 'succeeded', created_at: '2026-11-05T00:00:00Z', started_at: '2026-11-05T00:00:00Z', finished_at: '2026-11-05T00:00:12Z', recovery_point: '2026-11-05T00:00:00Z', target_label: 'Synthetic test storage', snapshot_id: 'a'.repeat(64), size_bytes: 1048576, verification_result: 'passed', duration_seconds: 12, manifest: { format: 'itam.backup.v1', app_revision: 'a'.repeat(40), database_sha256: 'b'.repeat(64), counts: { assets_asset: 28 } } }
  responses.set('/backups/jobs/', { body: [job] })
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
    await page.goto('http://127.0.0.1:5197/admin/backups')
    await page.getByRole('button', { name: 'View details' }).click()
    await page.getByRole('dialog', { name: 'Backup job details' }).waitFor()
    const drawerBounds = await page.getByRole('dialog', { name: 'Backup job details' }).boundingBox()
    if (!drawerBounds || drawerBounds.y < 0 || drawerBounds.y + drawerBounds.height > (width === 390 ? 844 : 900) + 1) throw new Error('Backup drawer clipped vertically')
    await capture(page, `backup-job-details-${width}`, false)
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error('Backup details overflow')
    await page.keyboard.press('Escape')
  }
  await page.setViewportSize({ width: 390, height: 844 })
  let release
  const pending = new Promise((resolve) => { release = resolve })
  const delayedAssets = async (route) => {
    await pending
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(pageData(assets)) })
  }
  await page.route('**/api/v1/assets/', delayedAssets)
  await page.goto('http://127.0.0.1:5197/assets')
  await page.getByText('Loading assets…', { exact: true }).waitFor()
  await capture(page, 'asset-loading-mobile')
  release()
  await page.getByRole('table', { name: 'Assets', exact: true }).waitFor()
  await page.unroute('**/api/v1/assets/', delayedAssets)
  responses.set('/assets/', { status: 503, body: { error: { code: 'FIXTURE_FAILURE', message: 'Synthetic service unavailable', request_id: 'fixture-reference' } } })
  await page.goto('http://127.0.0.1:5197/assets')
  await page.getByRole('alert').waitFor()
  await capture(page, 'asset-error-mobile')
  responses.delete('/assets/')
  responses.set('/auth/me/', { body: { ...me, permissions: [] } })
  await page.goto('http://127.0.0.1:5197/assets')
  await page.getByRole('alert').waitFor()
  await capture(page, 'asset-denied-mobile')
  await page.goto('http://127.0.0.1:5197/admin/general')
  await page.getByRole('alert').waitFor()
  await capture(page, 'general-denied-mobile')
  // Simulate a server timezone that this browser cannot represent.
  responses.set('/auth/me/', { body: { ...me, display_preferences: { ...me.display_preferences, timezone: 'Fixture/UnsupportedZone' } } })
  await page.goto('http://127.0.0.1:5197/assets')
  await page.getByText('This browser does not support the organization timezone. Dates are shown in UTC.', { exact: true }).waitFor()
  await capture(page, 'timezone-fallback-mobile')
  const result = { fixture_only: true, errors, unmapped: [...unmapped], screenshots }
  await fs.writeFile(`${output}/results.json`, JSON.stringify(result, null, 2))
  console.log(JSON.stringify(result))
  if (errors.length || unmapped.size) throw new Error('Browser errors or incomplete review fixtures')
} finally {
  await browser.close()
  await server.close()
}

