<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { getUserFacingError, toApiClientError } from '@/api/errors'
import { merchantAnalyticsApi } from '@/api/merchant-analytics'
import type {
  AnalyticsDateRange,
  AnalyticsReview,
  Sentiment,
  SentimentTrendPoint,
  TrendGranularity,
} from '@/types/merchant-analytics'

const props = defineProps<{
  merchantId: string
}>()

interface CountedLabel {
  label: string
  count: number
}

const LOW_SAMPLE_THRESHOLD = 10
const ASPECT_SAMPLE_LIMIT = 200

const granularity = ref<TrendGranularity>('day')
const startDateInput = ref('')
const endDateInput = ref('')
const appliedRange = ref<AnalyticsDateRange>({})
const trend = ref<SentimentTrendPoint[]>([])
const negativeReasons = ref<CountedLabel[]>([])
const analysisReviews = ref<AnalyticsReview[]>([])
const loading = ref(false)
const errorMessage = ref('')
const forbidden = ref(false)
const filterError = ref('')
const drawerOpen = ref(false)
const drawerTitle = ref('原点评')
const drawerDescription = ref('')
const drawerReviews = ref<AnalyticsReview[]>([])
const drawerLoading = ref(false)
const drawerError = ref('')
let requestVersion = 0

const sentiments: Sentiment[] = ['POSITIVE', 'NEUTRAL', 'NEGATIVE']
const sentimentMeta: Record<Sentiment, { label: string; key: 'positive' | 'neutral' | 'negative' }> = {
  POSITIVE: { label: '正面', key: 'positive' },
  NEUTRAL: { label: '中性', key: 'neutral' },
  NEGATIVE: { label: '负面', key: 'negative' },
}

const granularityLabels: Record<TrendGranularity, string> = {
  day: '日',
  week: '周',
  month: '月',
}

const sentimentCounts = computed<Record<Sentiment, number>>(() => ({
  POSITIVE: trend.value.reduce((sum, point) => sum + point.positive, 0),
  NEUTRAL: trend.value.reduce((sum, point) => sum + point.neutral, 0),
  NEGATIVE: trend.value.reduce((sum, point) => sum + point.negative, 0),
}))

const sampleSize = computed(() => Object.values(sentimentCounts.value).reduce((sum, value) => sum + value, 0))
const positiveRate = computed(() => sampleSize.value ? sentimentCounts.value.POSITIVE / sampleSize.value : 0)
const lowSample = computed(() => sampleSize.value > 0 && sampleSize.value < LOW_SAMPLE_THRESHOLD)
const maxReasonCount = computed(() => Math.max(1, ...negativeReasons.value.map((item) => item.count)))

const aspectCounts = computed<CountedLabel[]>(() => {
  const counts = new Map<string, number>()
  for (const review of analysisReviews.value) {
    for (const label of new Set(review.aspect_labels)) {
      const normalized = label.trim()
      if (normalized) counts.set(normalized, (counts.get(normalized) ?? 0) + 1)
    }
  }
  return [...counts.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label, 'zh-CN'))
    .slice(0, 10)
})

const maxAspectCount = computed(() => Math.max(1, ...aspectCounts.value.map((item) => item.count)))

function startOfDay(value: string): string {
  return `${value}T00:00:00`
}

function nextDay(value: string): string {
  const [year, month, day] = value.split('-').map(Number)
  const date = new Date(Date.UTC(year ?? 0, (month ?? 1) - 1, day ?? 1))
  date.setUTCDate(date.getUTCDate() + 1)
  return `${date.toISOString().slice(0, 10)}T00:00:00`
}

function selectedDateRange(): AnalyticsDateRange {
  return {
    ...(startDateInput.value ? { start_date: startOfDay(startDateInput.value) } : {}),
    ...(endDateInput.value ? { end_date: nextDay(endDateInput.value) } : {}),
  }
}

function formatPeriod(period: string): string {
  if (/^\d{4}-W\d{2}$/.test(period)) return period.replace('-W', ' 年第 ') + ' 周'
  if (/^\d{4}-\d{2}$/.test(period)) return period.replace('-', ' 年 ') + ' 月'
  return period
}

function formatReviewDate(value: string | null): string {
  if (!value) return '时间未记录'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString('zh-CN', { hour12: false })
}

function formatConfidence(value: number): string {
  return `${Math.round(Math.min(1, Math.max(0, value)) * 100)}%`
}

function percentage(count: number, total: number): string {
  return `${total ? (count / total) * 100 : 0}%`
}

function isoWeekRange(period: string): AnalyticsDateRange | null {
  const match = /^(\d{4})-W(\d{2})$/.exec(period)
  if (!match) return null
  const year = Number(match[1])
  const week = Number(match[2])
  const januaryFourth = new Date(Date.UTC(year, 0, 4))
  const weekDay = januaryFourth.getUTCDay() || 7
  const monday = new Date(januaryFourth)
  monday.setUTCDate(januaryFourth.getUTCDate() - weekDay + 1 + (week - 1) * 7)
  const nextMonday = new Date(monday)
  nextMonday.setUTCDate(monday.getUTCDate() + 7)
  return {
    start_date: `${monday.toISOString().slice(0, 10)}T00:00:00`,
    end_date: `${nextMonday.toISOString().slice(0, 10)}T00:00:00`,
  }
}

function periodRange(period: string): AnalyticsDateRange {
  if (/^\d{4}-\d{2}-\d{2}$/.test(period)) {
    return { start_date: startOfDay(period), end_date: nextDay(period) }
  }
  const week = isoWeekRange(period)
  if (week) return week
  const month = /^(\d{4})-(\d{2})$/.exec(period)
  if (month) {
    const start = `${month[1]}-${month[2]}-01`
    const next = new Date(Date.UTC(Number(month[1]), Number(month[2]), 1))
    return {
      start_date: startOfDay(start),
      end_date: `${next.toISOString().slice(0, 10)}T00:00:00`,
    }
  }
  return appliedRange.value
}

function autoGranularity(points: SentimentTrendPoint[]): TrendGranularity {
  if (points.length < 2) return 'day'
  const first = points[0]?.period ?? ''
  const last = points[points.length - 1]?.period ?? ''
  const start = new Date(first.length <= 7 ? `${first}-01` : first)
  const end = new Date(last.length <= 7 ? `${last}-01` : last)
  const spanDays = (end.getTime() - start.getTime()) / 86_400_000
  if (spanDays > 60) return 'month'
  if (spanDays > 14) return 'week'
  return 'day'
}

async function refresh(options: { allowAutoGranularity?: boolean } = {}): Promise<void> {
  const version = ++requestVersion
  loading.value = true
  errorMessage.value = ''
  forbidden.value = false
  const noRange = !appliedRange.value.start_date && !appliedRange.value.end_date
  try {
    const range = appliedRange.value
    const [nextTrend, nextReasons, nextReviews] = await Promise.all([
      merchantAnalyticsApi.getSentimentTrend(props.merchantId, {
        granularity: granularity.value,
        ...range,
      }),
      merchantAnalyticsApi.getNegativeReasons(props.merchantId, range),
      merchantAnalyticsApi.getReviews(props.merchantId, {
        ...range,
        limit: ASPECT_SAMPLE_LIMIT,
        offset: 0,
      }),
    ])
    if (version !== requestVersion) return

    if (options.allowAutoGranularity && noRange && nextTrend.length > 1) {
      const suggested = autoGranularity(nextTrend)
      if (suggested !== granularity.value) {
        granularity.value = suggested
        const betterTrend = await merchantAnalyticsApi.getSentimentTrend(props.merchantId, {
          granularity: suggested,
          ...range,
        })
        if (version !== requestVersion) return
        trend.value = betterTrend
      } else {
        trend.value = nextTrend
      }
    } else {
      trend.value = nextTrend
    }

    negativeReasons.value = nextReasons.map((item) => ({ label: item.reason, count: item.count }))
    analysisReviews.value = nextReviews
  } catch (error) {
    if (version !== requestVersion) return
    const apiError = toApiClientError(error)
    forbidden.value = apiError.status === 403
    errorMessage.value = forbidden.value
      ? '当前账号没有此商家的数据授权。'
      : getUserFacingError(error, '口碑分析加载失败，请稍后重试')
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

function applyFilters(): void {
  filterError.value = ''
  if (startDateInput.value && endDateInput.value && startDateInput.value > endDateInput.value) {
    filterError.value = '开始日期不能晚于结束日期。'
    return
  }
  appliedRange.value = selectedDateRange()
  void refresh()
}

async function openReviews(
  title: string,
  description: string,
  query: AnalyticsDateRange & { sentiment?: Sentiment; negative_reason?: string },
): Promise<void> {
  drawerOpen.value = true
  drawerTitle.value = title
  drawerDescription.value = description
  drawerReviews.value = []
  drawerError.value = ''
  drawerLoading.value = true
  try {
    drawerReviews.value = await merchantAnalyticsApi.getReviews(props.merchantId, {
      ...query,
      limit: 50,
      offset: 0,
    })
  } catch (error) {
    drawerError.value = getUserFacingError(error, '原点评加载失败，请稍后重试')
  } finally {
    drawerLoading.value = false
  }
}

function openSentiment(sentiment: Sentiment): void {
  const meta = sentimentMeta[sentiment]
  void openReviews(
    `${meta.label}点评`,
    `当前时间窗内参与${meta.label}情感统计的原点评`,
    { ...appliedRange.value, sentiment },
  )
}

function openTrend(point: SentimentTrendPoint, sentiment: Sentiment): void {
  const meta = sentimentMeta[sentiment]
  void openReviews(
    `${formatPeriod(point.period)} · ${meta.label}点评`,
    '该趋势时间段内参与统计的原点评',
    { ...periodRange(point.period), sentiment },
  )
}

function openAspect(label: string): void {
  drawerOpen.value = true
  drawerTitle.value = `特征「${label}」相关点评`
  drawerDescription.value = `从当前时间窗最近 ${ASPECT_SAMPLE_LIMIT} 条点评的 aspect_labels 中筛选`
  drawerError.value = ''
  drawerLoading.value = false
  drawerReviews.value = analysisReviews.value.filter((review) => review.aspect_labels.includes(label))
}

function openNegativeReason(reason: string): void {
  void openReviews(
    `差评归因「${reason}」`,
    '当前时间窗内包含该负面原因的原点评',
    { ...appliedRange.value, sentiment: 'NEGATIVE', negative_reason: reason },
  )
}

function closeDrawer(): void {
  drawerOpen.value = false
}

watch(granularity, () => {
  void refresh()
})

watch(() => props.merchantId, () => {
  drawerOpen.value = false
  void refresh()
})

onMounted(() => void refresh({ allowAutoGranularity: true }))
</script>

<template>
  <section
    class="analytics-dashboard"
    aria-label="商家口碑分析"
  >
    <form
      class="analytics-filters"
      @submit.prevent="applyFilters"
    >
      <label>
        <span>趋势口径</span>
        <select
          v-model="granularity"
          data-testid="granularity-filter"
        >
          <option value="day">按日</option>
          <option value="week">按周</option>
          <option value="month">按月</option>
        </select>
      </label>
      <label>
        <span>开始日期</span>
        <input
          v-model="startDateInput"
          type="date"
          data-testid="start-date-filter"
        >
      </label>
      <label>
        <span>结束日期</span>
        <input
          v-model="endDateInput"
          type="date"
          data-testid="end-date-filter"
        >
      </label>
      <button
        type="submit"
        :disabled="loading"
        data-testid="analytics-filter-submit"
      >
        {{ loading ? '更新中…' : '更新分析' }}
      </button>
      <p
        v-if="filterError"
        class="filter-error"
        role="alert"
      >
        {{ filterError }}
      </p>
    </form>

    <section
      v-if="loading && !trend.length"
      class="analytics-state"
      aria-live="polite"
    >
      正在汇总口碑数据…
    </section>
    <section
      v-else-if="errorMessage"
      :class="['analytics-state', { 'is-forbidden': forbidden }]"
      role="alert"
    >
      <strong>{{ forbidden ? '无权查看此商家' : '分析暂不可用' }}</strong>
      <p>{{ errorMessage }}</p>
      <button
        v-if="!forbidden"
        type="button"
        @click="() => refresh()"
      >
        重新加载
      </button>
    </section>
    <section
      v-else-if="!sampleSize"
      class="analytics-state"
    >
      <strong>当前时间窗暂无分析数据</strong>
      <p>调整日期范围后重试；只有已发布且完成当前版本分析的点评会进入统计。</p>
    </section>

    <template v-else>
      <section
        class="summary-grid"
        aria-label="口碑摘要"
      >
        <article>
          <span>分析样本</span>
          <strong>{{ sampleSize }}</strong>
          <small>当前统计时间窗</small>
        </article>
        <article>
          <span>正面率</span>
          <strong>{{ Math.round(positiveRate * 100) }}%</strong>
          <small>{{ sentimentCounts.POSITIVE }} 条正面点评</small>
        </article>
        <article>
          <span>特征标签</span>
          <strong>{{ aspectCounts.length }}</strong>
          <small>最多读取最近 {{ ASPECT_SAMPLE_LIMIT }} 条</small>
        </article>
        <article :class="{ 'is-warning': lowSample }">
          <span>趋势可信度</span>
          <strong>{{ lowSample ? '数据不足' : '可观察' }}</strong>
          <small>{{ lowSample ? `少于 ${LOW_SAMPLE_THRESHOLD} 条样本` : `按${granularityLabels[granularity]}聚合` }}</small>
        </article>
      </section>

      <p
        v-if="lowSample"
        class="sample-warning"
        role="note"
      >
        当前仅 {{ sampleSize }} 条样本，趋势可能波动较大，请勿据此形成确定性结论。
      </p>

      <section class="analytics-grid">
        <article class="chart-card sentiment-card">
          <header>
            <div><span class="eyebrow">情感分布</span><h2>正面 / 中性 / 负面</h2></div>
            <small>点击分类查看原点评</small>
          </header>
          <div
            class="distribution-chart"
            role="list"
            aria-label="情感分布图"
          >
            <button
              v-for="sentiment in sentiments"
              :key="sentiment"
              :class="`is-${sentiment.toLowerCase()}`"
              type="button"
              role="listitem"
              :data-testid="`sentiment-${sentiment.toLowerCase()}`"
              @click="openSentiment(sentiment)"
            >
              <span class="distribution-label"><strong>{{ sentimentMeta[sentiment].label }}</strong><b>{{ sentimentCounts[sentiment] }}</b></span>
              <span class="distribution-track"><i :style="{ width: percentage(sentimentCounts[sentiment], sampleSize) }" /></span>
              <small>{{ Math.round(sentimentCounts[sentiment] / sampleSize * 100) }}%</small>
            </button>
          </div>
        </article>

        <article class="chart-card trend-card">
          <header>
            <div><span class="eyebrow">情感趋势</span><h2>按{{ granularityLabels[granularity] }}统计</h2></div>
            <small>共 {{ sampleSize }} 条 · {{ trend.length }} 个{{ granularityLabels[granularity] }}期</small>
          </header>
          <div
            class="legend"
            aria-hidden="true"
          >
            <span class="positive">正面</span><span class="neutral">中性</span><span class="negative">负面</span>
          </div>
          <div
            class="trend-chart"
            aria-label="情感趋势图"
          >
            <div
              v-for="point in trend"
              :key="point.period"
              class="trend-row"
            >
              <span>{{ formatPeriod(point.period) }}</span>
              <div>
                <button
                  v-for="sentiment in sentiments"
                  :key="sentiment"
                  :class="`is-${sentiment.toLowerCase()}`"
                  type="button"
                  :disabled="point[sentimentMeta[sentiment].key] === 0"
                  :style="{ width: percentage(Number(point[sentimentMeta[sentiment].key]), point.positive + point.neutral + point.negative) }"
                  :aria-label="`${formatPeriod(point.period)} ${sentimentMeta[sentiment].label} ${point[sentimentMeta[sentiment].key]} 条，查看原点评`"
                  @click="openTrend(point, sentiment)"
                >
                  {{ point[sentimentMeta[sentiment].key] || '' }}
                </button>
              </div>
            </div>
          </div>
        </article>

        <article class="chart-card">
          <header>
            <div><span class="eyebrow">点评特征</span><h2>特征标签排行</h2></div>
            <small>来自点评特征标签</small>
          </header>
          <div
            v-if="aspectCounts.length"
            class="rank-chart"
            aria-label="点评特征排行"
          >
            <button
              v-for="item in aspectCounts"
              :key="item.label"
              type="button"
              @click="openAspect(item.label)"
            >
              <span>{{ item.label }}</span>
              <i><b :style="{ width: percentage(item.count, maxAspectCount) }" /></i>
              <strong>{{ item.count }}</strong>
            </button>
          </div>
          <p
            v-else
            class="chart-empty"
          >
            当前样本没有可展示的特征标签。
          </p>
        </article>

        <article class="chart-card">
          <header>
            <div><span class="eyebrow">差评归因</span><h2>负面原因排行</h2></div>
            <small>仅统计负面点评</small>
          </header>
          <div
            v-if="negativeReasons.length"
            class="rank-chart is-reason"
            aria-label="差评归因排行"
          >
            <button
              v-for="item in negativeReasons"
              :key="item.label"
              type="button"
              :data-testid="`reason-${item.label}`"
              @click="openNegativeReason(item.label)"
            >
              <span>{{ item.label }}</span>
              <i><b :style="{ width: percentage(item.count, maxReasonCount) }" /></i>
              <strong>{{ item.count }}</strong>
            </button>
          </div>
          <p
            v-else
            class="chart-empty"
          >
            当前时间窗没有差评归因数据。
          </p>
        </article>
      </section>
    </template>

    <div
      v-if="drawerOpen"
      class="review-backdrop"
      @click.self="closeDrawer"
    >
      <section
        class="review-drawer"
        role="dialog"
        aria-modal="true"
        :aria-label="drawerTitle"
      >
        <header>
          <div><span class="eyebrow">点评下钻</span><h2>{{ drawerTitle }}</h2><p>{{ drawerDescription }}</p></div>
          <button
            type="button"
            aria-label="关闭点评下钻"
            @click="closeDrawer"
          >
            关闭
          </button>
        </header>
        <p
          v-if="drawerLoading"
          class="drawer-state"
          aria-live="polite"
        >
          正在加载原点评…
        </p>
        <p
          v-else-if="drawerError"
          class="drawer-state is-error"
          role="alert"
        >
          {{ drawerError }}
        </p>
        <p
          v-else-if="!drawerReviews.length"
          class="drawer-state"
        >
          没有符合当前筛选条件的原点评。
        </p>
        <ul
          v-else
          class="review-list"
        >
          <li
            v-for="review in drawerReviews"
            :key="review.id"
          >
            <header>
              <span :class="`sentiment-chip is-${review.sentiment.toLowerCase()}`">{{ sentimentMeta[review.sentiment].label }}</span>
              <span>置信度 {{ formatConfidence(review.confidence) }}</span>
              <time>{{ formatReviewDate(review.review_date) }}</time>
            </header>
            <p>{{ review.review_text }}</p>
            <footer>
              <span
                v-for="aspect in review.aspect_labels"
                :key="`aspect-${aspect}`"
              >特征 · {{ aspect }}</span>
              <span
                v-for="reason in review.negative_reasons"
                :key="`reason-${reason}`"
                class="is-reason"
              >归因 · {{ reason }}</span>
            </footer>
          </li>
        </ul>
      </section>
    </div>
  </section>
</template>

<style scoped>
.analytics-dashboard { display: grid; gap: 22px; }
.analytics-filters { display: grid; grid-template-columns: 1fr 1fr 1fr auto; gap: 12px; align-items: end; border: 1px solid rgb(74 54 42 / 12%); border-radius: 16px; padding: 18px; background: rgb(255 255 255 / 62%); }
.analytics-filters label { display: grid; gap: 7px; color: #695b51; font-size: .74rem; font-weight: 800; }
.analytics-filters input, .analytics-filters select { min-height: 40px; border: 1px solid #d9ccc1; border-radius: 9px; padding: 8px 10px; background: #fffdfa; color: #392d26; }
.analytics-filters button, .analytics-state button { min-height: 40px; border: 1px solid var(--brand); border-radius: 9px; padding: 8px 16px; background: var(--brand); color: white; cursor: pointer; font-weight: 800; }
.analytics-filters button:disabled { cursor: wait; opacity: .6; }
.filter-error { grid-column: 1 / -1; margin: 0; color: #a4362b; font-size: .78rem; }
.analytics-state { border: 1px dashed #d5c6b9; border-radius: 16px; padding: 48px 24px; background: rgb(255 255 255 / 54%); color: #695b51; text-align: center; }
.analytics-state strong { display: block; color: #392d26; font-size: 1.1rem; }
.analytics-state p { margin: 8px 0 18px; }
.analytics-state.is-forbidden { border-color: #e3b3aa; background: #fff4f1; color: #8e3328; }
.summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.summary-grid article { border: 1px solid rgb(74 54 42 / 12%); border-radius: 14px; padding: 18px; background: rgb(255 255 255 / 66%); }
.summary-grid article.is-warning { border-color: #e1c78d; background: #fff9e9; }
.summary-grid span, .summary-grid small { display: block; color: #77675d; font-size: .72rem; }
.summary-grid strong { display: block; margin: 10px 0 5px; font-family: Georgia, "Noto Serif SC", serif; font-size: 1.8rem; }
.sample-warning { margin: -8px 0 0; border-left: 3px solid #c88c27; padding: 10px 14px; background: #fff8e6; color: #775f3d; font-size: .8rem; }
.analytics-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.chart-card { min-width: 0; border: 1px solid rgb(74 54 42 / 12%); border-radius: 18px; padding: 22px; background: rgb(255 255 255 / 70%); box-shadow: 0 14px 44px rgb(74 54 42 / 6%); }
.chart-card > header { display: flex; justify-content: space-between; gap: 18px; align-items: end; margin-bottom: 20px; }
.chart-card h2 { margin: 7px 0 0; font-size: 1.3rem; }
.chart-card header small { color: #88776c; font-size: .68rem; text-align: right; }
.distribution-chart { display: grid; gap: 15px; }
.distribution-chart button { display: grid; grid-template-columns: 90px 1fr 44px; gap: 12px; align-items: center; width: 100%; border: 0; padding: 3px 0; background: transparent; color: #392d26; cursor: pointer; text-align: left; }
.distribution-label { display: flex; justify-content: space-between; gap: 8px; font-size: .78rem; }
.distribution-track, .rank-chart i { height: 10px; overflow: hidden; border-radius: 999px; background: #e9dfd6; }
.distribution-track i, .rank-chart i b { display: block; height: 100%; min-width: 2px; border-radius: inherit; background: #3f9467; }
.distribution-chart .is-neutral .distribution-track i { background: #c79a43; }
.distribution-chart .is-negative .distribution-track i { background: #c95745; }
.distribution-chart button > small { color: #77675d; text-align: right; }
.legend { display: flex; gap: 14px; justify-content: flex-end; margin: -8px 0 12px; color: #77675d; font-size: .66rem; }
.legend span::before { display: inline-block; width: 7px; height: 7px; margin-right: 5px; border-radius: 50%; background: #3f9467; content: ""; }
.legend .neutral::before { background: #c79a43; }
.legend .negative::before { background: #c95745; }
.trend-chart { display: grid; gap: 10px; max-height: 340px; overflow: auto; padding-right: 3px; }
.trend-row { display: grid; grid-template-columns: max-content 1fr; gap: 10px; align-items: center; }
.trend-row > span { color: #77675d; font-size: .68rem; white-space: nowrap; }
.trend-row > div { display: flex; min-width: 0; height: 28px; overflow: hidden; border-radius: 7px; background: #eee5dc; }
.trend-row button { min-width: 0; border: 0; padding: 0 3px; background: #3f9467; color: white; cursor: pointer; font-size: .65rem; font-weight: 800; }
.trend-row button.is-neutral { background: #c79a43; }
.trend-row button.is-negative { background: #c95745; }
.trend-row button:disabled { cursor: default; }
.rank-chart { display: grid; gap: 10px; }
.rank-chart button { display: grid; grid-template-columns: minmax(90px, 130px) 1fr 30px; gap: 10px; align-items: center; border: 0; padding: 3px 0; background: transparent; color: #493a31; cursor: pointer; text-align: left; }
.rank-chart button > span { overflow: hidden; font-size: .76rem; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.rank-chart button > strong { color: #695b51; font-size: .72rem; text-align: right; }
.rank-chart i b { background: #b86b3e; }
.rank-chart.is-reason i b { background: #c95745; }
.chart-empty { margin: 42px 0; color: #88776c; font-size: .8rem; text-align: center; }
.review-backdrop { position: fixed; z-index: 100; inset: 0; display: flex; justify-content: flex-end; background: rgb(44 33 27 / 42%); }
.review-drawer { width: min(660px, 100%); height: 100%; overflow: auto; padding: 28px; background: #f8f3eb; box-shadow: -18px 0 60px rgb(44 33 27 / 18%); }
.review-drawer > header { display: flex; justify-content: space-between; gap: 24px; border-bottom: 1px solid #dfd3c8; padding-bottom: 20px; }
.review-drawer h2 { margin: 9px 0 5px; font-size: 1.55rem; }
.review-drawer header p { margin: 0; color: #77675d; font-size: .78rem; line-height: 1.55; }
.review-drawer > header > button { align-self: flex-start; border: 1px solid #d5c6b9; border-radius: 8px; padding: 7px 11px; background: #fffdfa; color: #695b51; cursor: pointer; font-weight: 800; }
.drawer-state { margin-top: 24px; border-radius: 10px; padding: 22px; background: #fffdfa; color: #77675d; text-align: center; }
.drawer-state.is-error { background: #fff0ed; color: #a4362b; }
.review-list { display: grid; gap: 12px; margin: 20px 0 0; padding: 0; list-style: none; }
.review-list > li { border: 1px solid #ded1c6; border-radius: 13px; padding: 16px; background: #fffdfa; }
.review-list li > header { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; color: #806f64; font-size: .68rem; }
.review-list time { margin-left: auto; }
.review-list p { margin: 13px 0; color: #392d26; line-height: 1.7; white-space: pre-wrap; }
.review-list footer { display: flex; flex-wrap: wrap; gap: 6px; }
.review-list footer span, .sentiment-chip { border-radius: 999px; padding: 4px 7px; background: #eee5dc; color: #695b51; font-size: .64rem; font-weight: 800; }
.review-list footer span.is-reason, .sentiment-chip.is-negative { background: #f4dfdb; color: #9e3c30; }
.sentiment-chip.is-positive { background: #e4f2e9; color: #2c704b; }
.sentiment-chip.is-neutral { background: #f5ead2; color: #806226; }
@media (max-width: 800px) {
  .analytics-filters { grid-template-columns: 1fr 1fr; }
  .analytics-filters button { grid-column: 1 / -1; }
  .summary-grid { grid-template-columns: 1fr 1fr; }
  .analytics-grid { grid-template-columns: 1fr; }
}
@media (max-width: 520px) {
  .analytics-filters, .summary-grid { grid-template-columns: 1fr; }
  .analytics-filters button { grid-column: auto; }
  .chart-card { padding: 17px; }
  .chart-card > header { align-items: flex-start; flex-direction: column; }
  .chart-card header small { text-align: left; }
  .distribution-chart button { grid-template-columns: 76px 1fr 36px; }
  .rank-chart button { grid-template-columns: 92px 1fr 26px; }
  .review-drawer { padding: 20px 15px; }
  .review-list time { width: 100%; margin-left: 0; }
}
</style>
