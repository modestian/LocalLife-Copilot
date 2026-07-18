<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import KnowledgeDocumentWorkspace from '@/components/KnowledgeDocumentWorkspace.vue'
import RetrievalDebugPanel from '@/components/RetrievalDebugPanel.vue'
import { useAuthStore } from '@/stores/auth'
import { useKnowledgeBaseStore } from '@/stores/knowledge-base'
import {
  canUpdateKnowledgeBase,
  knowledgeBaseAccessLabel,
} from '@/utils/knowledge-base-permissions'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const store = useKnowledgeBaseStore()
const id = computed(() => String(route.params.id))
const editing = ref(false)
const formError = ref('')
const savedMessage = ref('')
const form = reactive({
  name: '',
  description: '',
  owner_id: '',
  embedding_model_id: '',
})
const access = computed(() => canUpdateKnowledgeBase(authStore.currentUser, id.value))

watch(
  () => store.detail,
  (detail) => {
    if (!detail) return
    form.name = detail.name
    form.description = detail.description ?? ''
    form.owner_id = detail.owner_id
    form.embedding_model_id = detail.embedding_model_id
  },
  { immediate: true },
)

function formatDate(value: string | null): string {
  if (!value) return '暂无记录'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN', { hour12: false })
}

function statusLabel(value: string): string {
  return { ACTIVE: '启用', ARCHIVED: '已归档', DELETED: '已删除' }[value] ?? value
}

function beginEdit(): void {
  if (!access.value.allowed || !store.detail) return
  savedMessage.value = ''
  formError.value = ''
  editing.value = true
}

function cancelEdit(): void {
  if (store.detail) {
    form.name = store.detail.name
    form.description = store.detail.description ?? ''
    form.owner_id = store.detail.owner_id
    form.embedding_model_id = store.detail.embedding_model_id
  }
  formError.value = ''
  editing.value = false
}

async function save(): Promise<void> {
  formError.value = ''
  savedMessage.value = ''
  if (!access.value.allowed) {
    formError.value = '当前账号没有此知识库的编辑权限。'
    return
  }
  if (!form.name.trim()) {
    formError.value = '知识库名称不能为空。'
    return
  }
  if (!form.owner_id.trim() || !form.embedding_model_id.trim()) {
    formError.value = '负责人和默认 Embedding 模型不能为空。'
    return
  }

  try {
    await store.updateDetail(id.value, {
      name: form.name.trim(),
      description: form.description.trim() || null,
      owner_id: form.owner_id.trim(),
      embedding_model_id: form.embedding_model_id.trim(),
    })
    editing.value = false
    savedMessage.value = '知识库配置已保存。'
  } catch {
    formError.value = store.errorMessage
  }
}

function login(): void {
  void router.push({ name: 'login', query: { redirect: route.fullPath } })
}

onMounted(() => store.loadDetail(id.value))
</script>

<template>
  <main class="kb-detail-page">
    <header class="detail-header">
      <div>
        <router-link
          class="detail-header__brand"
          to="/"
        >
          LOCAL LIFE · AI COPILOT
        </router-link>
        <p class="detail-header__breadcrumb">
          <router-link to="/admin">
            管理板块
          </router-link>
          <span>/</span>
          <router-link :to="{ name: 'knowledge-bases' }">
            知识库
          </router-link>
          <span>/</span>
          详情
        </p>
      </div>
      <button
        v-if="!authStore.isAuthenticated"
        class="button button--primary"
        type="button"
        @click="login"
      >
        登录以进行操作
      </button>
    </header>

    <section
      v-if="store.loading"
      class="state-panel"
      aria-live="polite"
    >
      正在加载知识库详情…
    </section>

    <section
      v-else-if="store.errorMessage && !store.detail"
      class="state-panel state-panel--error"
      role="alert"
    >
      <strong>无法查看此知识库</strong>
      <p>{{ store.errorMessage }}</p>
      <div class="state-panel__actions">
        <router-link
          class="button button--secondary"
          :to="{ name: 'knowledge-bases' }"
        >
          返回列表
        </router-link>
        <button
          class="button button--primary"
          type="button"
          @click="store.loadDetail(id)"
        >
          重新加载
        </button>
      </div>
    </section>

    <template v-else-if="store.detail">
      <section class="detail-hero">
        <div>
          <div class="detail-hero__chips">
            <span :class="['status-chip', `is-${store.detail.status.toLowerCase()}`]">
              {{ statusLabel(store.detail.status) }}
            </span>
            <span :class="['permission-chip', { 'is-allowed': access.allowed }]">
              {{ knowledgeBaseAccessLabel(access) }}
            </span>
          </div>
          <h1>{{ store.detail.name }}</h1>
          <p>{{ store.detail.description || '暂无知识库描述。' }}</p>
        </div>
        <button
          v-if="access.allowed && !editing"
          class="button button--primary"
          type="button"
          @click="beginEdit"
        >
          编辑配置
        </button>
      </section>

      <section
        v-if="!access.allowed"
        class="permission-panel"
        role="note"
      >
        <strong>{{ knowledgeBaseAccessLabel(access) }}</strong>
        <span v-if="access.reason === 'LOGIN_REQUIRED'">游客可以查看详情，但不能修改任何配置。</span>
        <span v-else-if="access.reason === 'ROLE_PERMISSION_REQUIRED'">账号缺少知识库更新角色权限。</span>
        <span v-else>账号未获得当前知识库的更新资源授权。</span>
      </section>

      <section
        class="stat-grid"
        aria-label="知识库统计"
      >
        <article>
          <span>文档总数</span>
          <strong>{{ store.detail.statistics.document_count }}</strong>
        </article>
        <article>
          <span>Chunk 总数</span>
          <strong>{{ store.detail.statistics.chunk_count }}</strong>
        </article>
        <article>
          <span>已就绪文档</span>
          <strong>{{ store.detail.statistics.ready_document_count }}</strong>
        </article>
        <article :class="{ 'has-error': store.detail.statistics.failed_document_count > 0 }">
          <span>失败文档</span>
          <strong>{{ store.detail.statistics.failed_document_count }}</strong>
        </article>
      </section>

      <section
        v-if="editing"
        class="edit-panel"
      >
        <div class="section-title">
          <div>
            <span class="eyebrow">EDIT CONFIGURATION</span>
            <h2>编辑知识库</h2>
          </div>
          <span>仅提交发生变化的业务配置</span>
        </div>
        <form @submit.prevent="save">
          <label>
            <span>知识库名称 *</span>
            <input
              v-model="form.name"
              maxlength="200"
              required
            >
          </label>
          <label class="is-wide">
            <span>描述</span>
            <textarea
              v-model="form.description"
              rows="4"
            />
          </label>
          <label>
            <span>负责人 ID *</span>
            <input
              v-model="form.owner_id"
              required
            >
          </label>
          <label>
            <span>默认 Embedding 模型 *</span>
            <input
              v-model="form.embedding_model_id"
              required
            >
          </label>
          <p
            v-if="formError"
            class="form-message is-error"
            role="alert"
          >
            {{ formError }}
          </p>
          <div class="form-actions is-wide">
            <button
              class="button button--secondary"
              type="button"
              :disabled="store.saving"
              @click="cancelEdit"
            >
              取消
            </button>
            <button
              class="button button--primary"
              type="submit"
              :disabled="store.saving"
            >
              {{ store.saving ? '保存中…' : '保存修改' }}
            </button>
          </div>
        </form>
      </section>

      <p
        v-if="savedMessage"
        class="form-message is-success"
        role="status"
      >
        {{ savedMessage }}
      </p>

      <section class="metadata-panel">
        <div class="section-title">
          <div>
            <span class="eyebrow">CONFIGURATION</span>
            <h2>配置与归属</h2>
          </div>
        </div>
        <dl>
          <div><dt>负责人</dt><dd>{{ store.detail.owner_name }}</dd></div>
          <div><dt>所属部门</dt><dd>{{ store.detail.department_name || '未设置' }}</dd></div>
          <div><dt>Embedding 模型</dt><dd>{{ store.detail.embedding_model_name }}</dd></div>
          <div><dt>切分配置</dt><dd>{{ store.detail.chunk_size }} / 重叠 {{ store.detail.chunk_overlap }}</dd></div>
          <div><dt>最近索引时间</dt><dd>{{ formatDate(store.detail.latest_indexed_at) }}</dd></div>
          <div><dt>更新时间</dt><dd>{{ formatDate(store.detail.updated_at) }}</dd></div>
        </dl>
      </section>

      <KnowledgeDocumentWorkspace
        v-if="access.allowed"
        :knowledge-base-id="store.detail.id"
        :default-chunk-size="store.detail.chunk_size"
        :default-chunk-overlap="store.detail.chunk_overlap"
        :can-manage="access.allowed"
      />

      <RetrievalDebugPanel
        v-if="access.allowed"
        :knowledge-base-id="store.detail.id"
      />
    </template>
  </main>
</template>

<style scoped>
.kb-detail-page { width: min(1060px, calc(100% - 48px)); margin: 0 auto; padding: 32px 0 72px; }
.detail-header { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; padding-bottom: 24px; border-bottom: 1px solid rgb(74 54 42 / 12%); }
.detail-header__brand { color: var(--brand); font-size: .74rem; font-weight: 900; letter-spacing: .14em; text-decoration: none; }
.detail-header__breadcrumb { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0 0; color: #7b6d63; font-size: .82rem; }
.detail-hero { display: flex; justify-content: space-between; gap: 40px; align-items: end; padding: 64px 0 36px; }
.detail-hero h1 { margin: 14px 0; font-size: clamp(2.8rem, 7vw, 5.4rem); }
.detail-hero p { max-width: 700px; margin: 0; color: var(--muted); line-height: 1.7; }
.detail-hero__chips { display: flex; gap: 8px; }
.button { display: inline-flex; align-items: center; justify-content: center; min-height: 40px; border-radius: 9px; padding: 8px 14px; cursor: pointer; font-weight: 800; text-decoration: none; }
.button:disabled { cursor: not-allowed; opacity: .48; }
.button--primary { border: 1px solid var(--brand); background: var(--brand); color: white; }
.button--secondary { border: 1px solid #d9ccc1; background: #fffdfa; color: #6c5042; }
.status-chip, .permission-chip { display: inline-flex; border-radius: 999px; padding: 5px 9px; background: #eee5dc; color: #695b51; font-size: .7rem; font-weight: 900; }
.status-chip.is-active, .permission-chip.is-allowed { background: #e4f2e9; color: #2c704b; }
.status-chip.is-archived { background: #f1e8d9; color: #775f3d; }
.status-chip.is-deleted { background: #f4dfdb; color: #9e3c30; }
.permission-panel { display: flex; gap: 8px 20px; flex-wrap: wrap; margin-bottom: 20px; border-left: 3px solid var(--brand); padding: 12px 16px; background: rgb(255 255 255 / 52%); color: var(--muted); }
.permission-panel strong { color: #9d3423; }
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.stat-grid article { border: 1px solid rgb(74 54 42 / 12%); border-radius: 14px; padding: 20px; background: rgb(255 255 255 / 64%); }
.stat-grid span { display: block; color: #77675d; font-size: .78rem; }
.stat-grid strong { display: block; margin-top: 12px; font-family: Georgia, serif; font-size: 2rem; }
.stat-grid article.has-error { border-color: #e3b3aa; background: #fff4f1; color: #9e3c30; }
.edit-panel, .metadata-panel { margin-top: 24px; border: 1px solid rgb(74 54 42 / 12%); border-radius: 16px; padding: 24px; background: rgb(255 255 255 / 64%); }
.section-title { display: flex; justify-content: space-between; gap: 24px; align-items: end; margin-bottom: 22px; color: #7b6d63; font-size: .78rem; }
.section-title h2 { margin: 8px 0 0; color: #2c211b; font-size: 1.45rem; }
.edit-panel form { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.edit-panel label { display: grid; gap: 7px; color: #695b51; font-size: .8rem; font-weight: 800; }
.edit-panel input, .edit-panel textarea { width: 100%; border: 1px solid #d9ccc1; border-radius: 9px; padding: 10px 11px; background: #fffdfa; color: #392d26; font: inherit; }
.edit-panel textarea { resize: vertical; }
.is-wide { grid-column: 1 / -1; }
.form-actions { display: flex; justify-content: flex-end; gap: 10px; }
.form-message { border-radius: 10px; padding: 11px 14px; font-size: .84rem; }
.form-message.is-error { grid-column: 1 / -1; margin: 0; background: #fff0ed; color: #a4362b; }
.form-message.is-success { background: #e4f2e9; color: #2c704b; }
.metadata-panel dl { display: grid; grid-template-columns: 1fr 1fr; gap: 0 28px; margin: 0; }
.metadata-panel dl div { display: grid; grid-template-columns: 145px 1fr; gap: 14px; border-top: 1px solid #eadfd5; padding: 14px 0; }
.metadata-panel dt { color: #7b6d63; }
.metadata-panel dd { margin: 0; overflow-wrap: anywhere; color: #392d26; font-weight: 700; }
.state-panel { margin-top: 64px; border: 1px dashed #d5c6b9; border-radius: 14px; padding: 48px 24px; background: rgb(255 255 255 / 48%); color: #695b51; text-align: center; }
.state-panel p { margin: 8px 0 18px; }
.state-panel--error { border-color: #e3b3aa; background: #fff4f1; color: #8e3328; }
.state-panel__actions { display: flex; justify-content: center; gap: 10px; }
@media (max-width: 760px) {
  .kb-detail-page { width: min(100% - 28px, 600px); }
  .detail-header, .detail-hero { align-items: stretch; flex-direction: column; }
  .stat-grid { grid-template-columns: 1fr 1fr; }
  .edit-panel form, .metadata-panel dl { grid-template-columns: 1fr; }
  .metadata-panel dl div { grid-template-columns: 1fr; gap: 5px; }
}
</style>
