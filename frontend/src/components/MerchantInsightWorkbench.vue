<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { getUserFacingError } from '@/api/errors'
import { merchantAnalyticsApi } from '@/api/merchant-analytics'
import { merchantInsightsApi } from '@/api/merchant-insights'
import type { AnalyticsReview } from '@/types/merchant-analytics'
import type {
  BusinessSuggestionResult,
  MerchantComparisonResult,
  ReplySuggestionResult,
  ReplyTone,
} from '@/types/merchant-insights'

const props = defineProps<{
  merchantId: string
}>()

const prohibitedCommitments = ['虚构补偿', '虚构联系方式', '虚构已完成整改']
const toneLabels: Record<ReplyTone, string> = {
  EMPATHETIC: '真诚共情',
  PROFESSIONAL: '专业克制',
  CONCISE: '简洁直接',
}

const competitorInput = ref('')
const competitorIds = ref<string[]>([])
const compareStartDate = ref('')
const compareEndDate = ref('')
const comparison = ref<MerchantComparisonResult | null>(null)
const comparisonLoading = ref(false)
const comparisonError = ref('')
const comparisonFormError = ref('')

const reviews = ref<AnalyticsReview[]>([])
const reviewsLoading = ref(false)
const selectedReviewId = ref('')
const replyTone = ref<ReplyTone>('EMPATHETIC')
const replySuggestion = ref<ReplySuggestionResult | null>(null)
const editableReply = ref('')
const replyLoading = ref(false)
const replyError = ref('')
const copyMessage = ref('')

const suggestionStartDate = ref('')
const suggestionEndDate = ref('')
const focusAspectsInput = ref('')
const businessSuggestions = ref<BusinessSuggestionResult | null>(null)
const suggestionsLoading = ref(false)
const suggestionsError = ref('')

const selectedReview = computed(() => reviews.value.find((review) => review.id === selectedReviewId.value) ?? null)
const comparisonSummaries = computed(() => comparison.value?.summary ?? [])

function toStartDate(value: string): string | undefined {
  return value ? `${value}T00:00:00` : undefined
}

function toExclusiveEndDate(value: string): string | undefined {
  if (!value) return undefined
  const [year, month, day] = value.split('-').map(Number)
  const date = new Date(Date.UTC(year ?? 0, (month ?? 1) - 1, day ?? 1))
  date.setUTCDate(date.getUTCDate() + 1)
  return `${date.toISOString().slice(0, 10)}T00:00:00`
}

function formatDate(value: string | null): string {
  if (!value) return '时间未记录'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('zh-CN')
}

function formatRate(value: number): string {
  return `${Math.round(Math.min(1, Math.max(0, value)) * 100)}%`
}

function formatConfidence(value: number): string {
  return `${Math.round(Math.min(1, Math.max(0, value)) * 100)}%`
}

function topLabels(counts: Record<string, number>): string {
  const labels = Object.entries(counts)
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0], 'zh-CN'))
    .slice(0, 3)
    .map(([label, count]) => `${label} ${count}`)
  return labels.join(' · ') || '暂无数据'
}

function topAspects(merchantId: string): string {
  const counts = Object.fromEntries(
    (comparison.value?.aspect_comparison ?? []).map((row) => [
      row.aspect,
      row.merchants.find((merchant) => merchant.merchant_id === merchantId)?.total ?? 0,
    ]),
  )
  return topLabels(counts)
}

function topNegativeReasons(merchantId: string): string {
  const counts = Object.fromEntries(
    (comparison.value?.negative_reason_comparison ?? []).map((row) => [
      row.reason,
      row.merchants.find((merchant) => merchant.merchant_id === merchantId)?.count ?? 0,
    ]),
  )
  return topLabels(counts)
}

function parseAspects(value: string): string[] {
  return [...new Set(value.split(/[，,]/).map((item) => item.trim()).filter(Boolean))]
}

function addCompetitor(): void {
  comparisonFormError.value = ''
  const candidate = competitorInput.value.trim()
  if (!candidate) return
  if (candidate === props.merchantId) {
    comparisonFormError.value = '当前商家已作为基准，无需重复添加。'
    return
  }
  if (competitorIds.value.includes(candidate)) {
    comparisonFormError.value = '该竞品已在对比列表中。'
    return
  }
  if (competitorIds.value.length >= 3) {
    comparisonFormError.value = '一次最多选择 3 家竞品。'
    return
  }
  competitorIds.value = [...competitorIds.value, candidate]
  competitorInput.value = ''
}

function removeCompetitor(merchantId: string): void {
  competitorIds.value = competitorIds.value.filter((value) => value !== merchantId)
  comparison.value = null
}

function validDateRange(start: string, end: string): boolean {
  return !start || !end || start <= end
}

async function compare(): Promise<void> {
  comparisonFormError.value = ''
  comparisonError.value = ''
  if (competitorIds.value.length < 1) {
    comparisonFormError.value = '请至少选择 1 家竞品后再开始比较。'
    return
  }
  if (!validDateRange(compareStartDate.value, compareEndDate.value)) {
    comparisonFormError.value = '开始日期不能晚于结束日期。'
    return
  }
  comparisonLoading.value = true
  try {
    comparison.value = await merchantInsightsApi.compare({
      merchant_ids: [props.merchantId, ...competitorIds.value],
      ...(toStartDate(compareStartDate.value) ? { start_date: toStartDate(compareStartDate.value) } : {}),
      ...(toExclusiveEndDate(compareEndDate.value) ? { end_date: toExclusiveEndDate(compareEndDate.value) } : {}),
    })
  } catch (error) {
    comparisonError.value = getUserFacingError(error, '竞品比较加载失败，请稍后重试')
  } finally {
    comparisonLoading.value = false
  }
}

async function loadReviews(): Promise<void> {
  reviewsLoading.value = true
  try {
    reviews.value = await merchantAnalyticsApi.getReviews(props.merchantId, { limit: 50, offset: 0 })
    selectedReviewId.value = reviews.value[0]?.id ?? ''
  } catch (error) {
    replyError.value = getUserFacingError(error, '用于生成回复的点评加载失败，请稍后重试')
  } finally {
    reviewsLoading.value = false
  }
}

async function generateReply(): Promise<void> {
  replyError.value = ''
  copyMessage.value = ''
  if (!selectedReview.value) {
    replyError.value = '请先选择一条原点评。'
    return
  }
  replyLoading.value = true
  try {
    replySuggestion.value = await merchantInsightsApi.getReplySuggestion(selectedReview.value.id, {
      tone: replyTone.value,
      aspect_labels: selectedReview.value.aspect_labels,
      prohibited_commitments: prohibitedCommitments,
    })
    editableReply.value = replySuggestion.value.draft
  } catch (error) {
    replyError.value = getUserFacingError(error, '回复建议生成失败，请稍后重试')
  } finally {
    replyLoading.value = false
  }
}

async function copyReply(): Promise<void> {
  copyMessage.value = ''
  if (!editableReply.value.trim()) return
  try {
    if (!navigator.clipboard) throw new Error('Clipboard unavailable')
    await navigator.clipboard.writeText(editableReply.value)
    copyMessage.value = '已复制回复草稿，请在发布前人工确认。'
  } catch {
    copyMessage.value = '当前浏览器不支持复制，请手动复制草稿内容。'
  }
}

async function generateBusinessSuggestions(): Promise<void> {
  suggestionsError.value = ''
  if (!validDateRange(suggestionStartDate.value, suggestionEndDate.value)) {
    suggestionsError.value = '开始日期不能晚于结束日期。'
    return
  }
  suggestionsLoading.value = true
  try {
    businessSuggestions.value = await merchantInsightsApi.getBusinessSuggestions(props.merchantId, {
      ...(toStartDate(suggestionStartDate.value) ? { start_date: toStartDate(suggestionStartDate.value) } : {}),
      ...(toExclusiveEndDate(suggestionEndDate.value) ? { end_date: toExclusiveEndDate(suggestionEndDate.value) } : {}),
      ...(parseAspects(focusAspectsInput.value).length ? { focus_aspects: parseAspects(focusAspectsInput.value) } : {}),
    })
  } catch (error) {
    suggestionsError.value = getUserFacingError(error, '经营建议生成失败，请稍后重试')
  } finally {
    suggestionsLoading.value = false
  }
}

watch(() => props.merchantId, () => {
  competitorIds.value = []
  comparison.value = null
  replySuggestion.value = null
  editableReply.value = ''
  businessSuggestions.value = null
  void loadReviews()
})

onMounted(() => void loadReviews())
</script>

<template>
  <section
    class="insight-workbench"
    aria-label="商家洞察工作台"
  >
    <article class="insight-card competitor-card">
      <header>
        <div><span class="eyebrow">PUBLIC BENCHMARK</span><h2>竞品对比</h2></div>
        <small>统一时间窗、样本下限和指标口径</small>
      </header>
      <p class="card-intro">
        当前商家将作为基准；仅比较公开聚合数据，不展示竞品私有点评或经营数据。
      </p>
      <form
        class="compare-form"
        @submit.prevent="compare"
      >
        <label><span>竞品商家 ID</span><input
          v-model="competitorInput"
          placeholder="输入后添加"
        ><button
          type="button"
          @click="addCompetitor"
        >添加</button></label>
        <label><span>开始日期</span><input
          v-model="compareStartDate"
          type="date"
        ></label>
        <label><span>结束日期</span><input
          v-model="compareEndDate"
          type="date"
        ></label>
        <div
          class="competitor-chips"
          aria-label="已选竞品"
        >
          <span v-if="!competitorIds.length">请选择 1～3 家竞品</span>
          <button
            v-for="competitorId in competitorIds"
            :key="competitorId"
            type="button"
            @click="removeCompetitor(competitorId)"
          >
            {{ competitorId }} ×
          </button>
        </div>
        <p
          v-if="comparisonFormError"
          class="form-error"
          role="alert"
        >
          {{ comparisonFormError }}
        </p>
        <button
          class="primary-button"
          type="submit"
          :disabled="comparisonLoading"
        >
          {{ comparisonLoading ? '比较中…' : '开始比较' }}
        </button>
      </form>
      <p
        v-if="comparisonError"
        class="state-message is-error"
        role="alert"
      >
        {{ comparisonError }}
      </p>
      <template v-else-if="comparison">
        <p
          v-if="comparison.summary.every((merchant) => merchant.total === 0)"
          class="state-message is-warning"
        >
          样本量低于统一下限，当前不输出确定性排序或结论。
        </p>
        <div class="comparison-meta">
          <span>统计商家：{{ comparison.merchants.join('、') }}</span><span>口径：公开聚合数据</span>
        </div>
        <div
          class="comparison-table"
          role="table"
          aria-label="竞品公开聚合比较"
        >
          <div
            class="comparison-row comparison-head"
            role="row"
          >
            <span>商家</span><span>样本</span><span>正面率</span><span>负面率</span><span>主要特征 / 归因</span>
          </div>
          <div
            v-for="merchant in comparisonSummaries"
            :key="merchant.merchant_id"
            class="comparison-row"
            role="row"
          >
            <strong>{{ merchant.merchant_id }}</strong><span>{{ merchant.total }}</span><span>{{ formatRate(merchant.positive_rate) }}</span><span>{{ formatRate(merchant.negative_rate) }}</span><span>{{ topAspects(merchant.merchant_id) }}<br><small>归因：{{ topNegativeReasons(merchant.merchant_id) }}</small></span>
          </div>
        </div>
      </template>
    </article>

    <article class="insight-card reply-card">
      <header>
        <div><span class="eyebrow">REPLY DRAFT</span><h2>回复建议</h2></div>
        <small>草稿可编辑、可复制，不会自动发布</small>
      </header>
      <p class="card-intro">
        建议基于指定原点评和已识别特征生成；禁止承诺虚构补偿、联系方式或未完成整改。
      </p>
      <div class="reply-controls">
        <label><span>选择原点评</span><select
          v-model="selectedReviewId"
          :disabled="reviewsLoading"
        ><option
          v-if="!reviews.length"
          value=""
        >{{ reviewsLoading ? '加载点评中…' : '暂无可用点评' }}</option><option
          v-for="review in reviews"
          :key="review.id"
          :value="review.id"
        >{{ formatDate(review.review_date) }} · {{ review.review_text.slice(0, 36) }}</option></select></label>
        <label><span>回复语气</span><select v-model="replyTone"><option
          v-for="(_, tone) in toneLabels"
          :key="tone"
          :value="tone"
        >{{ toneLabels[tone] }}</option></select></label>
        <button
          class="primary-button"
          type="button"
          :disabled="replyLoading || reviewsLoading"
          @click="generateReply"
        >
          {{ replyLoading ? '生成中…' : '生成回复草稿' }}
        </button>
      </div>
      <section
        v-if="selectedReview"
        class="selected-review"
      >
        <span>原点评 · {{ formatDate(selectedReview.review_date) }}</span><p>{{ selectedReview.review_text }}</p><small v-if="selectedReview.aspect_labels.length">关联特征：{{ selectedReview.aspect_labels.join('、') }}</small>
      </section>
      <p
        v-if="replyError"
        class="state-message is-error"
        role="alert"
      >
        {{ replyError }}
      </p>
      <template v-if="replySuggestion">
        <label class="draft-editor"><span>可编辑回复草稿</span><textarea
          v-model="editableReply"
          rows="6"
          data-testid="reply-draft"
        /></label>
        <div class="draft-actions">
          <button
            type="button"
            @click="copyReply"
          >
            复制草稿
          </button><small>模型 {{ replySuggestion.model_version }} · Prompt {{ replySuggestion.prompt_version }} · {{ formatDate(replySuggestion.generated_at) }}</small>
        </div>
        <p
          v-if="copyMessage"
          class="copy-message"
          role="status"
        >
          {{ copyMessage }}
        </p>
      </template>
    </article>

    <article class="insight-card suggestion-card">
      <header>
        <div><span class="eyebrow">EVIDENCE-LED ACTIONS</span><h2>经营建议</h2></div>
        <small>展开建议即可查看支撑证据</small>
      </header>
      <form
        class="suggestion-form"
        @submit.prevent="generateBusinessSuggestions"
      >
        <label><span>开始日期</span><input
          v-model="suggestionStartDate"
          type="date"
        ></label>
        <label><span>结束日期</span><input
          v-model="suggestionEndDate"
          type="date"
        ></label>
        <label class="is-wide"><span>关注特征（用逗号分隔）</span><input
          v-model="focusAspectsInput"
          placeholder="如：服务，等位，环境"
        ></label>
        <button
          class="primary-button"
          type="submit"
          :disabled="suggestionsLoading"
        >
          {{ suggestionsLoading ? '生成中…' : '生成经营建议' }}
        </button>
      </form>
      <p
        v-if="suggestionsError"
        class="state-message is-error"
        role="alert"
      >
        {{ suggestionsError }}
      </p>
      <template v-else-if="businessSuggestions">
        <p
          v-if="businessSuggestions.insufficient_data"
          class="state-message is-warning"
        >
          当前样本不足，建议仅供观察，不应据此做确定性经营决策。
        </p>
        <p
          v-if="businessSuggestions.evidence_conflict"
          class="state-message is-warning"
        >
          证据存在冲突，请结合原点评和实际经营情况人工判断。
        </p>
        <details
          v-for="suggestion in businessSuggestions.suggestions"
          :key="suggestion.id"
          class="suggestion-detail"
        >
          <summary><span>{{ suggestion.title }}</span><small>置信度 {{ formatConfidence(suggestion.confidence) }}</small></summary>
          <p>{{ suggestion.content }}</p>
          <div class="suggestion-period">
            统计周期：{{ formatDate(suggestion.period_start) }} 至 {{ formatDate(suggestion.period_end) }}
          </div>
          <section class="evidence-list">
            <strong>证据点评（{{ suggestion.evidence_review_ids.length }}）</strong><article
              v-for="evidence in suggestion.evidence_reviews"
              :key="evidence.review_id"
            >
              <span>{{ evidence.sentiment || '未标注' }} · {{ formatDate(evidence.reviewed_at) }}</span><p>{{ evidence.review_text }}</p>
            </article>
          </section>
        </details>
        <small class="trace-meta">模型 {{ businessSuggestions.model_version }} · Prompt {{ businessSuggestions.prompt_version }} · {{ formatDate(businessSuggestions.generated_at) }}</small>
      </template>
    </article>
  </section>
</template>

<style scoped>
.insight-workbench { display: grid; grid-template-columns: 1.12fr .88fr; gap: 18px; margin-top: 18px; }
.insight-card { min-width: 0; border: 1px solid rgb(74 54 42 / 12%); border-radius: 18px; padding: 22px; background: rgb(255 255 255 / 70%); box-shadow: 0 14px 44px rgb(74 54 42 / 6%); }
.suggestion-card { grid-column: 1 / -1; }
.insight-card > header { display: flex; justify-content: space-between; gap: 18px; align-items: end; margin-bottom: 12px; }
.insight-card h2 { margin: 7px 0 0; font-size: 1.3rem; }.insight-card header small { color: #88776c; font-size: .68rem; text-align: right; }.card-intro { margin: 0 0 16px; color: #695b51; font-size: .78rem; line-height: 1.65; }
.compare-form, .suggestion-form { display: grid; grid-template-columns: 1fr 1fr; gap: 11px; }.compare-form label, .suggestion-form label, .reply-controls label, .draft-editor { display: grid; gap: 6px; color: #695b51; font-size: .7rem; font-weight: 800; }.compare-form label:first-child { grid-column: 1 / -1; grid-template-columns: 1fr auto; align-items: end; }.compare-form label:first-child span { grid-column: 1 / -1; }.suggestion-form .is-wide { grid-column: 1 / -1; }
.compare-form input, .compare-form select, .suggestion-form input, .reply-controls select, .draft-editor textarea { width: 100%; min-height: 39px; border: 1px solid #d9ccc1; border-radius: 9px; padding: 8px 10px; background: #fffdfa; color: #392d26; font: inherit; }.draft-editor textarea { min-height: 130px; resize: vertical; line-height: 1.6; }
.compare-form label:first-child button, .draft-actions button { border: 1px solid #d9ccc1; border-radius: 9px; padding: 8px 11px; background: #fffdfa; color: #6c5042; cursor: pointer; font-weight: 800; }.primary-button { min-height: 39px; border: 1px solid var(--brand); border-radius: 9px; padding: 8px 13px; background: var(--brand); color: white; cursor: pointer; font-weight: 800; }.primary-button:disabled { cursor: wait; opacity: .58; }.compare-form > .primary-button { grid-column: 1 / -1; }
.competitor-chips { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 7px; min-height: 26px; color: #88776c; font-size: .72rem; }.competitor-chips button { border: 0; border-radius: 999px; padding: 5px 8px; background: #f1e6d8; color: #6c5042; cursor: pointer; font-size: .68rem; font-weight: 800; }.form-error, .state-message { margin: 0; border-radius: 9px; padding: 10px 12px; font-size: .75rem; }.form-error, .state-message.is-error { background: #fff0ed; color: #a4362b; }.state-message.is-warning { background: #fff8e6; color: #775f3d; }.compare-form .form-error { grid-column: 1 / -1; }
.comparison-meta { display: flex; flex-wrap: wrap; gap: 6px 15px; margin: 16px 0 9px; color: #7a6a60; font-size: .67rem; }.comparison-table { overflow: auto; border: 1px solid #e0d4c9; border-radius: 10px; }.comparison-row { display: grid; grid-template-columns: minmax(110px, 1.1fr) 45px 58px 42px minmax(165px, 1.5fr); gap: 10px; align-items: center; border-top: 1px solid #eadfd5; padding: 10px; color: #4b3b32; font-size: .7rem; }.comparison-row:first-child { border-top: 0; }.comparison-head { background: #f5eee6; color: #79695e; font-size: .64rem; font-weight: 800; }.comparison-row strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.comparison-row small { color: #8a786d; font-size: .64rem; }
.reply-controls { display: grid; grid-template-columns: 1fr 1fr auto; gap: 10px; align-items: end; }.selected-review { margin: 15px 0; border-left: 3px solid #d98a4f; padding: 9px 12px; background: #fff9f3; }.selected-review span, .selected-review small { color: #806f64; font-size: .67rem; }.selected-review p { margin: 7px 0; color: #493a31; font-size: .78rem; line-height: 1.65; }.draft-actions { display: flex; justify-content: space-between; gap: 14px; align-items: center; margin-top: 10px; }.draft-actions small, .copy-message, .trace-meta { color: #7b6d63; font-size: .67rem; }.copy-message { margin: 9px 0 0; color: #2c704b; }
.suggestion-form { grid-template-columns: 1fr 1fr auto; align-items: end; }.suggestion-form .is-wide { grid-column: 1 / 3; }.suggestion-detail { margin-top: 12px; border: 1px solid #e0d4c9; border-radius: 11px; padding: 0 14px; background: #fffdfa; }.suggestion-detail summary { display: flex; justify-content: space-between; gap: 14px; padding: 14px 0; cursor: pointer; color: #493a31; font-size: .82rem; font-weight: 800; }.suggestion-detail summary small { color: #806226; font-size: .67rem; }.suggestion-detail > p { margin: 0 0 10px; color: #5e4d43; font-size: .78rem; line-height: 1.7; }.suggestion-period { color: #8a786d; font-size: .66rem; }.evidence-list { display: grid; gap: 8px; margin: 13px 0; border-top: 1px solid #eadfd5; padding-top: 12px; }.evidence-list > strong { color: #695b51; font-size: .72rem; }.evidence-list article { border-left: 2px solid #ddc4af; padding-left: 9px; }.evidence-list article span { color: #8a786d; font-size: .64rem; }.evidence-list article p { margin: 4px 0 0; color: #5a493e; font-size: .72rem; line-height: 1.55; }.trace-meta { display: block; margin-top: 12px; }
@media (max-width: 850px) { .insight-workbench { grid-template-columns: 1fr; }.suggestion-card { grid-column: auto; }.reply-controls, .suggestion-form { grid-template-columns: 1fr 1fr; }.reply-controls .primary-button, .suggestion-form .primary-button { grid-column: 1 / -1; }.suggestion-form .is-wide { grid-column: 1 / -1; } }
@media (max-width: 520px) { .insight-card { padding: 17px; }.insight-card > header { align-items: flex-start; flex-direction: column; }.insight-card header small { text-align: left; }.compare-form, .reply-controls, .suggestion-form { grid-template-columns: 1fr; }.compare-form label:first-child { grid-template-columns: 1fr; }.compare-form .primary-button, .reply-controls .primary-button, .suggestion-form .primary-button, .suggestion-form .is-wide { grid-column: auto; }.comparison-row { grid-template-columns: 92px 38px 48px 36px minmax(130px, 1fr); gap: 7px; padding: 9px 7px; }.draft-actions { align-items: flex-start; flex-direction: column; } }
</style>
