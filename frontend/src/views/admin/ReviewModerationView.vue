<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { getUserFacingError } from '@/api/errors'
import { reviewsApi, type AdminReplyItem, type AdminReviewItem } from '@/api/reviews'
import ProductTopBar from '@/components/ProductTopBar.vue'

type StatusFilter = 'PENDING' | 'PUBLISHED' | 'REJECTED'
type ModerationTarget = 'REVIEW' | 'REPLY'

const moderationTarget = ref<ModerationTarget>('REVIEW')
const statusFilter = ref<StatusFilter>('PENDING')
const reviews = ref<AdminReviewItem[]>([])
const replies = ref<AdminReplyItem[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const errorMessage = ref('')
const notice = ref('')

const moderatingId = ref<string | null>(null)
const moderateReason = ref('')

onMounted(() => {
  void loadItems()
})

async function loadItems(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    if (moderationTarget.value === 'REVIEW') {
      const result = await reviewsApi.getPendingReviews(statusFilter.value, page.value, 10)
      reviews.value = result.items
      total.value = result.total
    } else {
      const result = await reviewsApi.getPendingReplies(statusFilter.value, page.value, 10)
      replies.value = result.items
      total.value = result.total
    }
  } catch (err: unknown) {
    errorMessage.value = getUserFacingError(err)
  } finally {
    loading.value = false
  }
}

function switchTarget(target: ModerationTarget): void {
  moderationTarget.value = target
  statusFilter.value = 'PENDING'
  page.value = 1
  notice.value = ''
  moderatingId.value = null
  void loadItems()
}

function switchStatus(status: StatusFilter): void {
  statusFilter.value = status
  page.value = 1
  void loadItems()
}

function onPageChange(newPage: number): void {
  page.value = newPage
  void loadItems()
}

function startModerate(itemId: string): void {
  moderatingId.value = itemId
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
    const payload = { decision, reason: moderateReason.value.trim() }
    if (moderationTarget.value === 'REVIEW') {
      await reviewsApi.moderateReview(moderatingId.value, payload)
      notice.value = decision === 'APPROVE' ? '已通过该评论' : '已拒绝该评论'
    } else {
      await reviewsApi.moderateReply(moderatingId.value, payload)
      notice.value = decision === 'APPROVE' ? '已通过该商家回复' : '已拒绝该商家回复'
    }
    moderatingId.value = null
    moderateReason.value = ''
    await loadItems()
  } catch (err: unknown) {
    errorMessage.value = getUserFacingError(err)
  }
}

function toneLabel(tone: string): string {
  const map: Record<string, string> = {
    EMPATHETIC: '真诚共情',
    PROFESSIONAL: '专业克制',
    CONCISE: '简洁直接',
  }
  return map[tone] ?? tone
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
    <h1>内容审核</h1>
    <p class="intro">
      {{ moderationTarget === 'REVIEW'
        ? '审核用户提交的商家评论，通过后评论将公开展示。'
        : '审核商家对用户点评的回复，通过后回复将对用户展示。' }}
    </p>

    <div class="moderation-toolbar target-toolbar">
      <button
        :class="['filter-btn', { active: moderationTarget === 'REVIEW' }]"
        @click="switchTarget('REVIEW')"
      >
        用户评论
      </button>
      <button
        :class="['filter-btn', { active: moderationTarget === 'REPLY' }]"
        @click="switchTarget('REPLY')"
      >
        商家回复
      </button>
    </div>

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
      v-else-if="(moderationTarget === 'REVIEW' ? reviews.length : replies.length) === 0"
      class="empty"
    >
      暂无{{ statusLabel(statusFilter) }}的{{ moderationTarget === 'REVIEW' ? '评论' : '商家回复' }}
    </div>

    <div
      v-else-if="moderationTarget === 'REVIEW'"
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

    <div
      v-else
      class="review-list"
    >
      <div
        v-for="reply in replies"
        :key="reply.id"
        class="review-card"
      >
        <div class="review-header">
          <span class="review-author">商家回复</span>
          <el-tag
            :type="statusType(reply.status)"
            size="small"
          >
            {{ statusLabel(reply.status) }}
          </el-tag>
        </div>
        <p class="review-content">
          {{ reply.content }}
        </p>
        <div class="review-meta">
          <span>语气: {{ toneLabel(reply.tone) }}</span>
          <span>来源: {{ reply.source === 'SUGGESTION' ? 'AI建议' : '手动输入' }}</span>
          <span>时间: {{ formatDate(reply.created_at) }}</span>
        </div>

        <!-- Moderation actions -->
        <div
          v-if="reply.status === 'PENDING'"
          class="review-actions"
        >
          <template v-if="moderatingId === reply.id">
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
              @click="startModerate(reply.id)"
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

.target-toolbar {
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #ebeef5;
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
