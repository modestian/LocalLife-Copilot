import { expect, test, type Page, type Route } from '@playwright/test'

const sessionKey = 'local-life-copilot.auth-session'
const modelId = '70300000-0000-4000-8000-0000000000aa'

function response(data: unknown, status = 200): Parameters<Route['fulfill']>[0] {
  return {
    status,
    contentType: 'application/json',
    body: JSON.stringify({ data }),
  }
}

function modelVersion(status: string): Record<string, unknown> {
  return {
    id: modelId,
    name: '点评情感 LoRA',
    version: '1.3.0',
    task_type: 'sentiment_classification',
    status,
    base_model_ref: 'chinese-roberta-base',
    adapter_uri: 's3://models/1.3.0',
    artifact_sha256: 'f'.repeat(64),
    metrics: { macro_f1: 0.87 },
    created_at: '2026-07-01T09:00:00',
  }
}

async function installAuthentication(page: Page): Promise<void> {
  await page.route('**/api/v1/auth/login', async (route) => {
    await route.fulfill(response({
      access_token: 'e2e-admin-access-token',
      refresh_token: 'e2e-admin-refresh-token',
      token_type: 'bearer',
      expires_in: 3600,
      refresh_expires_in: 7200,
    }))
  })
  await page.route('**/api/v1/users/me', async (route) => {
    await route.fulfill(response({
      id: 'e2e-admin',
      username: 'demo-admin',
      display_name: '演示平台主管理员',
      email: null,
      department_id: '70300000-0000-4000-8000-000000000001',
      roles: [{ code: 'PLATFORM_ADMIN', name: '平台管理员' }],
      permissions: [],
      resource_scopes: [],
    }))
  })
  await page.route('**/health/ready', async (route) => {
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ status: 'ready' }) })
  })

  await page.goto('/login')
  await page.locator('input[autocomplete="username"]').fill('demo-admin')
  await page.locator('input[autocomplete="current-password"]').fill('e2e-local-password')
  await page.locator('button[type="submit"]').click()
  await expect(page.locator('body')).not.toHaveAttribute('data-auth-pending', 'true')
  await expect.poll(() => page.evaluate((key) => Boolean(window.localStorage.getItem(key)), sessionKey)).toBe(true)
}

test.describe('模型治理闭环：审批与回滚', () => {
  test('管理员在页面完成审批并执行回滚，部署与审计状态同步刷新', async ({ page }) => {
    let currentStatus = 'EVALUATED'
    let approvalPayload: Record<string, unknown> | undefined
    let rollbackPayload: Record<string, unknown> | undefined

    await page.route('**/api/v1/models/deployments**', async (route) => {
      await route.fulfill(response({
        scene: 'merchant_analytics',
        environment: 'staging',
        items: [{
          deployment_id: 'deployment-e2e-1',
          model_version_id: modelId,
          traffic_percent: 100,
          status: 'ACTIVE',
          is_canary: false,
        }],
      }))
    })
    await page.route(`**/api/v1/models/${modelId}/status`, async (route) => {
      approvalPayload = route.request().postDataJSON() as Record<string, unknown>
      currentStatus = String(approvalPayload.status)
      await route.fulfill(response(modelVersion(currentStatus)))
    })
    await page.route(`**/api/v1/models/${modelId}/rollback`, async (route) => {
      rollbackPayload = route.request().postDataJSON() as Record<string, unknown>
      await route.fulfill(response({
        id: 'deployment-e2e-1',
        model_version_id: modelId,
        scene: rollbackPayload.scene,
        environment: rollbackPayload.environment,
        traffic_percent: 100,
        action: 'ROLLBACK',
        status: 'ACTIVE',
        result: 'SUCCEEDED',
        deployed_by: 'e2e-admin',
        reason: rollbackPayload.reason,
        created_at: '2026-07-01T10:00:00',
      }, 201))
    })
    await page.route('**/api/v1/models', async (route) => {
      await route.fulfill(response({ items: [modelVersion(currentStatus)] }))
    })

    await installAuthentication(page)
    await page.goto('/admin/models')
    await page.getByRole('button', { name: '刷新模型版本' }).click()
    await expect(page.locator('.status-chip').first()).toContainText('已评测')

    const approvalForm = page.locator('form', { has: page.getByRole('heading', { name: '人工审批' }) })
    await expect(approvalForm.locator('button[type="submit"]')).toBeDisabled()
    await approvalForm.locator('textarea').fill('固定集指标达标，人工抽检通过。')
    await approvalForm.locator('input[type="checkbox"]').check()
    await approvalForm.locator('button[type="submit"]').click()

    await expect.poll(() => approvalPayload).toMatchObject({
      status: 'APPROVED',
      reason: '固定集指标达标，人工抽检通过。',
    })
    await expect(page.locator('.model-lifecycle__notice')).toContainText('审批结论已提交')
    await expect(page.locator('.status-chip').first()).toContainText('已审批')

    const rollbackForm = page.locator('form', { has: page.getByRole('heading', { name: '一键回滚' }) })
    await expect(rollbackForm.locator('button[type="submit"]')).toBeDisabled()
    await rollbackForm.locator('textarea').fill('灰度错误率超过阈值，执行回滚。')
    await rollbackForm.locator('input[type="checkbox"]').check()
    await expect(rollbackForm.locator('.model-lifecycle__confirm')).toContainText('merchant_analytics')
    await rollbackForm.locator('button[type="submit"]').click()

    await expect.poll(() => rollbackPayload).toMatchObject({
      scene: 'merchant_analytics',
      environment: 'staging',
      reason: '灰度错误率超过阈值，执行回滚。',
    })
    await expect(page.locator('.model-lifecycle__notice')).toContainText('回滚已执行')
    await expect(page.locator('.model-lifecycle__receipt')).toContainText('最近回执：ROLLBACK / ACTIVE / SUCCEEDED')
    await expect(page.locator('.model-lifecycle__receipt li').first()).toContainText('ACTIVE · 100%')
  })
})
