import type { CurrentUser } from '@/types/auth'

export type KnowledgeBaseAccessReason =
  | 'ALLOWED'
  | 'LOGIN_REQUIRED'
  | 'ROLE_PERMISSION_REQUIRED'
  | 'RESOURCE_SCOPE_REQUIRED'

export interface KnowledgeBaseAccess {
  allowed: boolean
  reason: KnowledgeBaseAccessReason
}

const updatePermissionCodes = new Set([
  'KB.UPDATE',
  'KB.WRITE',
  'KB.MANAGE',
  'KB_UPDATE',
  'KB_WRITE',
  'KB_MANAGE',
  'KNOWLEDGE_BASE.UPDATE',
  'KNOWLEDGE_BASE.WRITE',
  'KNOWLEDGE_BASE.MANAGE',
])

function normalizedPermission(code: string): string {
  return code.trim().toUpperCase().replaceAll(':', '.').replaceAll('-', '.')
}

export function canUpdateKnowledgeBase(
  user: CurrentUser | null,
  knowledgeBaseId: string,
): KnowledgeBaseAccess {
  if (!user) return { allowed: false, reason: 'LOGIN_REQUIRED' }

  const roles = new Set(user.roles.map((role) => role.code.trim().toUpperCase()))
  if (roles.has('PLATFORM_ADMIN')) return { allowed: true, reason: 'ALLOWED' }

  const hasRolePermission = user.permissions.some((permission) =>
    updatePermissionCodes.has(normalizedPermission(permission)),
  )
  if (!hasRolePermission) return { allowed: false, reason: 'ROLE_PERMISSION_REQUIRED' }

  const hasResourceScope = user.resource_scopes.some(
    (scope) =>
      scope.resource_type === 'KNOWLEDGE_BASE' &&
      scope.resource_id === knowledgeBaseId &&
      scope.actions.some((action) => ['UPDATE', 'WRITE', 'MANAGE'].includes(action.toUpperCase())),
  )
  if (!hasResourceScope) return { allowed: false, reason: 'RESOURCE_SCOPE_REQUIRED' }

  return { allowed: true, reason: 'ALLOWED' }
}

export function knowledgeBaseAccessLabel(access: KnowledgeBaseAccess): string {
  const labels: Record<KnowledgeBaseAccessReason, string> = {
    ALLOWED: '可编辑',
    LOGIN_REQUIRED: '游客只读',
    ROLE_PERMISSION_REQUIRED: '无编辑权限',
    RESOURCE_SCOPE_REQUIRED: '未授权此资源',
  }
  return labels[access.reason]
}
