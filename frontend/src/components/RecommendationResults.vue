<script setup lang="ts">
import { computed, ref } from 'vue'

import type {
  MerchantRecommendation,
  RecommendationFallback,
  RecommendationSource,
} from '@/types/recommendation'

import HighlightedText from './HighlightedText.vue'

const props = withDefaults(defineProps<{
  recommendations: MerchantRecommendation[]
  sources: RecommendationSource[]
  fallback?: RecommendationFallback
  now?: string
}>(), {
  fallback: () => ({ triggered: false }),
  now: () => new Date().toISOString(),
})

const emit = defineEmits<{
  refine: [suggestion: string]
}>()

const selectedSourceIds = ref<string[]>([])
const selectedSourceTitle = ref('')
const shouldFallback = computed(() => (
  props.fallback.triggered || (props.recommendations.length === 0 && props.sources.length === 0)
))
const showsSourcesOnly = computed(() => (
  props.recommendations.length === 0 && props.sources.length > 0 && !props.fallback.triggered
))
const selectedSources = computed(() => {
  const sourceIds = new Set(selectedSourceIds.value)
  return props.sources.filter((source) => sourceIds.has(source.chunk_id))
})
const fallbackSuggestions = computed(() => (
  props.fallback.suggestions?.length
    ? props.fallback.suggestions
    : ['扩大距离范围', '提高预算上限', '换一个菜系或场景']
))

function formatDistance(distance?: number | null): string {
  if (distance === null || distance === undefined) return '距离待确认'
  if (distance < 1000) return `${distance} 米`
  return `${(distance / 1000).toFixed(distance % 1000 === 0 ? 0 : 1)} 公里`
}

function formatPrice(priceCent?: number | null): string {
  if (priceCent === null || priceCent === undefined) return '价格待确认'
  return `人均 ¥${Math.round(priceCent / 100)}`
}

function sourceCount(recommendation: MerchantRecommendation): number {
  const ids = new Set(recommendation.source_chunk_ids)
  return props.sources.filter((source) => ids.has(source.chunk_id)).length
}

function freshness(updatedAt: string): { label: string; level: 'fresh' | 'recent' | 'stale' } {
  const ageMs = Math.max(0, new Date(props.now).getTime() - new Date(updatedAt).getTime())
  const ageDays = ageMs / 86_400_000
  if (ageDays < 1) return { label: '24 小时内更新', level: 'fresh' }
  if (ageDays <= 7) return { label: `${Math.ceil(ageDays)} 天前更新`, level: 'recent' }
  const date = new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'numeric', day: 'numeric' })
    .format(new Date(updatedAt))
  return { label: `数据可能已过期 · ${date}`, level: 'stale' }
}

function openSources(recommendation: MerchantRecommendation): void {
  selectedSourceTitle.value = `${recommendation.name} · 引用依据`
  selectedSourceIds.value = [...recommendation.source_chunk_ids]
}

function openAllSources(): void {
  selectedSourceTitle.value = '本次回答 · 引用依据'
  selectedSourceIds.value = props.sources.map((source) => source.chunk_id)
}

function closeSources(): void {
  selectedSourceIds.value = []
  selectedSourceTitle.value = ''
}

function safeSourceUrl(sourceUrl: string): string | null {
  const trimmed = sourceUrl.trim()
  return /^https?:\/\//i.test(trimmed) ? trimmed : null
}
</script>

<template>
  <section
    class="recommendation-results"
    aria-labelledby="recommendation-title"
  >
    <header class="recommendation-results__heading">
      <div>
        <span>TRACEABLE RECOMMENDATIONS</span>
        <h2 id="recommendation-title">
          为你找到的选择
        </h2>
      </div>
      <span v-if="recommendations.length > 0">{{ recommendations.length }} 家候选</span>
      <span v-else-if="showsSourcesOnly">{{ sources.length }} 条引用</span>
    </header>

    <section
      v-if="shouldFallback"
      class="recommendation-fallback"
      role="status"
    >
      <span aria-hidden="true">⌕</span>
      <div>
        <h3>暂时没有足够证据给出可靠推荐</h3>
        <p>
          {{ fallback.reason || '当前条件下未找到达到证据阈值的商家，我们不会编造名称、价格或评价。' }}
        </p>
        <div
          class="recommendation-fallback__actions"
          aria-label="条件调整建议"
        >
          <button
            v-for="suggestion in fallbackSuggestions"
            :key="suggestion"
            type="button"
            @click="emit('refine', suggestion)"
          >
            {{ suggestion }}
          </button>
        </div>
      </div>
    </section>

    <div
      v-else-if="recommendations.length > 0"
      class="recommendation-grid"
    >
      <article
        v-for="recommendation in recommendations"
        :key="recommendation.merchant_id"
        class="recommendation-card"
        :data-merchant-id="recommendation.merchant_id"
      >
        <div class="recommendation-card__topline">
          <span>{{ recommendation.category }}</span>
          <span
            class="freshness-badge"
            :data-level="freshness(recommendation.data_updated_at).level"
          >
            {{ freshness(recommendation.data_updated_at).label }}
          </span>
        </div>
        <h3>{{ recommendation.name }}</h3>
        <div class="recommendation-card__facts">
          <strong v-if="recommendation.rating">★ {{ recommendation.rating.toFixed(1) }}</strong>
          <span>{{ formatDistance(recommendation.distance_meter) }}</span>
          <span>{{ formatPrice(recommendation.avg_price_cent) }}</span>
          <span
            v-if="recommendation.business_status === 'OPEN'"
            class="is-open"
          >营业中</span>
        </div>
        <p class="recommendation-card__reason">
          {{ recommendation.reason }}
        </p>
        <ul
          v-if="recommendation.tags?.length"
          class="recommendation-card__tags"
        >
          <li
            v-for="tag in recommendation.tags"
            :key="tag"
          >
            {{ tag }}
          </li>
        </ul>
        <button
          class="recommendation-card__sources"
          type="button"
          :disabled="sourceCount(recommendation) === 0"
          @click="openSources(recommendation)"
        >
          查看 {{ sourceCount(recommendation) }} 条支持性引用
        </button>
      </article>
    </div>

    <section
      v-else-if="showsSourcesOnly"
      class="source-preview"
      aria-label="回答引用预览"
    >
      <p>本次回答引用了 {{ sources.length }} 条原始资料，可查看高亮片段并跳转来源。</p>
      <ol>
        <li
          v-for="source in sources.slice(0, 2)"
          :key="source.chunk_id"
        >
          <strong>{{ source.source_location }}</strong>
          <p>
            <HighlightedText
              :content="source.content"
              :highlight="source.highlight_text"
            />
          </p>
        </li>
      </ol>
      <button
        type="button"
        @click="openAllSources"
      >
        查看全部引用
      </button>
    </section>

    <p class="ai-boundary">
      <strong>AI 使用边界：</strong>
      推荐基于已收录资料与点评，不承诺实时库存、排队时间或营业状态；出发前请查看商家最新信息。
    </p>

    <div
      v-if="selectedSourceIds.length > 0"
      class="source-drawer-backdrop"
      role="presentation"
      @click.self="closeSources"
    >
      <aside
        class="source-drawer"
        aria-labelledby="source-drawer-title"
        aria-modal="true"
        role="dialog"
      >
        <div class="source-drawer__heading">
          <div>
            <span>SUPPORTING SOURCES</span>
            <h3 id="source-drawer-title">
              {{ selectedSourceTitle }}
            </h3>
          </div>
          <button
            aria-label="关闭引用"
            type="button"
            @click="closeSources"
          >
            ×
          </button>
        </div>
        <p class="source-drawer__notice">
          以下为生成回答时保存的引用快照，重点片段已高亮。
        </p>
        <ol>
          <li
            v-for="(source, index) in selectedSources"
            :key="source.chunk_id"
          >
            <article class="source-item">
              <div class="source-item__topline">
                <strong>引用 {{ index + 1 }}</strong>
                <span>相关度 {{ Math.round(source.score * 100) }}%</span>
              </div>
              <p class="source-item__location">
                {{ source.source_location }}
              </p>
              <blockquote>
                <HighlightedText
                  :content="source.content"
                  :highlight="source.highlight_text"
                />
              </blockquote>
              <a
                v-if="safeSourceUrl(source.source_url)"
                :href="safeSourceUrl(source.source_url)"
                target="_blank"
                rel="noopener noreferrer"
              >打开原始来源</a>
              <span
                v-else
                class="source-item__snapshot"
              >当前仅提供生成时保存的来源快照</span>
            </article>
          </li>
        </ol>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.recommendation-results { max-width: 920px; margin: 30px 0; padding: 22px; border: 1px solid rgb(74 54 42 / 12%); border-radius: 18px; background: rgb(255 255 255 / 72%); box-shadow: 0 18px 44px rgb(74 54 42 / 7%); }
.recommendation-results__heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; margin-bottom: 18px; }
.recommendation-results__heading div > span, .source-drawer__heading div > span { color: #c34833; font-size: .68rem; font-weight: 800; letter-spacing: .12em; }
.recommendation-results h2 { margin: 4px 0 0; color: #2c211b; font-size: 1.3rem; }
.recommendation-results__heading > span { border-radius: 999px; padding: 5px 9px; background: #eee5dc; color: #695b51; font-size: .7rem; font-weight: 800; }
.recommendation-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.recommendation-card { border: 1px solid #e7d9ce; border-radius: 14px; padding: 16px; background: #fffdfa; }
.recommendation-card__topline, .recommendation-card__facts, .source-item__topline { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; }
.recommendation-card__topline > span:first-child { color: #a54230; font-size: .72rem; font-weight: 800; }
.freshness-badge { border-radius: 999px; padding: 4px 7px; background: #e8f3ec; color: #2d714c; font-size: .65rem; font-weight: 700; }
.freshness-badge[data-level="recent"] { background: #f5edda; color: #87631e; }
.freshness-badge[data-level="stale"] { background: #fff0ed; color: #a4362b; }
.recommendation-card h3 { margin: 9px 0; color: #2c211b; font-size: 1.16rem; }
.recommendation-card__facts { justify-content: flex-start; color: #695b51; font-size: .78rem; }
.recommendation-card__facts strong { color: #b14b27; }
.recommendation-card__facts .is-open { color: #2f7650; font-weight: 800; }
.recommendation-card__reason { min-height: 3.2em; margin: 12px 0; color: #4e4037; font-size: .88rem; line-height: 1.65; }
.recommendation-card__tags { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 14px; padding: 0; list-style: none; }
.recommendation-card__tags li { border-radius: 6px; padding: 4px 7px; background: #f5ece4; color: #725c4f; font-size: .68rem; }
.recommendation-card__sources { border: 0; padding: 0; background: transparent; color: #a93a28; cursor: pointer; font: inherit; font-size: .78rem; font-weight: 800; text-decoration: underline; text-underline-offset: 3px; }
.recommendation-card__sources:disabled { color: #9b9088; cursor: not-allowed; }
.ai-boundary { margin: 16px 0 0; border-radius: 9px; padding: 10px 12px; background: #f7f0e8; color: #75675d; font-size: .75rem; line-height: 1.6; }
.recommendation-fallback { display: flex; gap: 14px; border: 1px solid #ead8c9; border-radius: 14px; padding: 18px; background: #fff9f2; }
.recommendation-fallback > span { color: #c34833; font-size: 2rem; }
.recommendation-fallback h3 { margin: 0 0 6px; color: #392d26; }
.recommendation-fallback p { margin: 0; color: #695b51; font-size: .88rem; line-height: 1.65; }
.recommendation-fallback__actions { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 13px; }
.recommendation-fallback__actions button { border: 1px solid #dec9bb; border-radius: 999px; padding: 6px 9px; background: #fffdfa; color: #8e3a2b; cursor: pointer; font: inherit; font-size: .72rem; font-weight: 700; }
.source-preview { border: 1px solid #ead8c9; border-radius: 14px; padding: 16px; background: #fffdfa; }
.source-preview > p { margin: 0 0 12px; color: #695b51; font-size: .82rem; }
.source-preview ol { display: grid; gap: 9px; margin: 0; padding: 0; list-style: none; }
.source-preview li { border-left: 3px solid #d26b57; padding-left: 11px; }
.source-preview li strong { color: #8e3a2b; font-size: .72rem; }
.source-preview li p { margin: 4px 0 0; color: #493a31; font-size: .8rem; line-height: 1.55; }
.source-preview > button { margin-top: 12px; border: 0; padding: 0; background: transparent; color: #a93a28; cursor: pointer; font: inherit; font-size: .78rem; font-weight: 800; text-decoration: underline; text-underline-offset: 3px; }
.source-drawer-backdrop { position: fixed; z-index: 30; inset: 0; background: rgb(40 29 22 / 46%); }
.source-drawer { position: absolute; top: 0; right: 0; width: min(620px, 100%); height: 100%; overflow-y: auto; padding: 24px; background: #fffdfa; box-shadow: -20px 0 60px rgb(40 29 22 / 24%); }
.source-drawer__heading { display: flex; justify-content: space-between; gap: 16px; }
.source-drawer__heading h3 { margin: 4px 0 0; color: #2c211b; }
.source-drawer__heading button { width: 34px; height: 34px; border: 0; border-radius: 50%; background: #f2e8de; color: #59483d; cursor: pointer; font-size: 1.3rem; }
.source-drawer__notice { color: #7b6d63; font-size: .8rem; }
.source-drawer ol { display: grid; gap: 12px; margin: 20px 0 0; padding: 0; list-style: none; }
.source-item { border: 1px solid #e7d9ce; border-radius: 12px; padding: 15px; }
.source-item__topline { color: #a54230; font-size: .74rem; }
.source-item__location { color: #7b6d63; font-size: .74rem; }
.source-item blockquote { margin: 10px 0; border-left: 3px solid #d26b57; padding-left: 12px; color: #493a31; font-size: .88rem; line-height: 1.7; }
.source-item a { color: #9d3423; font-size: .78rem; font-weight: 800; text-underline-offset: 3px; }
.source-item__snapshot { color: #88786d; font-size: .74rem; }
@media (max-width: 680px) { .recommendation-results { padding: 17px; } .recommendation-grid { grid-template-columns: 1fr; } .recommendation-card__reason { min-height: auto; } .source-drawer { padding: 18px; } }
</style>
