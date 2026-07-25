<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import ProductTopBar from '@/components/ProductTopBar.vue'
import { useAuthStore } from '@/stores/auth'
import { useKnowledgeBaseStore } from '@/stores/knowledge-base'
import type { KnowledgeBaseStatus } from '@/types/knowledge-base'
import {
  canCreateKnowledgeBase,
  canDeleteKnowledgeBase,
  canUpdateKnowledgeBase,
  knowledgeBaseAccessLabel,
} from '@/utils/knowledge-base-permissions'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const store = useKnowledgeBaseStore()

const isPlatformAdmin = computed(
  () => authStore.currentUser?.roles.some((role) => role.code === 'PLATFORM_ADMIN') ?? false,
)
const canCreate = computed(() => canCreateKnowledgeBase(authStore.currentUser))
const tenantId = ref(
  typeof route.query.tenant_id === 'string'
    ? route.query.tenant_id
    : authStore.currentUser?.department_id ?? '',
)
const departmentId = ref(
  typeof route.query.department_id === 'string' ? route.query.department_id : '',
)
const name = ref(typeof route.query.name === 'string' ? route.query.name : '')
const status = ref<KnowledgeBaseStatus | ''>(
  ['ACTIVE', 'ARCHIVED', 'DELETED'].includes(String(route.query.status))
    ? route.query.status as KnowledgeBaseStatus
    : '',
)
const page = ref(Math.max(1, Number(route.query.page) || 1))
const totalPages = computed(() => Math.max(1, Math.ceil(store.total / store.pageSize)))

// Create modal state
const showCreateModal = ref(false)
const createFormError = ref('')
const createForm = reactive({
  name: '',
  description: '',
  department_id: '',
  owner_id: '',
  embedding_model_id: '',
  chunk_size: 500,
  chunk_overlap: 80,
})

function statusLabel(value: KnowledgeBaseStatus): string {
  return { ACTIVE: '启用', ARCHIVED: '已归档', DELETED: '已删除' }[value]
}

function formatDate(value: string): string {
  if (!value) return '暂无更新时间'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? '暂无更新时间'
    : date.toLocaleString('zh-CN', { hour12: false })
}

function accessLabel(id: string): string {
  return knowledgeBaseAccessLabel(canUpdateKnowledgeBase(authStore.currentUser, id))
}

function ownerLabel(ownerName: string, ownerId: string): string {
  if (ownerName.trim()) return ownerName
  return `用户 · ${ownerId.slice(-8)}`
}

async function load(): Promise<void> {
  await router.replace({
    query: {
      ...(name.value.trim() ? { name: name.value.trim() } : {}),
      ...(status.value ? { status: status.value } : {}),
      ...(isPlatformAdmin.value && tenantId.value.trim()
        ? { tenant_id: tenantId.value.trim() }
        : {}),
      ...(departmentId.value.trim() ? { department_id: departmentId.value.trim() } : {}),
      ...(page.value > 1 ? { page: String(page.value) } : {}),
    },
  })
  await store.loadList({
    name: name.value.trim() || undefined,
    status: status.value || undefined,
    tenant_id:
      isPlatformAdmin.value && tenantId.value.trim() ? tenantId.value.trim() : undefined,
    department_id: departmentId.value.trim() || undefined,
    page: page.value,
    page_size: 10,
  })
}

async function search(): Promise<void> {
  page.value = 1
  await load()
}

async function changePage(nextPage: number): Promise<void> {
  if (nextPage < 1 || nextPage > totalPages.value || nextPage === page.value) return
  page.value = nextPage
  await load()
}

function openCreateModal(): void {
  if (!canCreate.value.allowed) return
  createFormError.value = ''
  createForm.name = ''
  createForm.description = ''
  createForm.department_id = ''
  createForm.owner_id = ''
  createForm.embedding_model_id = ''
  createForm.chunk_size = 500
  createForm.chunk_overlap = 80
  showCreateModal.value = true
}

function closeCreateModal(): void {
  showCreateModal.value = false
  createFormError.value = ''
}

async function submitCreate(): Promise<void> {
  createFormError.value = ''
  if (!createForm.name.trim()) {
    createFormError.value = '知识库名称不能为空。'
    return
  }
  if (!createForm.embedding_model_id.trim()) {
    createFormError.value = '默认 Embedding 模型 ID 不能为空。'
    return
  }
  if (createForm.chunk_size < 100 || createForm.chunk_size > 4000) {
    createFormError.value = '切分大小必须在 100 到 4000 之间。'
    return
  }
  if (createForm.chunk_overlap < 0 || createForm.chunk_overlap >= createForm.chunk_size) {
    createFormError.value = '重叠大小必须为非负数且小于切分大小。'
    return
  }

  try {
    await store.createKnowledgeBase({
      name: createForm.name.trim(),
      description: createForm.description.trim() || null,
      department_id: createForm.department_id.trim() || null,
      owner_id: createForm.owner_id.trim() || null,
      embedding_model_id: createForm.embedding_model_id.trim(),
      chunk_size: createForm.chunk_size,
      chunk_overlap: createForm.chunk_overlap,
    })
    showCreateModal.value = false
    await load()
  } catch {
    createFormError.value = store.errorMessage
  }
}

// Inline delete state
const deletingId = ref<string | null>(null)
const deleteError = ref('')

function confirmInlineDelete(id: string): void {
  deletingId.value = id
  deleteError.value = ''
}

function cancelInlineDelete(): void {
  deletingId.value = null
  deleteError.value = ''
}

async function executeInlineDelete(id: string): Promise<void> {
  deleteError.value = ''
  try {
    await store.deleteKnowledgeBase(id)
    deletingId.value = null
    await load()
  } catch {
    deleteError.value = store.errorMessage
  }
}

onMounted(load)
</script>

<template>
  <main class="kb-page">
    <ProductTopBar active="admin" />

    <section class="kb-page__intro">
      <span class="eyebrow">KNOWLEDGE BASES</span>
      <h1>知识库管理</h1>
      <p>浏览知识库状态、文档与 Chunk 规模；编辑入口根据角色权限和资源授权动态开放。</p>
      <span :class="['permission-chip', { 'is-readonly': !authStore.isAuthenticated }]">
        {{ authStore.isAuthenticated ? '按资源授权' : '游客只读' }}
      </span>
    </section>

    <form
      class="filter-panel"
      aria-label="知识库筛选"
      @submit.prevent="search"
    >
      <label v-if="isPlatformAdmin">
        <span>租户上下文</span>
        <input
          v-model="tenantId"
          type="text"
          required
          placeholder="输入租户 UUID"
        >
      </label>
      <label>
        <span>部门</span>
        <input
          v-model="departmentId"
          type="text"
          placeholder="输入部门 UUID"
        >
      </label>
      <label>
        <span>名称</span>
        <input
          v-model="name"
          type="search"
          placeholder="输入知识库名称"
        >
      </label>
      <label>
        <span>状态</span>
        <select v-model="status">
          <option value="">全部状态</option>
          <option value="ACTIVE">启用</option>
          <option value="ARCHIVED">已归档</option>
          <option value="DELETED">已删除</option>
        </select>
      </label>
      <button
        class="button button--primary"
        type="submit"
        :disabled="store.loading"
      >
        查询
      </button>
      <button
        v-if="canCreate.allowed"
        class="button button--create"
        type="button"
        @click="openCreateModal"
      >
        + 新建知识库
      </button>
    </form>

    <section
      v-if="!authStore.isAuthenticated"
      class="readonly-banner"
      role="note"
    >
      <strong>当前为游客只读模式</strong>
      <span>可以查看列表和详情，不能编辑知识库配置。</span>
    </section>

    <section
      v-if="store.errorMessage"
      class="state-panel state-panel--error"
      role="alert"
    >
      <strong>无法加载知识库</strong>
      <p>{{ store.errorMessage }}</p>
      <button
        class="button button--secondary"
        type="button"
        @click="load"
      >
        重新加载
      </button>
    </section>

    <section
      v-else-if="store.loading"
      class="state-panel"
      aria-live="polite"
    >
      正在加载知识库…
    </section>

    <section
      v-else-if="store.items.length === 0"
      class="state-panel"
    >
      <strong>没有符合条件的知识库</strong>
      <p>请调整名称或状态筛选条件。</p>
    </section>

    <section
      v-else
      class="kb-table-wrap"
      aria-label="知识库列表"
    >
      <header class="kb-table-wrap__header">
        <div>
          <span class="eyebrow">LIBRARY OVERVIEW</span>
          <h2>知识资产概览</h2>
        </div>
        <strong>{{ store.total }} 个知识库</strong>
      </header>
      <table class="kb-table">
        <thead>
          <tr>
            <th>知识库</th>
            <th>状态</th>
            <th>文档 / Chunk</th>
            <th>负责人</th>
            <th>更新时间</th>
            <th>权限状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in store.items"
            :key="item.id"
          >
            <td>
              <router-link
                class="kb-table__name"
                :to="{ name: 'knowledge-base-detail', params: { id: item.id } }"
              >
                {{ item.name }}
              </router-link>
              <small>{{ item.description || '暂无描述' }}</small>
            </td>
            <td>
              <span :class="['status-chip', `is-${item.status.toLowerCase()}`]">
                {{ statusLabel(item.status) }}
              </span>
            </td>
            <td>
              <span class="metric-pair">
                <strong>{{ item.statistics.document_count }}</strong>
                <small>文档</small>
                <strong>{{ item.statistics.chunk_count }}</strong>
                <small>Chunk</small>
              </span>
            </td>
            <td>{{ ownerLabel(item.owner_name, item.owner_id) }}</td>
            <td>{{ formatDate(item.updated_at) }}</td>
            <td>
              <span
                :class="[
                  'permission-chip',
                  { 'is-allowed': canUpdateKnowledgeBase(authStore.currentUser, item.id).allowed },
                ]"
              >
                {{ accessLabel(item.id) }}
              </span>
            </td>
            <td>
              <button
                v-if="canDeleteKnowledgeBase(authStore.currentUser, item.id).allowed"
                class="button button--danger-sm"
                type="button"
                @click="confirmInlineDelete(item.id)"
              >
                删除
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer
      v-if="!store.errorMessage && store.total > 0"
      class="pagination"
    >
      <span>共 {{ store.total }} 条，第 {{ store.page }} / {{ totalPages }} 页</span>
      <div>
        <button
          class="button button--secondary"
          type="button"
          :disabled="page <= 1 || store.loading"
          @click="changePage(page - 1)"
        >
          上一页
        </button>
        <button
          class="button button--secondary"
          type="button"
          :disabled="page >= totalPages || store.loading"
          @click="changePage(page + 1)"
        >
          下一页
        </button>
      </div>
    </footer>

    <!-- Create Knowledge Base Modal -->
    <Teleport to="body">
      <div
        v-if="showCreateModal"
        class="modal-overlay"
        role="dialog"
        aria-modal="true"
        aria-label="新建知识库"
        @click.self="closeCreateModal"
      >
        <div class="modal-panel">
          <header class="modal-panel__header">
            <div>
              <span class="eyebrow">CREATE</span>
              <h2>新建知识库</h2>
            </div>
            <button
              class="modal-panel__close"
              type="button"
              aria-label="关闭"
              @click="closeCreateModal"
            >
              ✕
            </button>
          </header>
          <form class="modal-panel__form" @submit.prevent="submitCreate">
            <label>
              <span>知识库名称 *</span>
              <input
                v-model="createForm.name"
                maxlength="200"
                required
                placeholder="输入知识库名称"
              >
            </label>
            <label class="is-wide">
              <span>描述</span>
              <textarea
                v-model="createForm.description"
                rows="3"
                placeholder="知识库用途或说明"
              />
            </label>
            <label>
              <span>负责人 ID</span>
              <input
                v-model="createForm.owner_id"
                placeholder="输入用户 UUID（留空则为当前用户）"
              >
            </label>
            <label>
              <span>所属部门 ID</span>
              <input
                v-model="createForm.department_id"
                placeholder="输入部门 UUID"
              >
            </label>
            <label>
              <span>默认 Embedding 模型 ID *</span>
              <input
                v-model="createForm.embedding_model_id"
                required
                placeholder="输入模型版本 UUID"
              >
            </label>
            <label>
              <span>切分大小</span>
              <input
                v-model.number="createForm.chunk_size"
                type="number"
                min="100"
                max="4000"
              >
            </label>
            <label>
              <span>重叠大小</span>
              <input
                v-model.number="createForm.chunk_overlap"
                type="number"
                min="0"
              >
            </label>
            <p
              v-if="createFormError"
              class="form-message is-error"
              role="alert"
            >
              {{ createFormError }}
            </p>
            <div class="form-actions is-wide">
              <button
                class="button button--secondary"
                type="button"
                :disabled="store.saving"
                @click="closeCreateModal"
              >
                取消
              </button>
              <button
                class="button button--primary"
                type="submit"
                :disabled="store.saving"
              >
                {{ store.saving ? '创建中…' : '创建知识库' }}
              </button>
            </div>
          </form>
        </div>
      </div>
    </Teleport>

    <!-- Inline Delete Confirmation Modal -->
    <Teleport to="body">
      <div
        v-if="deletingId"
        class="modal-overlay"
        role="dialog"
        aria-modal="true"
        aria-label="确认删除知识库"
        @click.self="cancelInlineDelete"
      >
        <div class="modal-confirm">
          <header class="modal-confirm__header">
            <span class="eyebrow">⚠ 危险操作</span>
            <h2>确认删除知识库</h2>
          </header>
          <div class="modal-confirm__body">
            <p>
              你确定要删除该知识库吗？此操作不可恢复。
            </p>
            <p
              v-if="deleteError"
              class="form-message is-error"
              role="alert"
            >
              {{ deleteError }}
            </p>
          </div>
          <div class="modal-confirm__actions">
            <button
              class="button button--secondary"
              type="button"
              :disabled="store.saving"
              @click="cancelInlineDelete"
            >
              取消
            </button>
            <button
              class="button button--danger"
              type="button"
              :disabled="store.saving"
              @click="executeInlineDelete(deletingId!)"
            >
              {{ store.saving ? '删除中…' : '确认删除' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </main>
</template>

<style scoped>
.kb-page { width: min(1180px, calc(100% - 48px)); margin: 0 auto; padding: 28px 0 72px; }
.kb-page__header { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; padding-bottom: 22px; border-bottom: 1px solid #e8e8e8; }
.kb-page__brand { color: #28231f; font-size: .76rem; font-weight: 900; letter-spacing: .07em; text-decoration: none; }
.kb-page__breadcrumb { display: flex; gap: 8px; margin: 12px 0 0; color: #7b6d63; font-size: .82rem; }
.kb-page__header-actions { display: flex; gap: 12px; align-items: center; }
.kb-page__intro { padding: 46px 0 30px; }
.kb-page__intro h1 { margin: 12px 0; font-family: "PingFang SC", "Microsoft YaHei", sans-serif; font-size: clamp(2.25rem, 5vw, 4rem); font-weight: 800; letter-spacing: -.065em; }
.kb-page__intro p { max-width: 680px; margin: 0; color: var(--muted); line-height: 1.7; }
.filter-panel { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; align-items: end; padding: 20px; border: 1px solid #ebe6e1; border-radius: 14px; background: #fff; box-shadow: 0 10px 26px rgb(65 47 34 / 4%); }
.filter-panel label { display: grid; gap: 7px; color: #695b51; font-size: .8rem; font-weight: 800; }
.filter-panel input, .filter-panel select { width: 100%; min-height: 42px; border: 1px solid #d9ccc1; border-radius: 9px; padding: 8px 11px; background: #fffdfa; color: #392d26; font: inherit; }
.button { min-height: 40px; border-radius: 9px; padding: 8px 14px; cursor: pointer; font-weight: 800; text-decoration: none; }
.button:disabled { cursor: not-allowed; opacity: .48; }
.button--primary { border: 1px solid var(--brand); background: linear-gradient(135deg, #ff7b43, #ec4b30); color: white; box-shadow: 0 7px 16px rgb(176 60 39 / 14%); }
.button--secondary { border: 1px solid #d9ccc1; background: #fffdfa; color: #6c5042; }
.button--create { border: 1px solid #2c704b; background: linear-gradient(135deg, #4aad6a, #308c4f); color: white; box-shadow: 0 7px 16px rgb(44 112 75 / 14%); }
.button--danger-sm { min-height: 32px; border: 1px solid #c44; border-radius: 7px; padding: 5px 10px; background: linear-gradient(135deg, #e0554a, #b8382c); color: white; cursor: pointer; font-size: .76rem; font-weight: 800; box-shadow: 0 3px 8px rgb(184 56 44 / 12%); }
.button--danger-sm:hover { opacity: 0.88; }
.readonly-banner { display: flex; gap: 8px 20px; flex-wrap: wrap; margin: 18px 0; border-left: 3px solid var(--brand); padding: 12px 16px; background: rgb(255 255 255 / 52%); color: var(--muted); }
.readonly-banner strong { color: #9d3423; }
.state-panel { margin-top: 20px; border: 1px dashed #d5c6b9; border-radius: 14px; padding: 48px 24px; background: rgb(255 255 255 / 48%); color: #695b51; text-align: center; }
.state-panel p { margin: 8px 0 18px; }
.state-panel--error { border-color: #e3b3aa; background: #fff4f1; color: #8e3328; }
.kb-table-wrap { overflow-x: auto; margin-top: 20px; border: 1px solid #ebe6e1; border-radius: 14px; background: #fff; box-shadow: 0 10px 26px rgb(65 47 34 / 4%); }
.kb-table-wrap__header { display: flex; justify-content: space-between; gap: 20px; align-items: flex-end; padding: 20px 22px 16px; border-bottom: 1px solid #f0ece8; background: linear-gradient(135deg, #fffdfa, #fff7f2); }
.kb-table-wrap__header h2 { margin: 5px 0 0; color: #392d26; font-size: 1.15rem; }
.kb-table-wrap__header > strong { color: #a13d2b; font-size: .82rem; }
.kb-table { width: 100%; min-width: 940px; border-collapse: collapse; text-align: left; }
.kb-table th { padding: 13px 16px; background: #faf8f6; color: #81776f; font-size: .72rem; letter-spacing: .04em; }
.kb-table td { border-top: 1px solid #f0ece8; padding: 17px 16px; color: #4e4139; font-size: .86rem; vertical-align: top; }
.kb-table tbody tr { transition: background .18s ease; }
.kb-table tbody tr:hover { background: #fff9f6; }
.kb-table__name { display: block; color: #b5412b; font-size: .95rem; font-weight: 900; }
.kb-table td small { display: block; max-width: 340px; margin-top: 6px; overflow: hidden; color: #827268; text-overflow: ellipsis; white-space: nowrap; }
.metric-pair { display: grid; grid-template-columns: auto auto; gap: 2px 7px; width: max-content; }
.metric-pair strong { color: #49372d; font-size: .92rem; }
.metric-pair small { margin: 0; align-self: center; color: #8a786d; font-size: .68rem; }
.status-chip, .permission-chip { display: inline-flex; border-radius: 999px; padding: 5px 9px; background: #eee5dc; color: #695b51; font-size: .7rem; font-weight: 900; white-space: nowrap; }
.status-chip.is-active, .permission-chip.is-allowed { background: #e4f2e9; color: #2c704b; }
.status-chip.is-deleted { background: #f4dfdb; color: #9e3c30; }
.status-chip.is-archived, .permission-chip.is-readonly { background: #f1e8d9; color: #775f3d; }
.pagination { display: flex; justify-content: space-between; gap: 20px; align-items: center; padding-top: 20px; color: #695b51; font-size: .82rem; }
.pagination div { display: flex; gap: 8px; }

/* Modal Styles */
.modal-overlay {
  position: fixed; inset: 0; z-index: 1000;
  display: flex; align-items: center; justify-content: center;
  background: rgb(0 0 0 / 42%); backdrop-filter: blur(4px);
}
.modal-panel {
  width: min(600px, calc(100% - 32px)); max-height: calc(100vh - 64px);
  overflow-y: auto; border-radius: 16px; background: #fff;
  box-shadow: 0 20px 50px rgb(0 0 0 / 18%);
}
.modal-panel__header {
  display: flex; justify-content: space-between; align-items: flex-start;
  padding: 24px 24px 0;
}
.modal-panel__header h2 { margin: 8px 0 0; color: #2c211b; font-size: 1.45rem; }
.modal-panel__close {
  border: none; background: none; color: #8d7b6f; font-size: 1.2rem;
  cursor: pointer; padding: 4px 8px; border-radius: 6px;
}
.modal-panel__close:hover { background: #f5f0eb; }
.modal-panel__form {
  display: grid; grid-template-columns: 1fr 1fr; gap: 18px;
  padding: 24px;
}
.modal-panel__form label { display: grid; gap: 7px; color: #695b51; font-size: .8rem; font-weight: 800; }
.modal-panel__form input, .modal-panel__form textarea {
  width: 100%; border: 1px solid #d9ccc1; border-radius: 9px;
  padding: 10px 11px; background: #fffdfa; color: #392d26; font: inherit;
}
.modal-panel__form textarea { resize: vertical; }
.is-wide { grid-column: 1 / -1; }
.form-actions { display: flex; justify-content: flex-end; gap: 10px; }
.form-message { border-radius: 10px; padding: 11px 14px; font-size: .84rem; }
.form-message.is-error { grid-column: 1 / -1; margin: 0; background: #fff0ed; color: #a4362b; }

/* Inline Delete Modal Styles */
.modal-confirm {
  width: min(480px, calc(100% - 32px)); border-radius: 16px; background: #fff;
  box-shadow: 0 20px 50px rgb(0 0 0 / 18%); overflow: hidden;
}
.modal-confirm__header { padding: 24px 24px 0; }
.modal-confirm__header h2 { margin: 8px 0 0; color: #2c211b; font-size: 1.35rem; }
.modal-confirm__body { padding: 16px 24px 20px; color: #4e4139; line-height: 1.7; }
.modal-confirm__body strong { color: #b5412b; }
.modal-confirm__actions {
  display: flex; justify-content: flex-end; gap: 10px;
  padding: 16px 24px 24px; border-top: 1px solid #f0ece8;
}
.button--danger { border: 1px solid #c44; background: linear-gradient(135deg, #e0554a, #b8382c); color: white; box-shadow: 0 7px 16px rgb(184 56 44 / 16%); min-height: 40px; border-radius: 9px; padding: 8px 14px; cursor: pointer; font-weight: 800; }

@media (max-width: 760px) {
  .kb-page { width: min(100% - 28px, 600px); }
  .kb-page__header { align-items: stretch; flex-direction: column; }
  .kb-page__header-actions { justify-content: space-between; }
  .filter-panel { grid-template-columns: 1fr; }
  .pagination { align-items: stretch; flex-direction: column; }
  .modal-panel__form { grid-template-columns: 1fr; }
}
</style>
