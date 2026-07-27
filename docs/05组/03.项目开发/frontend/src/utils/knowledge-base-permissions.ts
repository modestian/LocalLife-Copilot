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

const createPermissionCodes = new Set([
  'KB.CREATE',
  'KB_CREATE',
  'KNOWLEDGE_BASE.CREATE',
])

const deletePermissionCodes = new Set([
  'KB.DELETE',
  'KB_DELETE',
  'KNOWLEDGE_BASE.DELETE',
])

function normalizedPermission(code: string): string {
  return code.trim().toUpperCase().replaceAll(':', '.').replaceAll('-', '.')
}

function hasPermission(
  user: CurrentUser,
  permissionCodes: Set<string>,
): boolean {
  return user.permissions.some((permission) =>
    permissionCodes.has(normalizedPermission(permission)),
  )
}

export function canCreateKnowledgeBase(user: CurrentUser | null): KnowledgeBaseAccess {
  if (!user) return { allowed: false, reason: 'LOGIN_REQUIRED' }
  const roles = new Set(user.roles.map((role) => role.code.trim().toUpperCase()))
  if (roles.has('PLATFORM_ADMIN') || roles.has('KB_ADMIN')) {
    return { allowed: true, reason: 'ALLOWED' }
  }
  if (hasPermission(user, createPermissionCodes)) {
    return { allowed: true, reason: 'ALLOWED' }
  }
  return { allowed: false, reason: 'ROLE_PERMISSION_REQUIRED' }
}

export function canDeleteKnowledgeBase(
  user: CurrentUser | null,
  knowledgeBaseId: string,
): KnowledgeBaseAccess {
  if (!user) return { allowed: false, reason: 'LOGIN_REQUIRED' }

  const roles = new Set(user.roles.map((role) => role.code.trim().toUpperCase()))
  if (roles.has('PLATFORM_ADMIN') || roles.has('KB_ADMIN')) {
    return { allowed: true, reason: 'ALLOWED' }
  }

  const hasRolePermission = hasPermission(user, deletePermissionCodes)
  if (!hasRolePermission) return { allowed: false, reason: 'ROLE_PERMISSION_REQUIRED' }

  const hasResourceScope = user.resource_scopes.some(
    (scope) =>
      scope.resource_type === 'KNOWLEDGE_BASE' &&
      scope.resource_id === knowledgeBaseId &&
      scope.actions.some((action) => ['DELETE', 'MANAGE'].includes(action.toUpperCase())),
  )
  if (!hasResourceScope) return { allowed: false, reason: 'RESOURCE_SCOPE_REQUIRED' }

  return { allowed: true, reason: 'ALLOWED' }
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
