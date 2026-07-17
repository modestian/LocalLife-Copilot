import { expect, test } from '@playwright/test'

const sessionKey = 'local-life-copilot.auth-session'

test.beforeEach(async ({ page }) => {
  await page.addInitScript(({ key }) => {
    const now = Date.now()
    window.localStorage.setItem(key, JSON.stringify({
      access_token: 'e2e-access-token',
      refresh_token: 'e2e-refresh-token',
      token_type: 'bearer',
      expires_in: 3600,
      refresh_expires_in: 7200,
      access_expires_at: now + 3_600_000,
      refresh_expires_at: now + 7_200_000,
    }))
  }, { key: sessionKey })

  await page.route('**/api/v1/users/me', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        data: {
          id: 'user-e2e',
          username: 'e2e_user',
          display_name: '响应式测试用户',
          email: null,
          department_id: null,
          roles: [{ code: 'USER', name: '普通用户' }],
          permissions: [],
          resource_scopes: [],
        },
      }),
    })
  })
  await page.route('**/api/v1/conversations**', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ data: { items: [] } }),
    })
  })
  await page.route('**/health/ready', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ status: 'ready', checks: { api: 'up' } }),
    })
  })
})

test('scene entry and composite inputs remain usable without horizontal overflow', async ({
  page,
}, testInfo) => {
  await page.goto('/app')

  await expect(page.getByRole('heading', { name: '一句话，找到此刻想去的地方' })).toBeVisible()
  await expect(page.getByText('响应式测试用户 · 普通用户')).toBeVisible()
  await expect(page.getByRole('region', { name: '用户探店工作台' })).toBeVisible()
  await expect(page.getByText('还没有历史会话')).toBeVisible()

  await page.locator('[data-scenario="study"]').click()
  await page.getByPlaceholder('元/人').fill('60')
  await page.getByPlaceholder('川菜、咖啡…').fill('咖啡')
  await expect(page.getByRole('textbox', { name: '' }).last()).toHaveValue(
    '找一家适合学习办公、安静且方便久坐的店',
  )

  const layout = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    workspaceDisplay: getComputedStyle(document.querySelector('.conversation-workspace')!).display,
  }))
  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth)
  expect(layout.workspaceDisplay).toBe(
    testInfo.project.name === 'mobile-chromium' ? 'block' : 'grid',
  )

  const composer = page.locator('.composer')
  await composer.scrollIntoViewIfNeeded()
  await expect(composer).toBeVisible()
  const composerBox = await composer.boundingBox()
  expect(composerBox).not.toBeNull()
  expect(composerBox!.x).toBeGreaterThanOrEqual(0)
  expect(composerBox!.x + composerBox!.width).toBeLessThanOrEqual(layout.clientWidth + 1)
})
