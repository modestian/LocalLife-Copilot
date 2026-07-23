export type ManagedUserStatus = 'ACTIVE' | 'DISABLED' | 'LOCKED'
export type ManagedResourceType = 'KNOWLEDGE_BASE' | 'MERCHANT' | 'REGION'

export interface ManagedPermission {
  id: string
  code: string
  resource_type: string
  action: string
}

export interface ManagedRole {
  id: string
  code: string
  name: string
  is_system: boolean
  status: 'ACTIVE' | 'DISABLED'
  permissions: ManagedPermission[]
}

export interface ManagedResourceGrant {
  resource_type: ManagedResourceType
  resource_id: string
  actions: string[]
}

export interface ManagedUser {
  id: string
  username: string
  display_name: string
  email: string | null
  department_id: string | null
  status: ManagedUserStatus
  roles: Pick<ManagedRole, 'id' | 'code' | 'name'>[]
  resource_scopes: ManagedResourceGrant[]
  last_login_at: string | null
  created_at: string
  updated_at: string
}

export interface ManagedUserPage {
  items: ManagedUser[]
  total: number
  page: number
  page_size: number
}

export interface UserAccessPayload {
  role_ids: string[]
  resource_grants: ManagedResourceGrant[]
}
