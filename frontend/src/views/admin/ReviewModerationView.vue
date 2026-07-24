<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { getUserFacingError } from '@/api/errors'
import { reviewsApi, type AdminReviewItem } from '@/api/reviews'
import ProductTopBar from '@/components/ProductTopBar.vue'

type StatusFilter = 'PENDING' | 'PUBLISHED' | 'REJECTED'

const statusFilter = ref<StatusFilter>('PENDING')
const reviews = ref<AdminReviewItem[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const errorMessage = ref('')
const notice = ref('')

const moderatingId = ref<string | null>(null)
const moderateReason = ref('')

onMounted(() => {
  void loadReviews()
})

async function loadReviews(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await reviewsApi.getPendingReviews(statusFilter.value, page.value, 10)
    reviews.value = result.items
    total.value = result.total
  } catch (err: unknown) {
    errorMessage.value = getUserFacingError(err)
  } finally {
    loading.value = false
  }
}

function switchStatus(status: StatusFilter): void {
  statusFilter.value = status
  page.value = 1
  void loadReviews()
}

function onPageChange(newPage: number): void {
  page.value = newPage
  void loadReviews()
}

function startModerate(reviewId: string): void {
  moderatingId.value = reviewId
  moderateReason.value = ''
}

function cancelModerate(): void {
  moderatingId.value = null
  moderateReason.value = ''
}

async function submitModerate(decision: 'APPROVE' | 'REJECT'): Promise<void> {
  if (!moderatingId.value) return
  errorMessage.value = ''
  try {
    await reviewsApi.moderateReview(moderatingId.value, {
      decision,
      reason: moderateReason.value.trim(),
    })
    notice.value = decision === 'APPROVE' ? '已通过该评论' : '已拒绝该评论'
    moderatingId.value = null
    moderateReason.value = ''
    await loadReviews()
  } catch (err: unknown) {
    errorMessage.value = getUserFacingError(err)
  }
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    PENDING: '待审核',
    PUBLISHED: '已通过',
    REJECTED: '已拒绝',
  }
  return map[status] ?? status
}

function statusType(status: string): 'warning' | 'success' | 'danger' | 'info' {
  const map: Record<string, 'warning' | 'success' | 'danger' | 'info'> = {
    PENDING: 'warning',
    PUBLISHED: 'success',
    REJECTED: 'danger',
  }
  return map[status] ?? 'info'
}

function formatDate(iso: string | null): string {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN')
}
</script>

<template>
  <main class="home-page">
    <ProductTopBar active="admin" />
    <h1>评论审核</h1>
    <p class="intro">
      审核用户提交的商家评论，通过后评论将公开展示。
    </p>

    <div class="moderation-toolbar">
      <button
        :class="['filter-btn', { active: statusFilter === 'PENDING' }]"
        @click="switchStatus('PENDING')"
      >
        待审核
      </button>
      <button
        :class="['filter-btn', { active: statusFilter === 'PUBLISHED' }]"
        @click="switchStatus('PUBLISHED')"
      >
        已通过
      </button>
      <button
        :class="['filter-btn', { active: statusFilter === 'REJECTED' }]"
        @click="switchStatus('REJECTED')"
      >
        已拒绝
      </button>
    </div>

    <p
      v-if="notice"
      class="notice"
    >
      {{ notice }}
    </p>
    <p
      v-if="errorMessage"
      class="error"
    >
      {{ errorMessage }}
    </p>

    <div
      v-if="loading"
      class="loading"
    >
      加载中...
    </div>

    <div
      v-else-if="reviews.length === 0"
      class="empty"
    >
      暂无{{ statusLabel(statusFilter) }}的评论
    </div>

    <div
      v-else
      class="review-list"
    >
      <div
        v-for="review in reviews"
        :key="review.id"
        class="review-card"
      >
        <div class="review-header">
          <span class="review-author">{{ review.author ?? '匿名用户' }}</span>
          <el-tag
            :type="statusType(review.status)"
            size="small"
          >
            {{ statusLabel(review.status) }}
          </el-tag>
        </div>
        <div class="review-rating">
          <el-rate
            :model-value="review.rating ?? 0"
            disabled
          />
        </div>
        <p class="review-content">
          {{ review.content }}
        </p>
        <div class="review-meta">
          <span>来源: {{ review.source_type }}</span>
          <span>时间: {{ formatDate(review.created_at) }}</span>
        </div>

        <!-- Moderation actions -->
        <div
          v-if="review.status === 'PENDING'"
          class="review-actions"
        >
          <template v-if="moderatingId === review.id">
            <div class="moderate-form">
              <el-input
                v-model="moderateReason"
                placeholder="拒绝理由（留空则默认“不符合社区规范”）"
                :maxlength="1000"
                show-word-limit
              />
              <div class="moderate-buttons">
                <el-button
                  type="success"
                  size="small"
                  @click="submitModerate('APPROVE')"
                >
                  通过
                </el-button>
                <el-button
                  type="danger"
                  size="small"
                  @click="submitModerate('REJECT')"
                >
                  拒绝
                </el-button>
                <el-button
                  size="small"
                  @click="cancelModerate"
                >
                  取消
                </el-button>
              </div>
            </div>
          </template>
          <template v-else>
            <el-button
              type="primary"
              size="small"
              @click="startModerate(review.id)"
            >
              审核
            </el-button>
          </template>
        </div>
      </div>
    </div>

    <el-pagination
      v-if="total > 10"
      :current-page="page"
      :page-size="10"
      :total="total"
      layout="prev, pager, next"
      @current-change="onPageChange"
    />
  </main>
</template>

<style scoped>
.moderation-toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.filter-btn {
  padding: 6px 16px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  background: #fff;
  cursor: pointer;
  font-size: 14px;
}

.filter-btn.active {
  background: #409eff;
  color: #fff;
  border-color: #409eff;
}

.notice {
  color: #67c23a;
  margin-bottom: 12px;
}

.error {
  color: #f56c6c;
  margin-bottom: 12px;
}

.loading,
.empty {
  text-align: center;
  color: #909399;
  padding: 40px 0;
}

.review-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.review-card {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 16px;
  background: #fff;
}

.review-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.review-author {
  font-weight: 600;
}

.review-rating {
  margin-bottom: 8px;
}

.review-content {
  margin: 0 0 8px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.review-meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: #909399;
  margin-bottom: 12px;
}

.review-actions {
  border-top: 1px solid #ebeef5;
  padding-top: 12px;
}

.moderate-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.moderate-buttons {
  display: flex;
  gap: 8px;
}
</style>
