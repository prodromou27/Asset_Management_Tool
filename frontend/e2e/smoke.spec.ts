import { expect, test } from '@playwright/test'

test('frontend shell loads and shows the system health panel', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'System health' })).toBeVisible()
  await expect(page.getByText('ITAM')).toBeVisible()
})
