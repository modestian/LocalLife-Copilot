<script setup lang="ts">
import { computed, reactive, ref } from 'vue'

import { getUserFacingError } from '@/api/errors'
import { searchApi } from '@/api/search'
import type {
  SearchDocumentType,
  SearchFilters,
  SearchHit,
  SearchRequest,
  SearchResponse,
} from '@/types/search'

const props = defineProps<{
  knowledgeBaseId: string
}>()

interface SearchForm {
  query: string
  top_k: number
  vector_weight: number | ''
  keyword_weight: number | ''
  rerank: boolean
  categories: string
  max_price_yuan: number | ''
  max_distance_meter: number | ''
  open_now: '' | 'true' | 'false'
  document_types: SearchDocumentType[]
}

const form = reactive<SearchForm>({
  query: '',
  top_k: 10,
  vector_weight: 0.6,
  keyword_weight: 0.4,
  rerank: true,
  categories: '',
  max_price_yuan: '',
  max_distance_meter: '',
  open_now: '',
  document_types: [],
})
const loading = ref(false)
const formError = ref('')
const searchError = ref('')
const response = ref<SearchResponse | null>(null)
const lastRequest = ref<SearchRequest | null>(null)
const selectedHit = ref<SearchHit | null>(null)

const resultCount = computed(() => response.value?.total ?? response.value?.items.length ?? 0)
const weightTotal = computed(() => Number(form.vector_weight) + Number(form.keyword_weight))
const activeFilters = computed(() => {
  const filters = lastRequest.value?.filters
  if (!filters) return []
  const labels: string[] = []
  if (filters.category?.length) labels.push(`分类：${filters.category.join('、')}`)
  if (filters.price_cent_lte !== undefined) {
    labels.push(`人均不超过 ¥${Math.round(filters.price_cent_lte / 100)}`)
  }
  if (filters.distance_meter_lte !== undefined) {
    labels.push(`距离不超过 ${filters.distance_meter_lte} 米`)
  }
  if (filters.open_now !== undefined) labels.push(filters.open_now ? '仅营业中' : '当前非营业')
  if (filters.document_type?.length) {
    labels.push(`文档类型：${filters.document_type.map(documentTypeLabel).join('、')}`)
  }
  return labels
})

function documentTypeLabel(value: SearchDocumentType): string {
  return value === 'review' ? '点评' : '商家'
}

function parseCategories(value: string): string[] {
  return [...new Set(value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean))]
}

function buildFilters(): SearchFilters {
  const filters: SearchFilters = {}
  const categories = parseCategories(form.categories)
  if (categories.length) filters.category = categories
  if (form.max_price_yuan !== '') {
    filters.price_cent_lte = Math.round(Number(form.max_price_yuan) * 100)
  }
  if (form.max_distance_meter !== '') {
    filters.distance_meter_lte = Math.round(Number(form.max_distance_meter))
  }
  if (form.open_now !== '') filters.open_now = form.open_now === 'true'
  if (form.document_types.length) filters.document_type = [...form.document_types]
  return filters
}

function validate(): boolean {
  formError.value = ''
  if (!form.query.trim()) {
    formError.value = '请输入要调试的检索问题。'
    return false
  }
  if (!Number.isInteger(form.top_k) || form.top_k < 1 || form.top_k > 100) {
    formError.value = '返回数量必须是 1—100 的整数。'
    return false
  }
  if (
    form.vector_weight === '' ||
    form.keyword_weight === '' ||
    form.vector_weight < 0 ||
    form.vector_weight > 1 ||
    form.keyword_weight < 0 ||
    form.keyword_weight > 1 ||
    Math.abs(weightTotal.value - 1) > 0.0001
  ) {
    formError.value = '向量权重和关键词权重必须在 0—1 之间，且总和等于 1。'
    return false
  }
  if (form.max_price_yuan !== '' && Number(form.max_price_yuan) < 0) {
    formError.value = '价格上限不能小于 0。'
    return false
  }
  if (form.max_distance_meter !== '' && Number(form.max_distance_meter) < 0) {
    formError.value = '距离上限不能小于 0。'
    return false
  }
  return true
}

async function submitSearch(): Promise<void> {
  if (!validate()) return
  const payload: SearchRequest = {
    query: form.query.trim(),
    knowledge_base_ids: [props.knowledgeBaseId],
    top_k: Number(form.top_k),
    vector_weight: Number(form.vector_weight),
    keyword_weight: Number(form.keyword_weight),
    rerank: form.rerank,
    filters: buildFilters(),
  }

  loading.value = true
  searchError.value = ''
  selectedHit.value = null
  try {
    response.value = await searchApi.search(payload)
    lastRequest.value = payload
  } catch (error) {
    response.value = null
    searchError.value = getUserFacingError(error, '检索请求失败，请检查条件后重试')
  } finally {
    loading.value = false
  }
}

function resetFilters(): void {
  form.categories = ''
  form.max_price_yuan = ''
  form.max_distance_meter = ''
  form.open_now = ''
  form.document_types = []
  form.vector_weight = 0.6
  form.keyword_weight = 0.4
  form.top_k = 10
  form.rerank = true
  formError.value = ''
}

function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(value)
}

function safeSourceUrl(value: string): string {
  const trimmed = value.trim()
  return /^(https?:\/\/|\/(?!\/)|#)/i.test(trimmed) ? trimmed : '#'
}
</script>

<template>
  <section
    class="retrieval-debug"
    aria-labelledby="retrieval-debug-title"
  >
    <header class="retrieval-debug__heading">
      <div>
        <span class="eyebrow">HYBRID RETRIEVAL DEBUGGER</span>
        <h2 id="retrieval-debug-title">
          检索调试
        </h2>
        <p>在当前知识库范围内检查过滤条件、双路得分、融合排序和引用内容。</p>
      </div>
      <span
        class="scope-badge"
        :title="knowledgeBaseId"
      >单知识库授权范围</span>
    </header>

    <form
      class="retrieval-form"
      @submit.prevent="submitSearch"
    >
      <label class="query-field is-wide">
        <span>检索问题 *</span>
        <textarea
          v-model="form.query"
          data-testid="search-query"
          rows="3"
          placeholder="例如：安静、适合四个人讨论、人均 60 元以内的咖啡馆"
        />
      </label>

      <fieldset class="filter-fieldset">
        <legend>业务过滤</legend>
        <label>
          <span>分类</span>
          <input
            v-model="form.categories"
            data-testid="category-filter"
            placeholder="咖啡馆，川菜"
          >
          <small>多个分类使用逗号分隔</small>
        </label>
        <label>
          <span>人均价格上限（元）</span>
          <input
            v-model.number="form.max_price_yuan"
            data-testid="price-filter"
            type="number"
            min="0"
            step="1"
            placeholder="60"
          >
        </label>
        <label>
          <span>距离上限（米）</span>
          <input
            v-model.number="form.max_distance_meter"
            data-testid="distance-filter"
            type="number"
            min="0"
            step="100"
            placeholder="3000"
          >
        </label>
        <label>
          <span>营业状态</span>
          <select
            v-model="form.open_now"
            data-testid="open-now-filter"
          >
            <option value="">不限</option>
            <option value="true">仅营业中</option>
            <option value="false">当前非营业</option>
          </select>
        </label>
        <div class="document-types">
          <span>文档类型</span>
          <label>
            <input
              v-model="form.document_types"
              type="checkbox"
              value="review"
            >
            点评
          </label>
          <label>
            <input
              v-model="form.document_types"
              type="checkbox"
              value="merchant"
            >
            商家
          </label>
        </div>
      </fieldset>

      <fieldset class="score-fieldset">
        <legend>召回与排序</legend>
        <label>
          <span>返回数量</span>
          <input
            v-model.number="form.top_k"
            type="number"
            min="1"
            max="100"
            step="1"
          >
        </label>
        <label>
          <span>向量权重</span>
          <input
            v-model.number="form.vector_weight"
            type="number"
            min="0"
            max="1"
            step="0.1"
          >
        </label>
        <label>
          <span>关键词权重</span>
          <input
            v-model.number="form.keyword_weight"
            type="number"
            min="0"
            max="1"
            step="0.1"
          >
        </label>
        <div
          class="weight-summary"
          :class="{ 'is-invalid': Math.abs(weightTotal - 1) > 0.0001 }"
        >
          权重合计 {{ weightTotal.toFixed(1) }}
        </div>
        <label class="rerank-toggle">
          <input
            v-model="form.rerank"
            type="checkbox"
          >
          启用重排
        </label>
      </fieldset>

      <p
        v-if="formError"
        class="retrieval-message is-error is-wide"
        role="alert"
      >
        {{ formError }}
      </p>

      <div class="retrieval-actions is-wide">
        <button
          class="button button--secondary"
          type="button"
          :disabled="loading"
          @click="resetFilters"
        >
          重置条件
        </button>
        <button
          class="button button--primary"
          data-testid="search-submit"
          type="submit"
          :disabled="loading"
        >
          {{ loading ? '检索中…' : '执行检索' }}
        </button>
      </div>
    </form>

    <div
      v-if="searchError"
      class="retrieval-message is-error"
      role="alert"
    >
      {{ searchError }}
    </div>

    <section
      v-if="response"
      class="retrieval-results"
      aria-live="polite"
    >
      <header class="results-heading">
        <div>
          <span class="eyebrow">RANKED EVIDENCE</span>
          <h3>融合排序结果</h3>
        </div>
        <div class="result-summary">
          <strong>{{ resultCount }}</strong>
          <span>条证据{{ response.took_ms !== undefined ? ` · ${response.took_ms} ms` : '' }}</span>
        </div>
      </header>

      <div
        v-if="activeFilters.length"
        class="active-filters"
        aria-label="已应用过滤条件"
      >
        <span
          v-for="filter in activeFilters"
          :key="filter"
        >
          {{ filter }}
        </span>
      </div>

      <div
        v-if="response.items.length === 0"
        class="empty-results"
      >
        <strong>没有命中达到条件的证据</strong>
        <p>可放宽分类、价格或距离过滤，或调整检索问题后重试。</p>
      </div>

      <ol
        v-else
        class="result-list"
      >
        <li
          v-for="(hit, index) in response.items"
          :key="hit.chunk_id"
        >
          <article class="result-card">
            <header>
              <div class="result-rank">
                <span>#{{ index + 1 }}</span>
                <div>
                  <strong>{{ hit.source_location }}</strong>
                  <small>Chunk {{ hit.chunk_id }}</small>
                </div>
              </div>
              <div class="final-score">
                <span>最终得分</span>
                <strong>{{ formatScore(hit.score) }}</strong>
              </div>
            </header>

            <dl
              class="score-grid"
              aria-label="检索得分详情"
            >
              <div>
                <dt>BM25</dt>
                <dd>{{ formatScore(hit.score_detail.bm25) }}</dd>
              </div>
              <div>
                <dt>向量</dt>
                <dd>{{ formatScore(hit.score_detail.vector) }}</dd>
              </div>
              <div>
                <dt>融合</dt>
                <dd>{{ formatScore(hit.score_detail.fusion) }}</dd>
              </div>
              <div v-if="hit.score_detail.rerank !== undefined && hit.score_detail.rerank !== null">
                <dt>重排</dt>
                <dd>{{ formatScore(hit.score_detail.rerank) }}</dd>
              </div>
            </dl>

            <p class="result-content">
              {{ hit.content }}
            </p>
            <footer>
              <div>
                <span>文档 {{ hit.document_id }}</span>
                <span v-if="hit.merchant_id">商家 {{ hit.merchant_id }}</span>
              </div>
              <button
                type="button"
                @click="selectedHit = hit"
              >
                预览引用
              </button>
            </footer>
          </article>
        </li>
      </ol>
    </section>

    <div
      v-if="selectedHit"
      class="citation-backdrop"
      role="presentation"
      @click.self="selectedHit = null"
    >
      <aside
        class="citation-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="citation-title"
      >
        <header>
          <div>
            <span class="eyebrow">SOURCE SNAPSHOT</span>
            <h3 id="citation-title">
              引用预览
            </h3>
          </div>
          <button
            type="button"
            aria-label="关闭引用预览"
            @click="selectedHit = null"
          >
            ×
          </button>
        </header>
        <p class="citation-notice">
          该内容来自检索接口返回的证据片段，用于核对融合排序和来源定位。
        </p>
        <dl>
          <div><dt>来源位置</dt><dd>{{ selectedHit.source_location }}</dd></div>
          <div><dt>Chunk ID</dt><dd>{{ selectedHit.chunk_id }}</dd></div>
          <div><dt>文档 ID</dt><dd>{{ selectedHit.document_id }}</dd></div>
          <div v-if="selectedHit.merchant_id">
            <dt>商家 ID</dt><dd>{{ selectedHit.merchant_id }}</dd>
          </div>
        </dl>
        <blockquote>{{ selectedHit.content }}</blockquote>
        <a
          :href="safeSourceUrl(selectedHit.source_url)"
          target="_blank"
          rel="noopener noreferrer"
        >
          打开原始来源
        </a>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.retrieval-debug { margin-top: 24px; border: 1px solid rgb(74 54 42 / 12%); border-radius: 16px; padding: 24px; background: rgb(255 255 255 / 64%); }
.retrieval-debug__heading, .results-heading, .result-card > header, .result-card > footer, .citation-drawer > header { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; }
.retrieval-debug__heading h2, .results-heading h3 { margin: 7px 0 0; color: #2c211b; }
.retrieval-debug__heading p { max-width: 660px; margin: 9px 0 0; color: #74645a; font-size: .82rem; line-height: 1.6; }
.eyebrow { color: #c34833; font-size: .66rem; font-weight: 900; letter-spacing: .12em; }
.scope-badge { flex: none; border-radius: 999px; padding: 6px 10px; background: #e4f2e9; color: #2c704b; font-size: .68rem; font-weight: 900; }
.retrieval-form { display: grid; grid-template-columns: 1.35fr 1fr; gap: 16px; margin-top: 22px; }
.retrieval-form label { display: grid; gap: 6px; color: #695b51; font-size: .75rem; font-weight: 800; }
.retrieval-form input, .retrieval-form select, .retrieval-form textarea { width: 100%; border: 1px solid #d9ccc1; border-radius: 8px; padding: 9px 10px; background: #fffdfa; color: #392d26; font: inherit; }
.retrieval-form textarea { resize: vertical; line-height: 1.55; }
.retrieval-form small { color: #8a7a70; font-size: .65rem; font-weight: 500; }
.is-wide { grid-column: 1 / -1; }
.filter-fieldset, .score-fieldset { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; min-width: 0; margin: 0; border: 1px solid #e1d5ca; border-radius: 12px; padding: 18px; }
.filter-fieldset legend, .score-fieldset legend { padding: 0 7px; color: #8e3a2b; font-size: .76rem; font-weight: 900; }
.document-types { display: flex; flex-wrap: wrap; gap: 8px 14px; align-content: start; }
.document-types > span { width: 100%; color: #695b51; font-size: .75rem; font-weight: 800; }
.document-types label, .rerank-toggle { display: flex; grid-column: 1 / -1; grid-template-columns: auto 1fr; align-items: center; }
.document-types input, .rerank-toggle input { width: auto; }
.weight-summary { align-self: end; border-radius: 8px; padding: 10px; background: #e4f2e9; color: #2c704b; font-size: .72rem; font-weight: 800; text-align: center; }
.weight-summary.is-invalid { background: #fff0ed; color: #a4362b; }
.retrieval-actions { display: flex; justify-content: flex-end; gap: 10px; }
.button { display: inline-flex; align-items: center; justify-content: center; min-height: 40px; border-radius: 8px; padding: 8px 14px; cursor: pointer; font-weight: 800; }
.button:disabled { cursor: not-allowed; opacity: .48; }
.button--primary { border: 1px solid var(--brand); background: var(--brand); color: white; }
.button--secondary { border: 1px solid #d9ccc1; background: #fffdfa; color: #6c5042; }
.retrieval-message { margin-top: 14px; border-radius: 9px; padding: 11px 13px; font-size: .8rem; }
.retrieval-message.is-error { background: #fff0ed; color: #a4362b; }
.retrieval-results { margin-top: 28px; border-top: 1px solid #e1d5ca; padding-top: 22px; }
.result-summary { display: flex; gap: 7px; align-items: baseline; color: #7b6d63; font-size: .74rem; }
.result-summary strong { color: #9d3423; font-family: Georgia, serif; font-size: 1.8rem; }
.active-filters { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 14px; }
.active-filters span { border-radius: 999px; padding: 5px 8px; background: #f2e8de; color: #725c4f; font-size: .67rem; font-weight: 700; }
.empty-results { margin-top: 16px; border: 1px dashed #d5c6b9; border-radius: 11px; padding: 28px; color: #695b51; text-align: center; }
.empty-results p { margin: 7px 0 0; font-size: .78rem; }
.result-list { display: grid; gap: 12px; margin: 16px 0 0; padding: 0; list-style: none; }
.result-card { border: 1px solid #e1d5ca; border-radius: 13px; padding: 16px; background: #fffdfa; }
.result-rank { display: flex; gap: 12px; min-width: 0; }
.result-rank > span { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 9px; background: #9d3423; color: white; font-size: .72rem; font-weight: 900; }
.result-rank strong, .result-rank small { display: block; }
.result-rank strong { overflow-wrap: anywhere; color: #3e3028; font-size: .82rem; }
.result-rank small { margin-top: 4px; color: #89796f; font-size: .62rem; }
.final-score { flex: none; text-align: right; }
.final-score span, .final-score strong { display: block; }
.final-score span { color: #7b6d63; font-size: .62rem; }
.final-score strong { margin-top: 2px; color: #9d3423; font-family: Georgia, serif; font-size: 1.25rem; }
.score-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 14px 0 0; }
.score-grid div { border-radius: 8px; padding: 9px 10px; background: #f6eee7; }
.score-grid dt { color: #7b6d63; font-size: .62rem; }
.score-grid dd { margin: 4px 0 0; color: #49382f; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .78rem; font-weight: 800; }
.result-content { display: -webkit-box; margin: 14px 0; overflow: hidden; color: #493a31; font-size: .82rem; line-height: 1.65; -webkit-box-orient: vertical; -webkit-line-clamp: 3; }
.result-card > footer { align-items: flex-end; border-top: 1px solid #eee4dc; padding-top: 12px; }
.result-card > footer div { display: grid; gap: 3px; color: #89796f; font-size: .62rem; }
.result-card > footer button { border: 0; padding: 0; background: transparent; color: #9d3423; cursor: pointer; font: inherit; font-size: .75rem; font-weight: 900; text-decoration: underline; text-underline-offset: 3px; }
.citation-backdrop { position: fixed; z-index: 60; inset: 0; background: rgb(40 29 22 / 46%); backdrop-filter: blur(3px); }
.citation-drawer { position: absolute; top: 0; right: 0; width: min(620px, 100%); height: 100%; overflow-y: auto; padding: 26px; background: #fffdfa; box-shadow: -20px 0 60px rgb(40 29 22 / 24%); }
.citation-drawer h3 { margin: 6px 0 0; font-size: 1.45rem; }
.citation-drawer > header button { width: 34px; height: 34px; border: 0; border-radius: 50%; background: #f2e8de; color: #59483d; cursor: pointer; font-size: 1.3rem; }
.citation-notice { border-radius: 9px; padding: 10px 12px; background: #f7f0e8; color: #75675d; font-size: .76rem; line-height: 1.6; }
.citation-drawer dl { margin: 18px 0; }
.citation-drawer dl div { display: grid; grid-template-columns: 92px 1fr; gap: 12px; border-bottom: 1px solid #eadfd5; padding: 10px 0; font-size: .75rem; }
.citation-drawer dt { color: #7b6d63; }
.citation-drawer dd { margin: 0; overflow-wrap: anywhere; color: #3e3028; font-weight: 700; }
.citation-drawer blockquote { margin: 18px 0; border-left: 3px solid #d26b57; padding: 4px 0 4px 14px; color: #493a31; font-size: .9rem; line-height: 1.75; white-space: pre-wrap; }
.citation-drawer a { color: #9d3423; font-size: .8rem; font-weight: 900; text-underline-offset: 3px; }
@media (max-width: 760px) {
  .retrieval-debug { padding: 19px 15px; }
  .retrieval-debug__heading, .results-heading, .result-card > header, .result-card > footer { align-items: stretch; flex-direction: column; }
  .retrieval-form { grid-template-columns: 1fr; }
  .is-wide { grid-column: auto; }
  .filter-fieldset, .score-fieldset { grid-template-columns: 1fr; }
  .rerank-toggle { grid-column: auto; }
  .score-grid { grid-template-columns: 1fr 1fr; }
  .final-score { text-align: left; }
  .citation-drawer { padding: 20px 15px; }
  .citation-drawer dl div { grid-template-columns: 1fr; gap: 4px; }
}
</style>
