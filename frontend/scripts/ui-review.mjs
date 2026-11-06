import { createServer, preview } from 'vite'
import { chromium } from '@playwright/test'
import fs from 'node:fs/promises'
import { verifyCsp } from './verify-csp.mjs'

// Synthetic API responses only. No backend, vendor connector or SMTP service is contacted.
const cspReview = process.argv.includes('--csp')
const cspPolicy = (await fs.readFile('content-security-policy.conf', 'utf8')).match(/add_header Content-Security-Policy "([^"]+)" always;/)[1]
const output = cspReview ? 'test-results/csp-review' : 'test-results/category-icons-review'
await fs.mkdir(output, { recursive: true })
await fs.rm(`${output}/results.json`, { force: true })
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
const rootCategory = (id, name) => ({ id, code: id, name, path: name, parent: null, depth: 0, is_active: true })
const typeCategories = [
  ['workstations', 'Workstations'], ['servers', 'Servers'], ['networking', 'Networking'],
  ['printers', 'Printers'], ['security', 'Security'], ['monitors', 'Monitors'],
  ['ip-phones', 'IP Phones'], ['tvs', 'TVs'], ['ups', 'UPS'], ['power', 'Power Distribution'],
  ['storage', 'Storage'], ['peripherals', 'Peripherals'], ['other', 'Other'],
  ['lab-equipment', 'Lab equipment'],
].map(([id, name]) => rootCategory(id, name))
const category = { id: 'switch', code: 'switch', name: 'Switch', path: 'Networking / Switch', parent: 'networking', depth: 1, is_active: true }
const laptopCategory = { ...rootCategory('laptop', 'Laptop'), code: 'workstations-laptop', path: 'Workstations / Laptop', parent: 'workstations', depth: 1 }
const assets = Array.from({ length: 28 }, (_, i) => ({
  id: `asset-${i}`, name: `sw-floor-${String(i + 1).padStart(2, '0')}`, asset_tag: `IT-${1000 + i}`,
  category, manufacturer: 'Fixture Networks', model: 'Fixture 48', serial_number: `TEST-SERIAL-${i}`,
  primary_hostname: `sw-floor-${i + 1}.example.invalid`, primary_ip: `192.0.2.${i + 1}`,
  site, location: null, owner: null, business_status: 'deployed', observation_status: 'manual_only',
  support_status: 'unknown', is_archived: false, last_seen_at: null, source_count: 0,
  modified_at: '2026-11-05T00:00:00Z', version: 1,
}))
assets.push(...[
  ['workstation', 'ws-user-01', laptopCategory],
  ['server', 'srv-core-01', typeCategories[1]],
  ['printer', 'prn-office-01', typeCategories[3]],
].map(([id, name, assetCategory]) => ({ ...assets[0], id, name, category: assetCategory, model: 'Synthetic type fixture', asset_tag: `FIXTURE-${id}`, serial_number: `TEST-${id}` })))
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
  '/assets/': pageData(assets), '/asset-categories/': [...typeCategories, laptopCategory, category], '/sites/': [site], '/saved-views/': [],
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
if (cspReview) {
  routes['/notifications/templates/'] = [{ code: 'smtp_test', name: 'SMTP test message', description: 'Synthetic CSP preview', subject: 'Test', body_text: 'Preview', body_html: '<p>Preview</p>', variables: [], version: 1, modified_by: null }]
  routes['/notifications/templates/smtp_test/preview/'] = { subject: 'CSP preview', body_text: 'Policy preview content', body_html: '<style>p { color: rgb(40, 125, 75); }</style><p style="font-weight:600">Policy preview content</p>' }
}
const server = cspReview
  ? await preview({ preview: { host: '127.0.0.1', port: 5197, strictPort: true, headers: { 'Content-Security-Policy': cspPolicy } } })
  : await createServer({ server: { host: '127.0.0.1', port: 5197, strictPort: true } })
if (!cspReview) await server.listen()
const browser = await chromium.launch({ channel: process.env.ITAM_UI_BROWSER_CHANNEL === 'chromium' ? undefined : 'msedge', headless: true })
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' })
  const page = await context.newPage()
  const errors = []
  const violations = []
  if (cspReview) {
    await page.exposeFunction('recordPolicyViolation', (entry) => violations.push(entry))
    await page.addInitScript(() => document.addEventListener('securitypolicyviolation', (event) => {
      void window.recordPolicyViolation({ directive: event.effectiveDirective, blocked: event.blockedURI })
    }))
  }
  const unmapped = new Set()
  const responses = new Map()
  page.on('pageerror', (error) => errors.push(error.message))
  await page.route('**/api/v1/**', async (route) => {
    const key = new URL(route.request().url()).pathname.replace('/api/v1', '')
    const selectedCategory = new URL(route.request().url()).searchParams.get('category')
    if (key === '/assets/' && selectedCategory && !responses.has(key)) {
      const filtered = assets.filter((asset) => asset.category.id === selectedCategory || asset.category.parent === selectedCategory)
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(pageData(filtered)) })
      return
    }
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
  await page.waitForFunction(() => {
    const active = document.querySelector('.nav-link[aria-current="page"]')?.getBoundingClientRect()
    return active && active.left >= 0 && active.right <= innerWidth
  })
  const currentModule = await page.locator('.nav-link[aria-current="page"]').boundingBox()
  if (!currentModule || currentModule.x < 0 || currentModule.x + currentModule.width > 240) throw new Error('Current module is clipped in contextual sidebar')
  await capture(page, 'backups-desktop')
  await page.getByRole('button', { name: 'Inventory', exact: true }).click()
  await page.getByRole('link', { name: 'Assets', exact: true }).waitFor({ state: 'visible' })
  await page.getByRole('link', { name: 'Backups & Recovery', exact: true }).waitFor({ state: 'hidden' })
  await page.getByRole('button', { name: 'Administration', exact: true }).click()
  await page.getByRole('button', { name: 'Edit policy' }).click()
  await capture(page, 'backup-policy')
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  await page.goto('http://127.0.0.1:5197/assets')
  await page.getByRole('table', { name: 'Assets', exact: true }).waitFor()
  const typeDisclosure = page.getByRole('button', { name: 'Asset types', exact: true })
  await typeDisclosure.focus()
  await page.keyboard.press('Enter')
  await page.getByRole('link', { name: 'Workstations', exact: true }).waitFor({ state: 'hidden' })
  await page.getByRole('link', { name: 'Groups', exact: true }).waitFor({ state: 'visible' })
  await capture(page, 'asset-types-collapsed-desktop')
  await page.keyboard.press('Enter')
  await page.getByRole('link', { name: 'Workstations', exact: true }).waitFor({ state: 'visible' })
  await page.getByLabel('Select sw-floor-01', { exact: true }).check()
  await capture(page, 'assets-selection-desktop')
  await page.getByRole('button', { name: 'Filters & sort', exact: true }).click()
  await page.getByLabel('Category', { exact: true }).waitFor({ state: 'visible' })
  await capture(page, 'assets-filters-desktop')
  await page.getByRole('button', { name: 'Filters & sort', exact: true }).click()
  await page.getByLabel('Category', { exact: true }).waitFor({ state: 'hidden' })
  for (const width of [1024, 768]) {
    await page.setViewportSize({ width, height: 900 })
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error(`Tablet layout overflows at ${width}`)
    await capture(page, `assets-${width}`)
  }
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.getByRole('button', { name: 'Switch to dark theme' }).click()
  await capture(page, 'assets-selection-desktop-dark')
  await page.reload()
  await page.getByRole('button', { name: 'Switch to light theme' }).waitFor()
  await page.getByRole('button', { name: 'Switch to light theme' }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await capture(page, 'assets-mobile')
  await page.getByRole('button', { name: 'Switch to dark theme' }).click()
  await capture(page, 'assets-mobile-dark')
  await page.getByRole('button', { name: 'Switch to light theme' }).click()
  const filterToggle = page.getByRole('button', { name: 'Filters & sort', exact: true })
  await page.getByLabel('Category', { exact: true }).waitFor({ state: 'hidden' })
  if ((await page.getByRole('table', { name: 'Assets', exact: true }).boundingBox()).y >= 844) throw new Error('Mobile filters obscure the asset table')
  await filterToggle.focus()
  await page.keyboard.press('Space')
  await page.getByLabel('Category', { exact: true }).waitFor({ state: 'visible' })
  await page.getByLabel('Category', { exact: true }).selectOption('switch')
  await page.waitForURL('**/assets?category=switch')
  await capture(page, 'assets-filters-mobile')
  await page.getByRole('button', { name: 'Filters & sort (1 active)', exact: true }).click()
  await page.getByLabel('Category', { exact: true }).waitFor({ state: 'hidden' })
  await page.goto('http://127.0.0.1:5197/admin/backups')
  await page.getByRole('heading', { level: 1, name: 'Backups & Recovery' }).waitFor()
  await capture(page, 'backups-mobile')
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  if (overflow) throw new Error('Mobile page overflows viewport')
  await page.setViewportSize({ width: 1440, height: 900 })
  for (const [id, name, expected] of [['workstations', 'Workstations', 'ws-user-01'], ['servers', 'Servers', 'srv-core-01'], ['printers', 'Printers', 'prn-office-01']]) {
    await page.goto('http://127.0.0.1:5197/assets')
    await page.getByRole('link', { name, exact: true }).click()
    await page.waitForURL(`**/assets?category=${id}`)
    await page.getByRole('heading', { name, exact: true }).waitFor()
    const results = page.getByRole('table', { name: 'Assets', exact: true })
    await results.getByRole('link', { name: expected, exact: true }).waitFor()
    if (await results.locator('tbody tr').count() !== 1) throw new Error(`Incorrect type fixture rows for ${name}`)
    if (await page.getByRole('link', { name, exact: true }).getAttribute('aria-current') !== 'page') throw new Error('Asset type is not highlighted')
    await capture(page, `asset-type-${id}-desktop`)
    await page.getByRole('button', { name: 'Switch to dark theme' }).click()
    await capture(page, `asset-type-${id}-desktop-dark`)
    await page.getByRole('button', { name: 'Switch to light theme' }).click()
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('http://127.0.0.1:5197/assets?category=laptop')
  await page.getByRole('heading', { name: 'Laptop', exact: true }).waitFor()
  await page.getByRole('button', { name: 'Open navigation' }).click()
  if (await page.getByRole('link', { name: 'Workstations', exact: true }).getAttribute('aria-current') !== 'page') throw new Error('Child category does not highlight its parent')
  await capture(page, 'asset-types-navigation-mobile', false)
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Switch to dark theme' }).click()
  await page.getByRole('button', { name: 'Open navigation' }).click()
  await capture(page, 'asset-types-navigation-mobile-dark', false)
  await page.getByRole('button', { name: 'Asset types', exact: true }).click()
  await capture(page, 'asset-types-collapsed-mobile-dark', false)
  await page.getByRole('button', { name: 'Close navigation' }).focus()
  await page.keyboard.press('Shift+Tab')
  if (!await page.getByRole('link', { name: 'System health', exact: true }).evaluate((element) => element === document.activeElement)) throw new Error('Collapsed navigation loses reverse focus wrap')
  await page.keyboard.press('Tab')
  if (!await page.getByRole('button', { name: 'Close navigation' }).evaluate((element) => element === document.activeElement)) throw new Error('Collapsed navigation loses forward focus wrap')
  await page.getByRole('button', { name: 'Asset types', exact: true }).click()
  await page.getByRole('link', { name: 'Servers', exact: true }).click()
  await page.getByRole('heading', { name: 'Servers', exact: true }).waitFor()
  if (await page.getByRole('button', { name: 'Open navigation' }).getAttribute('aria-expanded') !== 'false') throw new Error('Type selection did not close mobile navigation')
  await capture(page, 'asset-type-servers-mobile-dark')
  await page.getByRole('button', { name: 'Switch to light theme' }).click()
  await capture(page, 'asset-type-servers-mobile')
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
      await page.getByRole('button', { name: 'Switch to dark theme' }).click()
      await capture(page, `${label}-${width}-dark`)
      if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error(`Dark theme overflow on ${url}`)
      await page.getByRole('button', { name: 'Switch to light theme' }).click()
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
    for (const theme of ['light', 'dark']) {
    if (theme === 'dark') await page.getByRole('button', { name: 'Switch to dark theme' }).click()
    await page.getByRole('button', { name: 'Schedule digest' }).click()
    await page.getByRole('dialog', { name: 'Schedule report digest' }).waitFor()
    await capture(page, `report-digest-dialog-${width}-${theme}`, false)
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'Export report' }).click()
    await page.getByRole('dialog', { name: 'Export lifecycle report' }).waitFor()
    await capture(page, `report-export-dialog-${width}-${theme}`, false)
    await page.keyboard.press('Escape')
    }
    await page.getByRole('button', { name: 'Switch to light theme' }).click()
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
  await capture(page, 'navigation-mobile')
  await page.keyboard.press('Shift+Tab')
  if (!(await page.getByRole('link', { name: 'System health', exact: true }).evaluate((element) => element === document.activeElement))) throw new Error('Navigation focus did not wrap backwards')
  await page.keyboard.press('Tab')
  if (!(await close.evaluate((element) => element === document.activeElement))) throw new Error('Navigation focus did not wrap forwards')
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
  if (cspReview) {
    await page.goto('http://127.0.0.1:5197/admin/smtp?tab=templates')
    await page.getByRole('button', { name: 'Preview', exact: true }).click()
    const email = page.frameLocator('iframe[title="HTML preview"]').getByText('Policy preview content')
    await email.waitFor()
    if (await email.evaluate((element) => getComputedStyle(element).color) !== 'rgb(40, 125, 75)') throw new Error('CSP broke email preview styling')
    await page.locator('iframe[title="HTML preview"]').evaluate((element) => element.scrollIntoView({ block: 'center' }))
    if (await page.locator('iframe[title="HTML preview"]').getAttribute('sandbox') !== '') throw new Error('Email preview sandbox changed')
    await capture(page, 'smtp-sandboxed-preview-csp')
  }
  responses.set('/auth/me/', { status: 401, body: { error: { code: 'NOT_AUTHENTICATED', message: 'Sign in.' } } })
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
    await page.goto('http://127.0.0.1:5197/login')
    await page.getByRole('heading', { name: 'Sign in', exact: true }).waitFor()
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error('Sign-in page overflows')
    await capture(page, `sign-in-${width}`)
    await page.getByRole('button', { name: 'Switch to dark theme' }).click()
    await capture(page, `sign-in-${width}-dark`)
    await page.getByRole('button', { name: 'Switch to light theme' }).click()
  }
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.getByText('Enter your username.', { exact: true }).waitFor()
  await capture(page, 'sign-in-validation-mobile')
  let cspProof
  if (cspReview) {
    if (violations.length) throw new Error(`Unexpected UI CSP violations: ${JSON.stringify(violations)}`)
    cspProof = await verifyCsp(page, cspPolicy, violations)
  }
  const result = { status: errors.length || unmapped.size ? 'failed' : 'passed', fixture_only: true, production_build: cspReview, csp: cspProof, errors, unmapped: [...unmapped], screenshots }
  await fs.writeFile(`${output}/results.json`, JSON.stringify(result, null, 2))
  console.log(JSON.stringify(result))
  if (errors.length || unmapped.size) throw new Error('Browser errors or incomplete review fixtures')
} finally {
  await browser.close()
  if (cspReview) await new Promise((resolve, reject) => server.httpServer.close((error) => error ? reject(error) : resolve()))
  else await server.close()
}

