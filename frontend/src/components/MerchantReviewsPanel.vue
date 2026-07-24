<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'

import { requestData } from '@/api/client'
import { getUserFacingError } from '@/api/errors'

interface ReviewRecord {
  id: string
  content: string
  rating: number | null
  author_ref: string | null
  reviewed_at: string | null
  tags: string[]
  sentiment: string | null
  confidence: number | null
  source: string | null
}

const props = defineProps<{
  merchantId: string
}>()

const reviews = ref<ReviewRecord[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 10
const loading = ref(false)
const errorMessage = ref('')

const sentimentFilter = ref('')
const startAt = ref('')
const endAt = ref('')

onMounted(() => void loadReviews())

watch(() => props.merchantId, () => {
  page.value = 1
  void loadReviews()
})

async function loadReviews(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const params: Record<string, unknown> = { page: page.value, page_size: pageSize }
    if (sentimentFilter.value) params.sentiment = sentimentFilter.value
    if (startAt.value) params.start_at = `${startAt.value}T00:00:00`
    if (endAt.value) params.end_at = `${endAt.value}T23:59:59`
    const result = await requestData<{ items: ReviewRecord[]; total: number }>({
      method: 'GET',
      url: `/api/v1/merchants/${encodeURIComponent(props.merchantId)}/reviews`,
      params,
    })
    reviews.value = result.items
    total.value = result.total
  } catch (err: unknown) {
    errorMessage.value = getUserFacingError(err)
  } finally {
    loading.value = false
  }
}

function applyFilters(): void {
  page.value = 1
  void loadReviews()
}

function onPageChange(newPage: number): void {
  page.value = newPage
  void loadReviews()
}

function sentimentLabel(s: string | null): string {
  const map: Record<string, string> = { POSITIVE: '好评', NEUTRAL: '中评', NEGATIVE: '差评' }
  return s ? (map[s] ?? s) : '未分析'
}

function sentimentClass(s: string | null): string {
  const map: Record<string, string> = { POSITIVE: 'is-positive', NEUTRAL: 'is-neutral', NEGATIVE: 'is-negative' }
  return s ? (map[s] ?? '') : ''
}

function formatDate(iso: string | null): string {
  if (!iso) return '-'
  return new Date(iso).toLocaleDateString('zh-CN')
}

function formatStars(rating: number | null): string {
  if (rating == null) return '无评分'
  return '★'.repeat(Math.round(rating)) + '☆'.repeat(5 - Math.round(rating))
}
</script>

<template>
  <section
    class="reviews-panel"
    aria-label="客户评论"
  >
    <header class="panel-header">
      <div>
        <span class="eyebrow">REVIEWS</span>
        <h2>客户评论</h2>
      </div>
      <small>共 {{ total }} 条已发布评论</small>
    </header>

    <form
      class="reviews-filters"
      @submit.prevent="applyFilters"
    >
      <label>
        <span>情感</span>
        <select v-model="sentimentFilter">
          <option value="">全部</option>
          <option value="POSITIVE">好评</option>
          <option value="NEUTRAL">中评</option>
          <option value="NEGATIVE">差评</option>
        </select>
      </label>
      <label>
        <span>开始日期</span>
        <input
          v-model="startAt"
          type="date"
        >
      </label>
      <label>
        <span>结束日期</span>
        <input
          v-model="endAt"
          type="date"
        >
      </label>
      <button type="submit">筛选</button>
    </form>

    <p
      v-if="errorMessage"
      class="error"
    >
      {{ errorMessage }}
    </p>

    <div
      v-if="loading"
      class="loading-state"
    >
      加载中...
    </div>

    <div
      v-else-if="reviews.length === 0"
      class="empty-state"
    >
      暂无评论数据
    </div>

    <ul
      v-else
      class="review-list"
    >
      <li
        v-for="review in reviews"
        :key="review.id"
        class="review-item"
      >
        <div class="review-top">
          <span class="review-author">{{ review.author_ref ?? '匿名顾客' }}</span>
          <span class="review-badges">
            <span
              v-if="review.sentiment"
              :class="['sentiment-badge', sentimentClass(review.sentiment)]"
            >
              {{ sentimentLabel(review.sentiment) }}
            </span>
            <span
              v-else
              class="sentiment-badge is-unanalyzed"
            >未分析</span>
          </span>
        </div>
        <div class="review-rating">
          <span class="stars">{{ formatStars(review.rating) }}</span>
          <time>{{ formatDate(review.reviewed_at) }}</time>
        </div>
        <p class="review-content">{{ review.content }}</p>
        <div
          v-if="review.tags && review.tags.length"
          class="review-tags"
        >
          <span
            v-for="tag in review.tags"
            :key="tag"
            class="tag"
          >{{ tag }}</span>
        </div>
      </li>
    </ul>

    <nav
      v-if="total > pageSize"
      class="pagination"
    >
      <button
        :disabled="page <= 1"
        @click="onPageChange(page - 1)"
      >
        上一页
      </button>
      <span>{{ page }} / {{ Math.ceil(total / pageSize) }}</span>
      <button
        :disabled="page >= Math.ceil(total / pageSize)"
        @click="onPageChange(page + 1)"
      >
        下一页
      </button>
    </nav>
  </section>
</template>

<style scoped>
.reviews-panel {
  border: 1px solid rgb(74 54 42 / 12%);
  border-radius: 16px;
  padding: 24px;
  background: rgb(255 255 255 / 62%);
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 18px;
}

.panel-header .eyebrow {
  display: block;
  font-size: 0.68rem;
  font-weight: 900;
  letter-spacing: 0.14em;
  color: #9d3423;
  margin-bottom: 4px;
}

.panel-header h2 {
  margin: 0;
  font-size: 1.3rem;
}

.panel-header small {
  color: #695b51;
  font-size: 0.78rem;
}

.reviews-filters {
  display: flex;
  gap: 12px;
  align-items: end;
  flex-wrap: wrap;
  margin-bottom: 18px;
}

.reviews-filters label {
  display: grid;
  gap: 5px;
  font-size: 0.72rem;
  font-weight: 700;
  color: #695b51;
}

.reviews-filters select,
.reviews-filters input {
  padding: 7px 10px;
  border: 1px solid rgb(74 54 42 / 18%);
  border-radius: 8px;
  font-size: 0.82rem;
  background: #fff;
}

.reviews-filters button {
  padding: 8px 18px;
  border: none;
  border-radius: 8px;
  background: #9d3423;
  color: #fff;
  font-weight: 700;
  font-size: 0.8rem;
  cursor: pointer;
}

.reviews-filters button:hover {
  background: #7c291b;
}

.error {
  color: #d32f2f;
  font-size: 0.82rem;
  margin-bottom: 12px;
}

.loading-state,
.empty-state {
  text-align: center;
  color: #909399;
  padding: 36px 0;
  font-size: 0.88rem;
}

.review-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 14px;
}

.review-item {
  border: 1px solid rgb(74 54 42 / 10%);
  border-radius: 12px;
  padding: 16px;
  background: #fff;
}

.review-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.review-author {
  font-weight: 700;
  font-size: 0.88rem;
}

.sentiment-badge {
  font-size: 0.7rem;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
}

.sentiment-badge.is-positive {
  background: #e8f5e9;
  color: #2e7d32;
}

.sentiment-badge.is-neutral {
  background: #f5ead2;
  color: #806226;
}

.sentiment-badge.is-negative {
  background: #fce4ec;
  color: #c62828;
}

.sentiment-badge.is-unanalyzed {
  background: #f5f5f5;
  color: #909399;
}

.review-badges {
  display: flex;
  gap: 6px;
  align-items: center;
}

.source-badge {
  font-size: 0.66rem;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
  background: #e8eaf6;
  color: #3949ab;
}

.review-rating {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.stars {
  color: #e6a23c;
  font-size: 0.9rem;
  letter-spacing: 1px;
}

.review-rating time {
  font-size: 0.72rem;
  color: #909399;
}

.review-content {
  margin: 0 0 8px;
  font-size: 0.86rem;
  line-height: 1.6;
  white-space: pre-wrap;
}

.review-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.review-tags .tag {
  font-size: 0.68rem;
  padding: 2px 8px;
  border-radius: 4px;
  background: #f0ebe6;
  color: #695b51;
}

.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 14px;
  margin-top: 18px;
}

.pagination button {
  padding: 6px 14px;
  border: 1px solid rgb(74 54 42 / 18%);
  border-radius: 6px;
  background: #fff;
  cursor: pointer;
  font-size: 0.78rem;
}

.pagination button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.pagination span {
  font-size: 0.78rem;
  color: #695b51;
}

@media (max-width: 600px) {
  .reviews-filters {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
