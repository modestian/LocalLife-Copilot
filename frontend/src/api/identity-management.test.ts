import { beforeEach, describe, expect, it, vi } from 'vitest'

import { requestData } from './client'
import { identityManagementApi } from './identity-management'

vi.mock('./client', () => ({ requestData: vi.fn() }))

describe('identity management API', () => {
  beforeEach(() => {
    vi.mocked(requestData).mockReset().mockResolvedValue({})
  })

  it('uses the documented account lifecycle routes', async () => {
    await identityManagementApi.listUsers({ query: 'demo', status: 'ACTIVE', page: 1 })
    await identityManagementApi.updateUser('user/id', { status: 'DISABLED' })
    await identityManagementApi.replaceUserAccess('user/id', {
      role_ids: ['role-1'],
      resource_grants: [],
    })
    await identityManagementApi.resetPassword('user/id', 'new-secure-password')

    expect(requestData).toHaveBeenNthCalledWith(1, {
      method: 'GET',
      url: '/api/v1/users',
      params: { query: 'demo', status: 'ACTIVE', page: 1 },
    })
    expect(requestData).toHaveBeenNthCalledWith(2, {
      method: 'PATCH',
      url: '/api/v1/users/user%2Fid',
      data: { status: 'DISABLED' },
    })
    expect(requestData).toHaveBeenNthCalledWith(3, {
      method: 'PUT',
      url: '/api/v1/users/user%2Fid/roles',
      data: { role_ids: ['role-1'], resource_grants: [] },
    })
    expect(requestData).toHaveBeenNthCalledWith(4, {
      method: 'POST',
      url: '/api/v1/users/user%2Fid/reset-password',
      data: { password: 'new-secure-password' },
    })
  })

  it('supports role permission replacement', async () => {
    await identityManagementApi.replaceRolePermissions('role/id', ['permission-1'])

    expect(requestData).toHaveBeenCalledWith({
      method: 'PUT',
      url: '/api/v1/roles/role%2Fid/permissions',
      data: { permission_ids: ['permission-1'] },
    })
  })
})
