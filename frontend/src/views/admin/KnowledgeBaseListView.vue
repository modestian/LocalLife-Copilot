<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useKnowledgeBaseStore } from '@/stores/knowledge-base'
import type { KnowledgeBaseStatus } from '@/types/knowledge-base'
import {
  canUpdateKnowledgeBase,
  knowledgeBaseAccessLabel,
} from '@/utils/knowledge-base-permissions'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const store = useKnowledgeBaseStore()

const name = ref(typeof route.query.name === 'string' ? route.query.name : '')
const status = ref<KnowledgeBaseStatus | ''>(
  ['ACTIVE', 'ARCHIVED', 'DELETED'].includes(String(route.query.status))
    ? route.query.status as KnowledgeBaseStatus
    : '',
)
const page = ref(Math.max(1, Number(route.query.page) || 1))
const totalPages = computed(() => Math.max(1, Math.ceil(store.total / store.pageSize)))

function statusLabel(value: KnowledgeBaseStatus): string {
  return { ACTIVE: '启用', ARCHIVED: '已归档', DELETED: '已删除' }[value]
}

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN', { hour12: false })
}

function accessLabel(id: string): string {
  return knowledgeBaseAccessLabel(canUpdateKnowledgeBase(authStore.currentUser, id))
}

async function load(): Promise<void> {
  await router.replace({
    query: {
      ...(name.value.trim() ? { name: name.value.trim() } : {}),
      ...(status.value ? { status: status.value } : {}),
      ...(page.value > 1 ? { page: String(page.value) } : {}),
    },
  })
  await store.loadList({
    name: name.value.trim() || undefined,
    status: status.value || undefined,
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

function login(): void {
  void router.push({ name: 'login', query: { redirect: route.fullPath } })
}

onMounted(load)
</script>

<template>
  <main class="kb-page">
    <header class="kb-page__header">
      <div>
        <router-link
          class="kb-page__brand"
          to="/"
        >
          LOCAL LIFE · AI COPILOT
        </router-link>
        <p class="kb-page__breadcrumb">
          <router-link to="/admin">
            管理板块
          </router-link>
          <span>/</span>
          知识库
        </p>
      </div>
      <div class="kb-page__header-actions">
        <span :class="['permission-chip', { 'is-readonly': !authStore.isAuthenticated }]">
          {{ authStore.isAuthenticated ? '按资源授权' : '游客只读' }}
        </span>
        <button
          v-if="!authStore.isAuthenticated"
          class="button button--primary"
          type="button"
          @click="login"
        >
          登录以进行操作
        </button>
      </div>
    </header>

    <section class="kb-page__intro">
      <span class="eyebrow">KNOWLEDGE BASES</span>
      <h1>知识库管理</h1>
      <p>浏览知识库状态、文档与 Chunk 规模；编辑入口根据角色权限和资源授权动态开放。</p>
    </section>

    <form
      class="filter-panel"
      aria-label="知识库筛选"
      @submit.prevent="search"
    >
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
      <table class="kb-table">
        <thead>
          <tr>
            <th>知识库</th>
            <th>状态</th>
            <th>文档 / Chunk</th>
            <th>负责人</th>
            <th>更新时间</th>
            <th>权限状态</th>
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
            <td>{{ item.statistics.document_count }} / {{ item.statistics.chunk_count }}</td>
            <td>{{ item.owner_name }}</td>
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
  </main>
</template>

<style scoped>
.kb-page { width: min(1180px, calc(100% - 48px)); margin: 0 auto; padding: 32px 0 72px; }
.kb-page__header { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; padding-bottom: 24px; border-bottom: 1px solid rgb(74 54 42 / 12%); }
.kb-page__brand { color: var(--brand); font-size: .74rem; font-weight: 900; letter-spacing: .14em; text-decoration: none; }
.kb-page__breadcrumb { display: flex; gap: 8px; margin: 12px 0 0; color: #7b6d63; font-size: .82rem; }
.kb-page__header-actions { display: flex; gap: 12px; align-items: center; }
.kb-page__intro { padding: 58px 0 34px; }
.kb-page__intro h1 { margin: 12px 0; font-size: clamp(2.8rem, 7vw, 5.4rem); }
.kb-page__intro p { max-width: 680px; margin: 0; color: var(--muted); line-height: 1.7; }
.filter-panel { display: grid; grid-template-columns: minmax(240px, 1fr) 220px auto; gap: 16px; align-items: end; padding: 20px; border: 1px solid rgb(74 54 42 / 12%); border-radius: 16px; background: rgb(255 255 255 / 62%); }
.filter-panel label { display: grid; gap: 7px; color: #695b51; font-size: .8rem; font-weight: 800; }
.filter-panel input, .filter-panel select { width: 100%; min-height: 42px; border: 1px solid #d9ccc1; border-radius: 9px; padding: 8px 11px; background: #fffdfa; color: #392d26; font: inherit; }
.button { min-height: 40px; border-radius: 9px; padding: 8px 14px; cursor: pointer; font-weight: 800; }
.button:disabled { cursor: not-allowed; opacity: .48; }
.button--primary { border: 1px solid var(--brand); background: var(--brand); color: white; }
.button--secondary { border: 1px solid #d9ccc1; background: #fffdfa; color: #6c5042; }
.readonly-banner { display: flex; gap: 8px 20px; flex-wrap: wrap; margin: 18px 0; border-left: 3px solid var(--brand); padding: 12px 16px; background: rgb(255 255 255 / 52%); color: var(--muted); }
.readonly-banner strong { color: #9d3423; }
.state-panel { margin-top: 20px; border: 1px dashed #d5c6b9; border-radius: 14px; padding: 48px 24px; background: rgb(255 255 255 / 48%); color: #695b51; text-align: center; }
.state-panel p { margin: 8px 0 18px; }
.state-panel--error { border-color: #e3b3aa; background: #fff4f1; color: #8e3328; }
.kb-table-wrap { overflow-x: auto; margin-top: 20px; border: 1px solid rgb(74 54 42 / 12%); border-radius: 16px; background: rgb(255 255 255 / 68%); }
.kb-table { width: 100%; min-width: 940px; border-collapse: collapse; text-align: left; }
.kb-table th { padding: 13px 16px; background: #eee5dc; color: #695b51; font-size: .74rem; letter-spacing: .04em; }
.kb-table td { border-top: 1px solid #eee3d9; padding: 17px 16px; color: #4e4139; font-size: .86rem; vertical-align: top; }
.kb-table__name { display: block; color: #8f3021; font-size: .95rem; font-weight: 900; }
.kb-table td small { display: block; max-width: 340px; margin-top: 6px; overflow: hidden; color: #827268; text-overflow: ellipsis; white-space: nowrap; }
.status-chip, .permission-chip { display: inline-flex; border-radius: 999px; padding: 5px 9px; background: #eee5dc; color: #695b51; font-size: .7rem; font-weight: 900; white-space: nowrap; }
.status-chip.is-active, .permission-chip.is-allowed { background: #e4f2e9; color: #2c704b; }
.status-chip.is-deleted { background: #f4dfdb; color: #9e3c30; }
.status-chip.is-archived, .permission-chip.is-readonly { background: #f1e8d9; color: #775f3d; }
.pagination { display: flex; justify-content: space-between; gap: 20px; align-items: center; padding-top: 20px; color: #695b51; font-size: .82rem; }
.pagination div { display: flex; gap: 8px; }
@media (max-width: 760px) {
  .kb-page { width: min(100% - 28px, 600px); }
  .kb-page__header { align-items: stretch; flex-direction: column; }
  .kb-page__header-actions { justify-content: space-between; }
  .filter-panel { grid-template-columns: 1fr; }
  .pagination { align-items: stretch; flex-direction: column; }
}
</style>
