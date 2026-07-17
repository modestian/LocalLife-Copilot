<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import {
  debugSearch,
  type SearchRequest,
  type SearchResult,
} from '@/api/search'
import { ApiClientError } from '@/api/errors'

const props = withDefaults(defineProps<{
  knowledgeBaseId: string
  initialResults?: SearchResult[]
  search?: (request: SearchRequest) => Promise<SearchResult[]>
}>(), {
  initialResults: () => [],
  search: debugSearch,
})

type SearchState = 'idle' | 'loading' | 'ready' | 'empty' | 'error' | 'forbidden'

const query = ref('安静、适合四人讨论的咖啡馆')
const category = ref('咖啡馆')
const distance = ref<number | null>(3000)
const price = ref<number | null>(6000)
const openNow = ref(true)
const documentTypes = ref<string[]>(['review', 'merchant'])
const topK = ref(5)
const results = ref<SearchResult[]>(props.initialResults)
const state = ref<SearchState>(props.initialResults.length > 0 ? 'ready' : 'idle')
const errorMessage = ref('')
const selectedResult = ref<SearchResult | null>(null)

const canSearch = computed(() => query.value.trim().length > 0 && state.value !== 'loading')
const hasResults = computed(() => state.value === 'ready' && results.value.length > 0)

watch(
  () => props.initialResults,
  (nextResults) => {
    results.value = nextResults
    state.value = nextResults.length > 0 ? 'ready' : 'idle'
  },
)

function formatScore(score: number): string {
  return score.toFixed(3)
}

function createRequest(): SearchRequest {
  const categories = category.value
    .split('，')
    .flatMap((value) => value.split(','))
    .map((value) => value.trim())
    .filter(Boolean)

  return {
    query: query.value.trim(),
    knowledge_base_ids: [props.knowledgeBaseId],
    top_k: topK.value,
    vector_weight: 0.6,
    keyword_weight: 0.4,
    rerank: true,
    filters: {
      ...(categories.length > 0 ? { category: categories } : {}),
      ...(distance.value ? { distance_meter_lte: distance.value } : {}),
      ...(price.value ? { price_cent_lte: price.value } : {}),
      open_now: openNow.value,
      ...(documentTypes.value.length > 0 ? { document_type: documentTypes.value } : {}),
    },
  }
}

async function runSearch(): Promise<void> {
  if (!canSearch.value) return

  state.value = 'loading'
  errorMessage.value = ''
  selectedResult.value = null
  try {
    results.value = await props.search(createRequest())
    state.value = results.value.length > 0 ? 'ready' : 'empty'
  } catch (error: unknown) {
    if (error instanceof ApiClientError && error.status === 403) {
      state.value = 'forbidden'
      errorMessage.value = '当前账号无权调试此知识库的检索结果。'
      return
    }

    state.value = 'error'
    errorMessage.value = error instanceof Error ? error.message : '检索请求失败，请稍后重试。'
  }
}
</script>

<template>
  <section
    class="search-debug"
    aria-labelledby="search-debug-title"
  >
    <header>
      <p class="search-debug__eyebrow">
        KNOWLEDGE BASE · RETRIEVAL
      </p>
      <h2 id="search-debug-title">
        检索调试
      </h2>
      <p>筛选条件仅用于缩小查询范围；权限、资源范围与有效期由服务端强制校验。</p>
    </header>

    <form
      class="search-debug__form"
      @submit.prevent="runSearch"
    >
      <label class="search-debug__query">
        <span>检索问题</span>
        <input
          v-model="query"
          type="search"
          placeholder="输入需要验证的检索问题"
        >
      </label>
      <div class="search-debug__filters">
        <label>
          <span>品类</span>
          <input
            v-model="category"
            placeholder="例如：咖啡馆"
          >
        </label>
        <label>
          <span>距离上限（米）</span>
          <input
            v-model.number="distance"
            min="1"
            step="100"
            type="number"
          >
        </label>
        <label>
          <span>人均上限（分）</span>
          <input
            v-model.number="price"
            min="1"
            step="100"
            type="number"
          >
        </label>
        <label>
          <span>返回条数</span>
          <input
            v-model.number="topK"
            max="20"
            min="1"
            type="number"
          >
        </label>
      </div>
      <div class="search-debug__options">
        <label><input
          v-model="openNow"
          type="checkbox"
        > 仅营业中</label>
        <span>文档类型</span>
        <label><input
          v-model="documentTypes"
          type="checkbox"
          value="review"
        > 点评</label>
        <label><input
          v-model="documentTypes"
          type="checkbox"
          value="merchant"
        > 商家资料</label>
        <label><input
          v-model="documentTypes"
          type="checkbox"
          value="menu"
        > 菜单</label>
      </div>
      <button
        class="search-debug__submit"
        :disabled="!canSearch"
        type="submit"
      >
        {{ state === 'loading' ? '检索中…' : '执行调试检索' }}
      </button>
    </form>

    <div
      v-if="state === 'loading'"
      class="search-debug__state"
      role="status"
    >
      正在执行 BM25 与向量双路召回，并按融合分数排序。
    </div>
    <div
      v-else-if="state === 'empty'"
      class="search-debug__state"
      role="status"
    >
      没有符合当前筛选条件的结果。请放宽筛选范围或调整查询词。
    </div>
    <div
      v-else-if="state === 'forbidden' || state === 'error'"
      class="search-debug__state is-error"
      role="alert"
    >
      {{ errorMessage }}
      <button
        type="button"
        @click="runSearch"
      >
        重试
      </button>
    </div>

    <ol
      v-if="hasResults"
      class="search-debug__results"
      aria-label="检索结果"
    >
      <li
        v-for="(result, index) in results"
        :key="result.chunk_id"
      >
        <article class="search-result">
          <div class="search-result__topline">
            <span>融合排序 #{{ index + 1 }}</span>
            <strong>融合 {{ formatScore(result.score_detail.fusion) }}</strong>
          </div>
          <h3>{{ result.source_location }}</h3>
          <p>{{ result.content }}</p>
          <dl class="search-result__scores">
            <div>
              <dt>BM25</dt>
              <dd>{{ formatScore(result.score_detail.bm25) }}</dd>
            </div>
            <div>
              <dt>向量</dt>
              <dd>{{ formatScore(result.score_detail.vector) }}</dd>
            </div>
            <div>
              <dt>最终分数</dt>
              <dd>{{ formatScore(result.score) }}</dd>
            </div>
          </dl>
          <button
            class="search-result__preview"
            type="button"
            @click="selectedResult = result"
          >
            预览引用
          </button>
        </article>
      </li>
    </ol>

    <div
      v-if="selectedResult"
      class="citation-preview-backdrop"
      role="presentation"
      @click.self="selectedResult = null"
    >
      <section
        class="citation-preview"
        aria-labelledby="citation-preview-title"
        aria-modal="true"
        role="dialog"
      >
        <div class="citation-preview__heading">
          <div>
            <p>引用预览</p>
            <h3 id="citation-preview-title">
              {{ selectedResult.source_location }}
            </h3>
          </div>
          <button
            aria-label="关闭引用预览"
            type="button"
            @click="selectedResult = null"
          >
            ×
          </button>
        </div>
        <p>{{ selectedResult.content }}</p>
        <dl>
          <div><dt>Chunk ID</dt><dd>{{ selectedResult.chunk_id }}</dd></div>
          <div><dt>Document ID</dt><dd>{{ selectedResult.document_id }}</dd></div>
        </dl>
        <a
          :href="selectedResult.source_url"
          target="_blank"
          rel="noopener noreferrer"
        >打开原始来源</a>
      </section>
    </div>
  </section>
</template>

<style scoped>
.search-debug { max-width: 760px; margin: 30px 0; padding: 24px; border: 1px solid rgb(74 54 42 / 12%); border-radius: 18px; background: rgb(255 255 255 / 72%); box-shadow: 0 18px 44px rgb(74 54 42 / 7%); }
.search-debug h2, .search-result h3, .citation-preview h3 { margin: 4px 0 8px; color: #2c211b; }
.search-debug header > p:last-child { margin: 0; color: #695b51; line-height: 1.65; }
.search-debug__eyebrow, .citation-preview__heading p { margin: 0; color: #d4472d; font-size: .72rem; font-weight: 800; letter-spacing: .12em; }
.search-debug__form { display: grid; gap: 14px; margin-top: 20px; }
.search-debug label { display: grid; gap: 5px; color: #59483d; font-size: .8rem; font-weight: 700; }
.search-debug input { min-width: 0; border: 1px solid #d9ccc1; border-radius: 8px; padding: 8px; background: #fffdfa; color: #392d26; font: inherit; font-size: .88rem; }
.search-debug input:focus { outline: 2px solid rgb(212 71 45 / 28%); border-color: #c34833; }
.search-debug__query input { width: 100%; }
.search-debug__filters { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.search-debug__options { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; color: #695b51; font-size: .82rem; }
.search-debug__options label { display: inline-flex; align-items: center; gap: 5px; font-weight: 500; }
.search-debug__options input { min-width: auto; padding: 0; }
.search-debug__submit, .search-result__preview, .search-debug__state button { width: fit-content; border: 0; border-radius: 8px; padding: 9px 13px; background: #c34833; color: #fff; cursor: pointer; font: inherit; font-size: .88rem; font-weight: 700; }
.search-debug__submit:disabled { cursor: wait; opacity: .65; }
.search-debug__state { margin-top: 18px; border-radius: 10px; padding: 12px; background: #fbf5ee; color: #695b51; font-size: .88rem; line-height: 1.6; }
.search-debug__state.is-error { background: #fff0ed; color: #a4362b; }
.search-debug__state button { margin-left: 8px; padding: 4px 8px; background: transparent; color: currentcolor; text-decoration: underline; }
.search-debug__results { display: grid; gap: 12px; margin: 20px 0 0; padding: 0; list-style: none; }
.search-result { padding: 15px; border: 1px solid #eaded3; border-radius: 12px; background: #fffdfa; }
.search-result__topline { display: flex; justify-content: space-between; gap: 12px; color: #7a493d; font-size: .78rem; }
.search-result h3 { font-size: 1rem; }
.search-result > p { margin: 0; color: #55473d; font-size: .9rem; line-height: 1.65; }
.search-result__scores { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 14px 0; }
.search-result__scores div { padding: 8px; border-radius: 8px; background: #f8f1e9; }
.search-result__scores dt { color: #7b6d63; font-size: .72rem; }
.search-result__scores dd { margin: 3px 0 0; color: #3d3028; font-size: .9rem; font-weight: 800; }
.search-result__preview { background: #544238; }
.citation-preview-backdrop { position: fixed; z-index: 20; inset: 0; display: grid; place-items: center; padding: 20px; background: rgb(40 29 22 / 45%); }
.citation-preview { width: min(620px, 100%); border-radius: 16px; padding: 22px; background: #fffdfa; box-shadow: 0 24px 80px rgb(40 29 22 / 30%); }
.citation-preview__heading { display: flex; justify-content: space-between; gap: 16px; }
.citation-preview__heading button { width: 32px; height: 32px; border: 0; border-radius: 50%; background: #f2e8de; color: #59483d; cursor: pointer; font-size: 1.3rem; }
.citation-preview > p { color: #55473d; line-height: 1.75; white-space: pre-wrap; }
.citation-preview dl { display: grid; gap: 8px; margin: 16px 0; }
.citation-preview dl div { display: grid; grid-template-columns: 96px 1fr; gap: 8px; color: #695b51; font-size: .8rem; }
.citation-preview dd { overflow-wrap: anywhere; margin: 0; color: #3d3028; }
.citation-preview a { color: #9d3423; font-size: .9rem; font-weight: 700; }
@media (max-width: 520px) { .search-debug { padding: 18px; } .search-debug__filters { grid-template-columns: 1fr; } .search-result__scores { grid-template-columns: 1fr; } }
</style>
