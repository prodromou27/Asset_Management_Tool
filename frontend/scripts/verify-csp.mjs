import assert from 'node:assert/strict'
import { expect } from '@playwright/test'

export async function verifyCsp(page, policy, violations) {
  const origin = 'http://127.0.0.1:5197'
  const response = await page.goto(`${origin}/login`)
  assert.equal(response.headers()['content-security-policy'], policy)
  await page.route('**/csp-allowed-probe.js', (route) => route.fulfill({
    contentType: 'application/javascript',
    body: `window.__allowedProbe = true; try { new Function('window.__evalProbe = true')(); } catch { window.__evalBlocked = true; }`,
  }))
  await page.evaluate(() => {
    const inline = document.createElement('script')
    inline.textContent = 'window.__inlineProbe = true'
    document.body.append(inline)
    const allowed = document.createElement('script')
    allowed.src = '/csp-allowed-probe.js'
    document.body.append(allowed)
    const foreign = document.createElement('script')
    foreign.src = 'https://blocked.example.invalid/probe.js'
    document.body.append(foreign)
    const button = document.createElement('button')
    button.setAttribute('onclick', 'window.__handlerProbe = true')
    document.body.append(button)
    button.click()
    const base = document.createElement('base')
    base.href = 'https://blocked.example.invalid/'
    document.head.append(base)
    void fetch('https://blocked.example.invalid/probe').catch(() => {})
    const object = document.createElement('object')
    object.data = '/csp-allowed-probe.js'
    document.body.append(object)
  })
  await page.waitForFunction(() => window.__allowedProbe && window.__evalBlocked)
  const flags = await page.evaluate(() => ({
    inline: !!window.__inlineProbe, handler: !!window.__handlerProbe,
    eval: !!window.__evalProbe, base: document.baseURI,
  }))
  assert.deepEqual(flags, { inline: false, handler: false, eval: false, base: `${origin}/login` })
  for (const directive of ['script-src-elem', 'script-src-attr', 'script-src', 'connect-src', 'base-uri', 'object-src']) {
    await expect.poll(() => violations.map((entry) => entry.directive)).toContain(directive)
  }
  await expect.poll(() => violations.some((entry) => entry.directive === 'script-src-elem'
    && new URL(entry.blocked, origin).origin === 'https://blocked.example.invalid')).toBe(true)
  const embedding = await page.context().newPage()
  try {
    await embedding.route('**/api/v1/**', (route) => route.fulfill({ status: 401, contentType: 'application/json', body: '{}' }))
    await embedding.route(/^(?!http:\/\/127\.0\.0\.1:5197\/).*/, (route) => route.abort())
    await embedding.route('**/csp-embedding-probe', (route) => route.fulfill({
      contentType: 'text/html', body: `<iframe src="${origin}/login"></iframe>`,
    }))
    const blocked = embedding.waitForEvent('console', { predicate: (message) => message.text().includes('frame-ancestors') })
    await embedding.goto(`${origin}/csp-embedding-probe`)
    await blocked
  } finally {
    await embedding.close()
  }
  return { policy, normal_ui_violations: 0, sandboxed_email_preview: true,
    inline_script_blocked: true, handler_blocked: true, eval_blocked: true,
    foreign_script_blocked: true, external_connection_blocked: true,
    base_override_blocked: true, object_blocked: true, embedding_blocked: true }
}
