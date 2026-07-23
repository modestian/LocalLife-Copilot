import type {
  ManagedPermission,
  ManagedResourceGrant,
  ManagedRole,
  ManagedUser,
  ManagedUserPage,
  ManagedUserStatus,
  UserAccessPayload,
} from '@/types/identity-management'

import { requestData } from './client'

export const identityManagementApi = {
  listUsers(params: {
    query?: string
    status?: ManagedUserStatus
    page?: number
    page_size?: number
  }): Promise<ManagedUserPage> {
    return requestData({ method: 'GET', url: '/api/v1/users', params })
  },

  createUser(payload: {
    username: string
    display_name: string
    password: string
    email?: string | null
    department_id?: string | null
    role_ids: string[]
    resource_grants: ManagedResourceGrant[]
  }): Promise<ManagedUser> {
    return requestData({ method: 'POST', url: '/api/v1/users', data: payload })
  },

  updateUser(
    id: string,
    payload: Partial<Pick<ManagedUser, 'display_name' | 'email' | 'department_id' | 'status'>>,
  ): Promise<ManagedUser> {
    return requestData({
      method: 'PATCH',
      url: `/api/v1/users/${encodeURIComponent(id)}`,
      data: payload,
    })
  },

  deleteUser(id: string): Promise<{ id: string; status: 'DELETED' }> {
    return requestData({
      method: 'DELETE',
      url: `/api/v1/users/${encodeURIComponent(id)}`,
    })
  },

  resetPassword(id: string, password: string): Promise<{ sessions_revoked: boolean }> {
    return requestData({
      method: 'POST',
      url: `/api/v1/users/${encodeURIComponent(id)}/reset-password`,
      data: { password },
    })
  },

  replaceUserAccess(id: string, payload: UserAccessPayload): Promise<ManagedUser> {
    return requestData({
      method: 'PUT',
      url: `/api/v1/users/${encodeURIComponent(id)}/roles`,
      data: payload,
    })
  },

  listRoles(): Promise<{ items: ManagedRole[] }> {
    return requestData({ method: 'GET', url: '/api/v1/roles' })
  },

  createRole(payload: {
    code: string
    name: string
    permission_ids: string[]
  }): Promise<ManagedRole> {
    return requestData({ method: 'POST', url: '/api/v1/roles', data: payload })
  },

  replaceRolePermissions(id: string, permission_ids: string[]): Promise<ManagedRole> {
    return requestData({
      method: 'PUT',
      url: `/api/v1/roles/${encodeURIComponent(id)}/permissions`,
      data: { permission_ids },
    })
  },

  listPermissions(): Promise<{ items: ManagedPermission[] }> {
    return requestData({ method: 'GET', url: '/api/v1/permissions' })
  },
}
