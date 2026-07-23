<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { getUserFacingError } from '@/api/errors'
import { identityManagementApi } from '@/api/identity-management'
import ProductTopBar from '@/components/ProductTopBar.vue'
import { useAuthStore } from '@/stores/auth'
import type {
  ManagedPermission,
  ManagedResourceGrant,
  ManagedResourceType,
  ManagedRole,
  ManagedUser,
  ManagedUserStatus,
} from '@/types/identity-management'

type Tab = 'users' | 'roles'
const router = useRouter()

const authStore = useAuthStore()
const tab = ref<Tab>('users')
const users = ref<ManagedUser[]>([])
const roles = ref<ManagedRole[]>([])
const permissions = ref<ManagedPermission[]>([])
const total = ref(0)
const page = ref(1)
const query = ref('')
const status = ref<ManagedUserStatus | ''>('')
const loading = ref(false)
const saving = ref(false)
const errorMessage = ref('')
const notice = ref('')

const selectedUser = ref<ManagedUser | null>(null)
const editDisplayName = ref('')
const editEmail = ref('')
const editDepartmentId = ref('')
const editStatus = ref<ManagedUserStatus>('ACTIVE')
const editRoleIds = ref<string[]>([])
const editGrants = ref('')
const resetPassword = ref('')

const showCreateUser = ref(false)
const createUsername = ref('')
const createDisplayName = ref('')
const createEmail = ref('')
const createDepartmentId = ref('')
const createPassword = ref('')
const createRoleIds = ref<string[]>([])

const selectedRole = ref<ManagedRole | null>(null)
const editPermissionIds = ref<string[]>([])
const createRoleCode = ref('')
const createRoleName = ref('')
const createPermissionIds = ref<string[]>([])

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / 20)))
const permissionGroups = computed(() => {
  const groups = new Map<string, ManagedPermission[]>()
  for (const permission of permissions.value) {
    const values = groups.get(permission.resource_type) ?? []
    values.push(permission)
    groups.set(permission.resource_type, values)
  }
  return [...groups.entries()]
})

function formatDate(value: string | null): string {
  if (!value) return '从未登录'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function grantsToText(grants: ManagedResourceGrant[]): string {
  return grants
    .map((grant) => `${grant.resource_type}|${grant.resource_id}|${grant.actions.join(',')}`)
    .join('\n')
}

function parseGrants(value: string): ManagedResourceGrant[] {
  if (!value.trim()) return []
  return value.split('\n').filter((line) => line.trim()).map((line, index) => {
    const [resourceType, resourceId, actions] = line.split('|').map((part) => part.trim())
    if (
      !['KNOWLEDGE_BASE', 'MERCHANT', 'REGION'].includes(resourceType)
      || !resourceId
      || !actions
    ) {
      throw new Error(`第 ${index + 1} 行资源授权格式不正确`)
    }
    return {
      resource_type: resourceType as ManagedResourceType,
      resource_id: resourceId,
      actions: actions.split(',').map((action) => action.trim().toUpperCase()).filter(Boolean),
    }
  })
}

function selectUser(user: ManagedUser): void {
  selectedUser.value = user
  editDisplayName.value = user.display_name
  editEmail.value = user.email ?? ''
  editDepartmentId.value = user.department_id ?? ''
  editStatus.value = user.status
  editRoleIds.value = user.roles.map((role) => role.id)
  editGrants.value = grantsToText(user.resource_scopes)
  resetPassword.value = ''
  notice.value = ''
}

function selectRole(role: ManagedRole): void {
  selectedRole.value = role
  editPermissionIds.value = role.permissions.map((permission) => permission.id)
  notice.value = ''
}

async function loadUsers(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await identityManagementApi.listUsers({
      query: query.value.trim() || undefined,
      status: status.value || undefined,
      page: page.value,
      page_size: 20,
    })
    users.value = result.items
    total.value = result.total
    if (selectedUser.value) {
      const fresh = result.items.find((user) => user.id === selectedUser.value?.id)
      if (fresh) selectUser(fresh)
    }
  } catch (error) {
    errorMessage.value = getUserFacingError(error, '账号列表加载失败')
  } finally {
    loading.value = false
  }
}

async function loadCatalogs(): Promise<void> {
  try {
    const [roleResult, permissionResult] = await Promise.all([
      identityManagementApi.listRoles(),
      identityManagementApi.listPermissions(),
    ])
    roles.value = roleResult.items
    permissions.value = permissionResult.items
  } catch (error) {
    errorMessage.value = getUserFacingError(error, '角色与权限字典加载失败')
  }
}

async function search(): Promise<void> {
  page.value = 1
  await loadUsers()
}

async function createUser(): Promise<void> {
  saving.value = true
  errorMessage.value = ''
  try {
    const created = await identityManagementApi.createUser({
      username: createUsername.value,
      display_name: createDisplayName.value,
      password: createPassword.value,
      email: createEmail.value || null,
      department_id: createDepartmentId.value || null,
      role_ids: createRoleIds.value,
      resource_grants: [],
    })
    showCreateUser.value = false
    createUsername.value = ''
    createDisplayName.value = ''
    createEmail.value = ''
    createDepartmentId.value = ''
    createPassword.value = ''
    createRoleIds.value = []
    notice.value = `账号 ${created.username} 已创建`
    await loadUsers()
    selectUser(created)
  } catch (error) {
    errorMessage.value = getUserFacingError(error, '账号创建失败')
  } finally {
    saving.value = false
  }
}

async function saveUserProfile(): Promise<void> {
  if (!selectedUser.value) return
  saving.value = true
  try {
    const updated = await identityManagementApi.updateUser(selectedUser.value.id, {
      display_name: editDisplayName.value,
      email: editEmail.value || null,
      department_id: editDepartmentId.value || null,
      status: editStatus.value,
    })
    notice.value = '账号基本信息已保存；状态变化会使已有会话失效'
    selectUser(updated)
    await loadUsers()
  } catch (error) {
    errorMessage.value = getUserFacingError(error, '账号更新失败')
  } finally {
    saving.value = false
  }
}

async function saveUserAccess(): Promise<void> {
  if (!selectedUser.value) return
  saving.value = true
  try {
    const updated = await identityManagementApi.replaceUserAccess(selectedUser.value.id, {
      role_ids: editRoleIds.value,
      resource_grants: parseGrants(editGrants.value),
    })
    notice.value = '角色和资源授权已更新，账号已有会话已撤销'
    selectUser(updated)
    await loadUsers()
  } catch (error) {
    errorMessage.value = getUserFacingError(error, '授权更新失败')
  } finally {
    saving.value = false
  }
}

async function submitPasswordReset(): Promise<void> {
  if (!selectedUser.value || !resetPassword.value) return
  saving.value = true
  errorMessage.value = ''
  notice.value = ''
  try {
    const userId = selectedUser.value.id
    await identityManagementApi.resetPassword(userId, resetPassword.value)
    resetPassword.value = ''
    if (userId === authStore.currentUser?.id) {
      authStore.clearSession()
      await router.replace({ name: 'login', query: { passwordChanged: '1' } })
      return
    }
    notice.value = '密码已重置，账号已有会话已全部撤销'
  } catch (error) {
    errorMessage.value = getUserFacingError(error, '密码重置失败')
  } finally {
    saving.value = false
  }
}

async function deleteSelectedUser(): Promise<void> {
  if (
    !selectedUser.value
    || !window.confirm(`确认逻辑删除账号“${selectedUser.value.username}”？`)
  ) return
  saving.value = true
  try {
    await identityManagementApi.deleteUser(selectedUser.value.id)
    notice.value = '账号已逻辑删除，已有会话已撤销'
    selectedUser.value = null
    await loadUsers()
  } catch (error) {
    errorMessage.value = getUserFacingError(error, '账号删除失败')
  } finally {
    saving.value = false
  }
}

async function createRole(): Promise<void> {
  saving.value = true
  try {
    const created = await identityManagementApi.createRole({
      code: createRoleCode.value,
      name: createRoleName.value,
      permission_ids: createPermissionIds.value,
    })
    createRoleCode.value = ''
    createRoleName.value = ''
    createPermissionIds.value = []
    notice.value = `角色 ${created.code} 已创建`
    await loadCatalogs()
    selectRole(created)
  } catch (error) {
    errorMessage.value = getUserFacingError(error, '角色创建失败')
  } finally {
    saving.value = false
  }
}

async function saveRolePermissions(): Promise<void> {
  if (!selectedRole.value) return
  saving.value = true
  try {
    const updated = await identityManagementApi.replaceRolePermissions(
      selectedRole.value.id,
      editPermissionIds.value,
    )
    notice.value = '角色权限矩阵已保存'
    await loadCatalogs()
    selectRole(updated)
  } catch (error) {
    errorMessage.value = getUserFacingError(error, '角色权限保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadUsers(), loadCatalogs()])
})
</script>

<template>
  <main class="identity-page">
    <ProductTopBar active="admin" />
    <section class="hero">
      <span class="eyebrow">IDENTITY & ACCESS</span>
      <h1>身份与权限管理</h1>
      <p>集中维护账号生命周期、角色权限和知识库、商家、区域资源范围。所有变更均写入审计日志。</p>
      <div class="safety-note">
        仅平台管理员可操作；不能停用、删除或移除最后一个平台管理员。
      </div>
    </section>

    <nav
      class="tabs"
      aria-label="身份管理功能"
    >
      <button
        :class="{ active: tab === 'users' }"
        type="button"
        @click="tab = 'users'"
      >
        账号管理
      </button>
      <button
        :class="{ active: tab === 'roles' }"
        type="button"
        @click="tab = 'roles'"
      >
        角色与权限
      </button>
    </nav>

    <p
      v-if="notice"
      class="notice"
      role="status"
    >
      {{ notice }}
    </p>
    <p
      v-if="errorMessage"
      class="error"
      role="alert"
    >
      {{ errorMessage }}
    </p>

    <template v-if="tab === 'users'">
      <section class="toolbar">
        <input
          v-model="query"
          type="search"
          placeholder="搜索用户名、姓名或邮箱"
          @keyup.enter="search"
        >
        <select v-model="status">
          <option value="">
            全部状态
          </option>
          <option value="ACTIVE">
            正常
          </option>
          <option value="DISABLED">
            已停用
          </option>
          <option value="LOCKED">
            已锁定
          </option>
        </select>
        <button
          class="primary"
          type="button"
          @click="search"
        >
          查询
        </button>
        <button
          type="button"
          @click="showCreateUser = !showCreateUser"
        >
          新建账号
        </button>
      </section>

      <form
        v-if="showCreateUser"
        class="editor create-grid"
        @submit.prevent="createUser"
      >
        <h2>新建账号</h2>
        <label>用户名<input
          v-model="createUsername"
          required
          minlength="3"
        ></label>
        <label>显示名称<input
          v-model="createDisplayName"
          required
        ></label>
        <label>邮箱<input
          v-model="createEmail"
          type="email"
        ></label>
        <label>部门 / 租户 ID<input
          v-model="createDepartmentId"
          placeholder="可选 UUID"
        ></label>
        <label>初始密码<input
          v-model="createPassword"
          required
          type="password"
          minlength="12"
        ></label>
        <fieldset>
          <legend>初始角色</legend>
          <label
            v-for="role in roles"
            :key="role.id"
            class="check"
          >
            <input
              v-model="createRoleIds"
              type="checkbox"
              :value="role.id"
            >{{ role.name }}
          </label>
        </fieldset>
        <button
          class="primary"
          type="submit"
          :disabled="saving || !createRoleIds.length"
        >
          创建账号
        </button>
      </form>

      <div class="workspace">
        <section class="table-card">
          <table>
            <thead><tr><th>账号</th><th>角色</th><th>状态</th><th>最近登录</th></tr></thead>
            <tbody>
              <tr
                v-for="user in users"
                :key="user.id"
                :class="{ selected: selectedUser?.id === user.id }"
                @click="selectUser(user)"
              >
                <td><strong>{{ user.display_name }}</strong><small>{{ user.username }}<br>{{ user.email || '未设置邮箱' }}</small></td>
                <td>{{ user.roles.map((role) => role.name).join('、') }}</td>
                <td><span :class="['status', user.status.toLowerCase()]">{{ user.status }}</span></td>
                <td>{{ formatDate(user.last_login_at) }}</td>
              </tr>
            </tbody>
          </table>
          <p
            v-if="loading"
            class="empty"
          >
            正在加载…
          </p>
          <p
            v-else-if="!users.length"
            class="empty"
          >
            没有符合条件的账号
          </p>
          <footer>
            <span>共 {{ total }} 个账号，第 {{ page }} / {{ totalPages }} 页</span>
            <button
              type="button"
              :disabled="page <= 1"
              @click="page--; loadUsers()"
            >
              上一页
            </button>
            <button
              type="button"
              :disabled="page >= totalPages"
              @click="page++; loadUsers()"
            >
              下一页
            </button>
          </footer>
        </section>

        <aside
          v-if="selectedUser"
          class="editor"
        >
          <h2>{{ selectedUser.username }}</h2>
          <label>显示名称<input v-model="editDisplayName"></label>
          <label>邮箱<input
            v-model="editEmail"
            type="email"
          ></label>
          <label>账号状态
            <label>部门 / 租户 ID<input
              v-model="editDepartmentId"
              placeholder="可选 UUID"
            ></label>
            <select v-model="editStatus">
              <option value="ACTIVE">正常</option>
              <option value="DISABLED">停用</option>
              <option value="LOCKED">锁定</option>
            </select>
          </label>
          <button
            class="primary"
            type="button"
            :disabled="saving"
            @click="saveUserProfile"
          >
            保存基本信息
          </button>

          <fieldset>
            <legend>角色</legend>
            <label
              v-for="role in roles"
              :key="role.id"
              class="check"
            >
              <input
                v-model="editRoleIds"
                type="checkbox"
                :value="role.id"
              >{{ role.name }}
              <small>{{ role.code }}</small>
            </label>
          </fieldset>
          <label>资源授权
            <textarea
              v-model="editGrants"
              rows="5"
              placeholder="每行：MERCHANT|资源 UUID|READ,UPDATE"
            />
          </label>
          <small>支持 KNOWLEDGE_BASE、MERCHANT、REGION；保存授权后会撤销该账号已有会话。</small>
          <button
            class="primary"
            type="button"
            :disabled="saving || !editRoleIds.length"
            @click="saveUserAccess"
          >
            保存角色与资源授权
          </button>

          <label>重置密码<input
            v-model="resetPassword"
            type="password"
            minlength="12"
            placeholder="至少 12 位"
          ></label>
          <button
            type="button"
            :disabled="saving || resetPassword.length < 12"
            @click="submitPasswordReset"
          >
            重置并撤销会话
          </button>
          <button
            class="danger"
            type="button"
            :disabled="saving || selectedUser.id === authStore.currentUser?.id"
            @click="deleteSelectedUser"
          >
            逻辑删除账号
          </button>
        </aside>
        <aside
          v-else
          class="editor empty"
        >
          选择一个账号查看和编辑
        </aside>
      </div>
    </template>

    <template v-else>
      <div class="workspace roles-workspace">
        <section class="table-card">
          <button
            v-for="role in roles"
            :key="role.id"
            class="role-row"
            :class="{ selected: selectedRole?.id === role.id }"
            type="button"
            @click="selectRole(role)"
          >
            <span><strong>{{ role.name }}</strong><small>{{ role.code }}</small></span>
            <span>{{ role.permissions.length }} 项权限 · {{ role.is_system ? '系统角色' : '自定义角色' }}</span>
          </button>
        </section>
        <aside class="editor">
          <template v-if="selectedRole">
            <h2>{{ selectedRole.name }}权限</h2>
            <fieldset
              v-for="[resourceType, values] in permissionGroups"
              :key="resourceType"
            >
              <legend>{{ resourceType }}</legend>
              <label
                v-for="permission in values"
                :key="permission.id"
                class="check"
              >
                <input
                  v-model="editPermissionIds"
                  type="checkbox"
                  :value="permission.id"
                >
                {{ permission.action }} <small>{{ permission.code }}</small>
              </label>
            </fieldset>
            <button
              class="primary"
              type="button"
              :disabled="saving"
              @click="saveRolePermissions"
            >
              保存权限矩阵
            </button>
          </template>
          <template v-else>
            <h2>创建自定义角色</h2>
            <label>角色编码<input
              v-model="createRoleCode"
              placeholder="例如 CONTENT_REVIEWER"
            ></label>
            <label>角色名称<input
              v-model="createRoleName"
              placeholder="例如 内容审核员"
            ></label>
            <fieldset
              v-for="[resourceType, values] in permissionGroups"
              :key="resourceType"
            >
              <legend>{{ resourceType }}</legend>
              <label
                v-for="permission in values"
                :key="permission.id"
                class="check"
              >
                <input
                  v-model="createPermissionIds"
                  type="checkbox"
                  :value="permission.id"
                >
                {{ permission.action }}
              </label>
            </fieldset>
            <button
              class="primary"
              type="button"
              :disabled="saving || !createRoleCode || !createRoleName"
              @click="createRole"
            >
              创建角色
            </button>
          </template>
          <button
            v-if="selectedRole"
            type="button"
            @click="selectedRole = null"
          >
            切换到创建角色
          </button>
        </aside>
      </div>
    </template>
  </main>
</template>

<style scoped>
.identity-page { width: min(1240px, calc(100% - 48px)); margin: 0 auto; padding: 28px 0 72px; color: #352a24; }
.hero { padding: 46px 0 26px; }
.hero h1 { margin: 10px 0; font-size: clamp(2.3rem, 5vw, 4.2rem); letter-spacing: -.06em; }
.hero p { max-width: 760px; color: #76675e; line-height: 1.7; }
.safety-note, .notice, .error { border-radius: 10px; padding: 11px 14px; font-size: .84rem; }
.safety-note { display: inline-block; background: #fff3e9; color: #9d4b27; }
.notice { background: #edf8f0; color: #287140; }
.error { background: #fff0ed; color: #a1372a; }
.tabs { display: flex; gap: 8px; margin: 12px 0 20px; border-bottom: 1px solid #e8ded7; }
.tabs button { border: 0; border-bottom: 3px solid transparent; padding: 12px 18px; background: transparent; color: #786a60; font-weight: 800; cursor: pointer; }
.tabs button.active { border-color: #ef5a37; color: #bc4129; }
.toolbar { display: grid; grid-template-columns: minmax(260px, 1fr) 180px auto auto; gap: 10px; margin-bottom: 16px; }
input, select, textarea { width: 100%; box-sizing: border-box; border: 1px solid #d9ccc1; border-radius: 9px; padding: 9px 11px; background: #fffdfa; color: inherit; font: inherit; }
button { border: 1px solid #d8c9bd; border-radius: 9px; padding: 9px 14px; background: #fffdfa; color: #654d40; font-weight: 800; cursor: pointer; }
button:disabled { cursor: not-allowed; opacity: .46; }
button.primary { border-color: #e85635; background: linear-gradient(135deg, #ff7542, #e44d31); color: #fff; }
button.danger { border-color: #d99b90; color: #a63125; }
.workspace { display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(330px, .85fr); gap: 18px; align-items: start; }
.table-card, .editor { overflow: hidden; border: 1px solid #e9e0da; border-radius: 14px; background: #fff; box-shadow: 0 10px 26px rgb(65 47 34 / 5%); }
table { width: 100%; border-collapse: collapse; text-align: left; }
th { padding: 12px 14px; background: #faf7f5; color: #867970; font-size: .74rem; }
td { border-top: 1px solid #f0e9e4; padding: 14px; font-size: .84rem; vertical-align: top; cursor: pointer; }
tr.selected td { background: #fff5ef; }
td strong, td small, .role-row strong, .role-row small { display: block; }
td small, .role-row small, .editor small { margin-top: 4px; color: #8a7d74; line-height: 1.45; }
.status { border-radius: 999px; padding: 4px 8px; font-size: .7rem; font-weight: 850; }
.status.active { background: #e8f6ec; color: #287140; }
.status.disabled, .status.locked { background: #f2edeb; color: #8a5148; }
.table-card footer { display: flex; gap: 9px; align-items: center; justify-content: flex-end; border-top: 1px solid #eee6e0; padding: 12px; font-size: .78rem; }
.table-card footer span { margin-right: auto; }
.editor { display: grid; gap: 13px; padding: 20px; }
.editor h2 { margin: 0; }
.editor label { display: grid; gap: 6px; color: #67564b; font-size: .8rem; font-weight: 800; }
.editor fieldset { display: grid; gap: 8px; border: 1px solid #e7ddd6; border-radius: 10px; padding: 12px; }
.editor legend { padding: 0 6px; color: #5e4b40; font-size: .8rem; font-weight: 850; }
.editor label.check { display: flex; gap: 7px; align-items: center; font-weight: 650; }
.check input { width: auto; }
.check small { margin-left: auto; }
.create-grid { grid-template-columns: repeat(2, 1fr); margin-bottom: 18px; }
.create-grid h2, .create-grid fieldset { grid-column: 1 / -1; }
.empty { padding: 38px; color: #8a7d74; text-align: center; }
.role-row { display: flex; width: 100%; justify-content: space-between; border: 0; border-bottom: 1px solid #eee6e0; border-radius: 0; padding: 17px; text-align: left; }
.role-row.selected { background: #fff3ec; }
@media (max-width: 900px) { .workspace, .toolbar, .create-grid { grid-template-columns: 1fr; }.create-grid h2, .create-grid fieldset { grid-column: auto; } }
</style>
