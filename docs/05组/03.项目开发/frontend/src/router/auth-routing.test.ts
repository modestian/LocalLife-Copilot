import { describe, expect, it } from 'vitest'

import type { CurrentUser } from '@/types/auth'

import {
  canAccessRoles,
  loginRouteFor,
  resolveWorkbenchRouteName,
  safeRedirect,
} from './auth-routing'

function userWithRole(code: string): CurrentUser {
  return {
    id: 'user-id',
    username: 'tester',
    display_name: '测试用户',
    email: null,
    department_id: null,
    roles: [{ code, name: code }],
    permissions: [],
    resource_scopes: [],
  }
}

describe('role routing', () => {
  it.each([
    ['USER', 'user-home'],
    ['MERCHANT_ADMIN', 'merchant-uid'],
    ['KB_ADMIN', 'admin-home'],
    ['PLATFORM_ADMIN', 'admin-home'],
  ] as const)('routes %s to %s', (role, routeName) => {
    expect(resolveWorkbenchRouteName(userWithRole(role))).toBe(routeName)
  })

  it('keeps user, merchant, and admin workspaces mutually exclusive', () => {
    expect(canAccessRoles(
      userWithRole('PLATFORM_ADMIN'),
      ['PLATFORM_ADMIN', 'KB_ADMIN'],
    )).toBe(true)
    expect(canAccessRoles(userWithRole('PLATFORM_ADMIN'), ['MERCHANT_ADMIN'])).toBe(false)
    expect(canAccessRoles(userWithRole('PLATFORM_ADMIN'), ['USER'])).toBe(false)
    expect(canAccessRoles(userWithRole('MERCHANT_ADMIN'), ['MERCHANT_ADMIN'])).toBe(true)
    expect(canAccessRoles(userWithRole('MERCHANT_ADMIN'), ['USER'])).toBe(false)
    expect(canAccessRoles(userWithRole('USER'), ['KB_ADMIN'])).toBe(false)
  })

  it('treats unrecognized non-privileged roles as user workspace roles', () => {
    const user = userWithRole('REGION_READER')

    expect(resolveWorkbenchRouteName(user)).toBe('user-home')
    expect(canAccessRoles(user, ['USER'])).toBe(true)
  })

  it('only accepts local absolute redirect paths', () => {
    expect(safeRedirect('/app?from=login')).toBe('/app?from=login')
    expect(safeRedirect('//example.com')).toBeUndefined()
    expect(safeRedirect('https://example.com')).toBeUndefined()
  })

  it('builds a login route for guest operations without allowing external redirects', () => {
    expect(loginRouteFor('/app?scene=date')).toEqual({
      name: 'login',
      query: { redirect: '/app?scene=date' },
    })
    expect(loginRouteFor('//example.com')).toEqual({
      name: 'login',
      query: { redirect: '/app' },
    })
  })
})
