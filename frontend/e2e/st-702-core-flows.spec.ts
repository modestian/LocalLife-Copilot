import { expect, test, type Page, type Route } from '@playwright/test'

const sessionKey = 'local-life-copilot.auth-session'
const knowledgeBaseId = '70200000-0000-4000-8000-000000000010'
const merchantId = '70200000-0000-4000-8000-000000000020'
const unauthorizedMerchantId = '70200000-0000-4000-8000-000000000021'
const documentId = '70200000-0000-4000-8000-000000000040'
const taskId = '70200000-0000-4000-8000-000000000060'

type DemoRole = 'admin' | 'user' | 'merchant'

function response(data: unknown, status = 200): Parameters<Route['fulfill']>[0] {
  return {
    status,
    contentType: 'application/json',
    body: JSON.stringify({ data }),
  }
}

function currentUser(role: DemoRole): Record<string, unknown> {
  const users = {
    admin: {
      username: 'demo-admin',
      display_name: '演示平台主管理员',
      roles: [{ code: 'PLATFORM_ADMIN', name: '平台管理员' }],
      resource_scopes: [],
    },
    user: {
      username: 'demo-user',
      display_name: '演示探店用户',
      roles: [{ code: 'USER', name: '普通用户' }],
      resource_scopes: [{ resource_type: 'KNOWLEDGE_BASE', resource_id: knowledgeBaseId, actions: ['READ'] }],
    },
    merchant: {
      username: 'demo-merchant',
      display_name: '演示商家运营',
      roles: [{ code: 'MERCHANT_ADMIN', name: '商家管理员' }],
      resource_scopes: [{ resource_type: 'MERCHANT', resource_id: merchantId, actions: ['READ'] }],
    },
  } as const
  const selected = users[role]
  return {
    id: `e2e-${role}`,
    email: null,
    department_id: '70200000-0000-4000-8000-000000000001',
    permissions: [],
    ...selected,
  }
}

async function installAuthentication(page: Page, role: DemoRole): Promise<void> {
  await page.route('**/api/v1/auth/login', async (route) => {
    await route.fulfill(response({
      access_token: `e2e-${role}-access-token`,
      refresh_token: `e2e-${role}-refresh-token`,
      token_type: 'bearer',
      expires_in: 3600,
      refresh_expires_in: 7200,
    }))
  })
  await page.route('**/api/v1/users/me', async (route) => {
    await route.fulfill(response(currentUser(role)))
  })
  await page.route('**/health/ready', async (route) => {
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ status: 'ready' }) })
  })

  await page.goto('/login')
  await page.locator('input[autocomplete="username"]').fill(`demo-${role}`)
  await page.locator('input[autocomplete="current-password"]').fill('e2e-local-password')
  await page.locator('button[type="submit"]').click()
  await expect(page.locator('body')).not.toHaveAttribute('data-auth-pending', 'true')
  await expect.poll(() => page.evaluate((key) => Boolean(window.localStorage.getItem(key)), sessionKey)).toBe(true)
}

const knowledgeBase = {
  id: knowledgeBaseId,
  name: '探店知识库',
  description: '用于确定性验收的商家资料。',
  department_id: '70200000-0000-4000-8000-000000000001',
  department_name: 'ST-702 演示租户',
  owner_id: 'e2e-admin',
  owner_name: '演示平台主管理员',
  embedding_model_id: '70200000-0000-4000-8000-000000000032',
  embedding_model_name: 'demo-sentiment-v2',
  chunk_size: 500,
  chunk_overlap: 80,
  status: 'ACTIVE',
  statistics: { document_count: 2, chunk_count: 2, ready_document_count: 2, failed_document_count: 0 },
  created_at: '2026-07-01T09:00:00',
  updated_at: '2026-07-01T09:00:00',
  latest_indexed_at: '2026-07-01T09:00:00',
}

test.describe('ST-702 核心角色链路与错误态', () => {
  test('管理员登录后上传文档，并等待索引任务完成', async ({ page }) => {
    let taskRequests = 0
    await page.route(`**/api/v1/knowledge-bases/${knowledgeBaseId}/documents**`, async (route) => {
      await route.fulfill(response({ items: [], total: 0, page: 1, page_size: 10 }))
    })
    await page.route(`**/api/v1/knowledge-bases/${knowledgeBaseId}/documents:upload`, async (route) => {
      expect(route.request().method()).toBe('POST')
      await route.fulfill(response({ task_id: taskId, status: 'PENDING', progress: 0, status_url: `/api/v1/tasks/${taskId}` }, 202))
    })
    await page.route(`**/api/v1/tasks/${taskId}`, async (route) => {
      taskRequests += 1
      const completed = taskRequests > 1
      await route.fulfill(response({
        task_id: taskId,
        task_type: 'INGEST',
        resource_type: 'DOCUMENT',
        resource_id: documentId,
        status: completed ? 'SUCCEEDED' : 'RUNNING',
        stage: completed ? 'VERIFYING' : 'INDEXING',
        progress: completed ? 100 : 72,
        cancellable: !completed,
        retryable: false,
        attempt_count: 1,
        max_attempts: 3,
        error_code: null,
        error_message: null,
        files: [],
        result: completed ? { chunk_count: 1 } : null,
        created_at: '2026-07-01T09:00:00',
        updated_at: '2026-07-01T09:01:00',
        started_at: '2026-07-01T09:00:05',
        completed_at: completed ? '2026-07-01T09:01:00' : null,
      }))
    })
    await page.route(`**/api/v1/knowledge-bases/${knowledgeBaseId}`, async (route) => {
      await route.fulfill(response(knowledgeBase))
    })

    await installAuthentication(page, 'admin')
    await page.goto(`/admin/knowledge-bases/${knowledgeBaseId}`)
    await expect(page.locator('.upload-panel')).toBeVisible()
    await page.locator('input[type="file"]').setInputFiles({
      name: 'st-702-upload.md',
      mimeType: 'text/markdown',
      buffer: Buffer.from('# ST-702\n确定性上传内容。'),
    })
    await expect(page.locator('.upload-actions button')).toBeEnabled()
    await page.locator('.upload-actions button').click()

    await expect.poll(() => taskRequests, { timeout: 5000 }).toBeGreaterThan(1)
    await expect(page.locator('.task-card.is-succeeded progress').first()).toHaveAttribute('value', '100')
  })

  test('普通用户可查看引用、跳转来源并提交反馈，同时展示无结果兜底', async ({ page }) => {
    let feedbackPayload: Record<string, unknown> | undefined
    const conversationId = '70200000-0000-4000-8000-000000000050'
    const assistantMessageId = '70200000-0000-4000-8000-000000000052'
    await page.route('**/api/v1/conversations**', async (route) => {
      await route.fulfill(response({
        items: [{
          id: conversationId,
          title: '清河面馆午餐咨询',
          scenario: 'nearby',
          status: 'ACTIVE',
          updated_at: '2026-07-01T09:00:00',
          message_count: 2,
          preview_messages: [{
            id: assistantMessageId,
            conversation_id: conversationId,
            role: 'ASSISTANT',
            content: '清河面馆适合两人午餐，建议错峰避开排队。',
            status: 'COMPLETED',
            created_at: '2026-07-01T09:00:00',
            recommendations: [{
              merchant_id: merchantId,
              name: '清河面馆',
              category: '面馆',
              rating: 4.7,
              distance_meter: 500,
              avg_price_cent: 3600,
              business_status: 'OPEN',
              reason: '双人套餐分量充足。',
              tags: ['双人午餐'],
              data_updated_at: '2026-07-01T09:00:00',
              source_chunk_ids: ['chunk-qinghe'],
            }],
            sources: [{
              chunk_id: 'chunk-qinghe',
              document_id: documentId,
              merchant_id: merchantId,
              content: '双人套餐分量充足，午餐高峰建议错峰。',
              source_location: '清河面馆探店资料',
              source_url: `https://example.com/sources/${documentId}`,
              score: 0.98,
              highlight_text: '双人套餐',
            }],
          }, {
            id: 'fallback-message',
            conversation_id: conversationId,
            role: 'ASSISTANT',
            content: '',
            status: 'COMPLETED',
            created_at: '2026-07-01T09:01:00',
            recommendations: [],
            sources: [],
            fallback: { triggered: true, reason: '没有足够的可信检索证据。' },
          }],
        }],
      }))
    })
    await page.route('**/api/v1/chat/feedback', async (route) => {
      feedbackPayload = route.request().postDataJSON() as Record<string, unknown>
      await route.fulfill(response({ id: 'feedback-e2e', rating: 1 }, 201))
    })

    await installAuthentication(page, 'user')
    await page.goto('/app')
    await page.locator(`[data-conversation-id="${conversationId}"]`).click()
    await expect(page.locator('.recommendation-card')).toBeVisible()
    await page.locator('.recommendation-card__sources').click()
    const sourceLink = page.locator('.source-item a')
    await expect(sourceLink).toHaveAttribute('href', `https://example.com/sources/${documentId}`)
    await expect(page.locator('.recommendation-fallback')).toBeVisible()
    await page.locator('.source-drawer button').click()
    await expect(page.locator('.source-drawer')).toBeHidden()

    await page.locator('.message-feedback__actions button').first().click()
    await expect.poll(() => feedbackPayload).toMatchObject({
      conversation_id: conversationId,
      message_id: assistantMessageId,
      rating: 1,
    })
  })

  test('商家仅能查看授权范围', async ({ page }) => {
    await page.route('**/api/v1/merchants/**', async (route) => {
      const url = route.request().url()
      if (url.includes('sentiment-trend')) {
        await route.fulfill(response([{ period: '2026-07-01', positive: 4, neutral: 1, negative: 1 }]))
      } else if (url.includes('negative-reasons')) {
        await route.fulfill(response([{ reason: '排队时间长', count: 1 }]))
      } else {
        await route.fulfill(response([{ id: 'review-1', review_text: '午餐排队较久。', sentiment: 'NEGATIVE', confidence: 0.93, aspect_labels: ['排队'], negative_reasons: ['排队时间长'], review_date: '2026-07-01T12:00:00' }]))
      }
    })
    await installAuthentication(page, 'merchant')
    await page.goto(`/merchant/${merchantId}`)
    await expect(page.locator('.summary-grid')).toBeVisible()
    await page.goto(`/merchant/${unauthorizedMerchantId}`)
    await expect(page.locator('.access-state')).toBeVisible()
  })

  test('管理员可查看失败任务的错误详情并重试', async ({ page }) => {
    let retryRequests = 0
    await page.route(`**/api/v1/knowledge-bases/${knowledgeBaseId}/documents**`, async (route) => {
      await route.fulfill(response({ items: [], total: 0, page: 1, page_size: 10 }))
    })
    await page.route(`**/api/v1/knowledge-bases/${knowledgeBaseId}/documents:upload`, async (route) => {
      await route.fulfill(response({ task_id: taskId, status: 'PENDING', progress: 0, status_url: `/api/v1/tasks/${taskId}` }, 202))
    })
    await page.route(`**/api/v1/knowledge-bases/${knowledgeBaseId}`, async (route) => {
      await route.fulfill(response(knowledgeBase))
    })
    await page.route(`**/api/v1/tasks/${taskId}/retry`, async (route) => {
      retryRequests += 1
      await route.fulfill(response({ task_id: taskId, status: 'PENDING', progress: 0, status_url: `/api/v1/tasks/${taskId}` }))
    })
    await page.route(`**/api/v1/tasks/${taskId}`, async (route) => {
      await route.fulfill(response({
        task_id: taskId,
        task_type: 'INGEST',
        resource_type: 'DOCUMENT',
        resource_id: documentId,
        status: 'FAILED',
        stage: 'INDEXING',
        progress: 72,
        cancellable: false,
        retryable: true,
        attempt_count: 1,
        max_attempts: 3,
        error_code: 'SEARCH_BACKEND_UNAVAILABLE',
        error_message: '索引服务暂不可用。',
        files: [{ file_name: 'failed.md', document_id: documentId, status: 'FAILED', stage: 'INDEXING', progress: 72, error_code: 'SEARCH_BACKEND_UNAVAILABLE', error_message: '索引服务暂不可用。' }],
        result: null,
        created_at: '2026-07-01T09:00:00',
        updated_at: '2026-07-01T09:01:00',
        started_at: '2026-07-01T09:00:05',
        completed_at: '2026-07-01T09:01:00',
      }))
    })

    await installAuthentication(page, 'admin')
    await page.goto(`/admin/knowledge-bases/${knowledgeBaseId}`)
    await page.locator('input[type="file"]').setInputFiles({
      name: 'failed.md',
      mimeType: 'text/markdown',
      buffer: Buffer.from('# failed'),
    })
    await expect(page.locator('.upload-actions button')).toBeEnabled()
    await page.locator('.upload-actions button').click()
    await expect(page.locator('.task-card.is-failed')).toBeVisible()
    await expect(page.locator('.failure-detail')).toContainText('SEARCH_BACKEND_UNAVAILABLE')
    await page.locator('.retry-button').click()
    await expect.poll(() => retryRequests).toBe(1)
  })
})
