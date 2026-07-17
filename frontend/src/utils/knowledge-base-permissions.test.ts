import { describe, expect, it } from 'vitest'

import type { CurrentUser } from '@/types/auth'

import { canUpdateKnowledgeBase, knowledgeBaseAccessLabel } from './knowledge-base-permissions'

function user(overrides: Partial<CurrentUser> = {}): CurrentUser {
  return {
    id: 'user-id',
    username: 'kb-admin',
    display_name: '知识库管理员',
    email: null,
    department_id: null,
    roles: [{ code: 'KB_ADMIN', name: '知识库管理员' }],
    permissions: ['kb.update'],
    resource_scopes: [
      { resource_type: 'KNOWLEDGE_BASE', resource_id: 'kb-allowed', actions: ['READ', 'UPDATE'] },
    ],
    ...overrides,
  }
}

describe('knowledge base update permission', () => {
  it('keeps guests read-only', () => {
    const access = canUpdateKnowledgeBase(null, 'kb-allowed')

    expect(access).toEqual({ allowed: false, reason: 'LOGIN_REQUIRED' })
    expect(knowledgeBaseAccessLabel(access)).toBe('游客只读')
  })

  it('requires both role permission and resource scope', () => {
    expect(canUpdateKnowledgeBase(user(), 'kb-allowed').allowed).toBe(true)
    expect(canUpdateKnowledgeBase(user({ permissions: [] }), 'kb-allowed').reason).toBe(
      'ROLE_PERMISSION_REQUIRED',
    )
    expect(canUpdateKnowledgeBase(user(), 'kb-forbidden').reason).toBe('RESOURCE_SCOPE_REQUIRED')
  })

  it('allows platform administrators to manage all knowledge bases', () => {
    const access = canUpdateKnowledgeBase(
      user({ roles: [{ code: 'PLATFORM_ADMIN', name: '平台管理员' }], permissions: [], resource_scopes: [] }),
      'any-kb',
    )

    expect(access).toEqual({ allowed: true, reason: 'ALLOWED' })
  })
})
