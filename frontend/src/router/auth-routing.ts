import type { RouteLocationRaw } from 'vue-router'

import type { CurrentUser } from '@/types/auth'

export type WorkbenchRouteName = 'user-home' | 'merchant-home' | 'admin-home'

const adminRoles = new Set(['PLATFORM_ADMIN', 'KB_ADMIN', 'OPS_ADMIN', 'MODEL_ADMIN'])
const merchantRoles = new Set(['MERCHANT_ADMIN', 'MERCHANT_OPERATOR'])

export function resolveWorkbenchRouteName(user: CurrentUser): WorkbenchRouteName {
  const roles = new Set(user.roles.map((role) => role.code.trim().toUpperCase()))
  if ([...roles].some((role) => adminRoles.has(role))) return 'admin-home'
  if ([...roles].some((role) => merchantRoles.has(role))) return 'merchant-home'
  return 'user-home'
}

export function canAccessRoles(user: CurrentUser, requiredRoles?: string[]): boolean {
  if (!requiredRoles?.length) return true
  const roles = new Set(user.roles.map((role) => role.code.trim().toUpperCase()))
  if (roles.has('PLATFORM_ADMIN')) return true
  if (requiredRoles.length === 1 && requiredRoles[0] === 'USER') {
    return ![...roles].some((role) => adminRoles.has(role) || merchantRoles.has(role))
  }
  return requiredRoles.some((role) => roles.has(role.trim().toUpperCase()))
}

export function safeRedirect(value: unknown): RouteLocationRaw | undefined {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return undefined
  return value
}

export function loginRouteFor(redirect: string): RouteLocationRaw {
  return {
    name: 'login',
    query: { redirect: safeRedirect(redirect) ?? '/app' },
  }
}
