<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { reviewsApi, type MerchantDirectoryItem, type ReviewItem } from '@/api/reviews'

const merchants = ref<MerchantDirectoryItem[]>([])
const selectedMerchantId = ref('')
const rating = ref(0)
const content = ref('')
const submitting = ref(false)
const submitMessage = ref('')
const submitError = ref('')

const myReviews = ref<ReviewItem[]>([])
const reviewsTotal = ref(0)
const reviewsPage = ref(1)
const loadingReviews = ref(false)

onMounted(async () => {
  await loadMerchants()
  await loadMyReviews()
})

async function loadMerchants(keyword?: string): Promise<void> {
  try {
    const result = await reviewsApi.getMerchantDirectory(keyword, 50)
    merchants.value = result.items
  } catch {
    merchants.value = []
  }
}

async function loadMyReviews(): Promise<void> {
  loadingReviews.value = true
  try {
    const result = await reviewsApi.getMyReviews(reviewsPage.value, 10)
    myReviews.value = result.items
    reviewsTotal.value = result.total
  } catch {
    myReviews.value = []
  } finally {
    loadingReviews.value = false
  }
}

async function submitReview(): Promise<void> {
  submitMessage.value = ''
  submitError.value = ''

  if (!selectedMerchantId.value) {
    submitError.value = '请选择商家'
    return
  }
  if (!content.value.trim()) {
    submitError.value = '请输入评论内容'
    return
  }
  if (rating.value === 0) {
    submitError.value = '请选择评分'
    return
  }

  submitting.value = true
  try {
    await reviewsApi.submitReview(selectedMerchantId.value, {
      content: content.value.trim(),
      rating: rating.value,
    })
    submitMessage.value = '评论已提交，等待审核'
    content.value = ''
    rating.value = 0
    selectedMerchantId.value = ''
    await loadMyReviews()
  } catch (error: unknown) {
    const err = error as { response?: { data?: { code?: string; message?: string } } }
    if (err.response?.data?.code === 'SENSITIVE_CONTENT_REJECTED') {
      submitError.value = '评论包含受限内容，已拒绝提交'
    } else {
      submitError.value = err.response?.data?.message ?? '提交失败，请稍后重试'
    }
  } finally {
    submitting.value = false
  }
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    PENDING: '待审核',
    PUBLISHED: '已发布',
    REJECTED: '已拒绝',
    DELETED: '已删除',
  }
  return map[status] ?? status
}

function statusType(status: string): string {
  const map: Record<string, string> = {
    PENDING: 'warning',
    PUBLISHED: 'success',
    REJECTED: 'danger',
    DELETED: 'info',
  }
  return map[status] ?? 'info'
}

function merchantName(merchantId: string): string {
  const found = merchants.value.find((m) => m.id === merchantId)
  return found?.name ?? merchantId.slice(0, 8)
}
</script>

<template>
  <div class="review-panel">
    <section class="review-form">
      <h2>发表评价</h2>

      <div class="form-field">
        <label for="merchant-select">选择商家</label>
        <el-select
          id="merchant-select"
          v-model="selectedMerchantId"
          filterable
          remote
          :remote-method="loadMerchants"
          placeholder="搜索并选择商家"
          style="width: 100%"
        >
          <el-option
            v-for="merchant in merchants"
            :key="merchant.id"
            :label="merchant.name"
            :value="merchant.id"
          />
        </el-select>
      </div>

      <div class="form-field">
        <label>评分</label>
        <el-rate
          v-model="rating"
          :max="5"
          :texts="['很差', '较差', '一般', '较好', '很好']"
          show-text
        />
      </div>

      <div class="form-field">
        <label for="review-content">评论内容</label>
        <el-input
          id="review-content"
          v-model="content"
          type="textarea"
          :rows="5"
          :maxlength="10000"
          show-word-limit
          placeholder="分享你对这家店的体验…"
        />
      </div>

      <el-button
        type="primary"
        :loading="submitting"
        :disabled="!selectedMerchantId || !content.trim() || rating === 0"
        @click="submitReview"
      >
        提交评价
      </el-button>

      <p
        v-if="submitMessage"
        class="submit-message success"
      >
        {{ submitMessage }}
      </p>
      <p
        v-if="submitError"
        class="submit-message error"
      >
        {{ submitError }}
      </p>
    </section>

    <section class="my-reviews">
      <h2>我的评价</h2>
      <p
        v-if="myReviews.length === 0 && !loadingReviews"
        class="empty-state"
      >
        暂无评价记录
      </p>
      <ul v-else>
        <li
          v-for="review in myReviews"
          :key="review.id"
          class="review-item"
        >
          <div class="review-item__header">
            <strong>{{ merchantName(review.merchant_id) }}</strong>
            <el-tag
              :type="statusType(review.status)"
              size="small"
            >
              {{ statusLabel(review.status) }}
            </el-tag>
          </div>
          <p class="review-item__content">
            {{ review.content }}
          </p>
          <div class="review-item__meta">
            <span v-if="review.rating !== null">★ {{ review.rating }}</span>
            <time>{{ new Date(review.created_at).toLocaleDateString('zh-CN') }}</time>
          </div>
        </li>
      </ul>
      <div
        v-if="reviewsTotal > 10"
        class="pagination"
      >
        <el-pagination
          v-model:current-page="reviewsPage"
          :page-size="10"
          :total="reviewsTotal"
          layout="prev, pager, next"
          @current-change="loadMyReviews"
        />
      </div>
    </section>
  </div>
</template>

<style scoped>
.review-panel { display: grid; gap: 40px; }
.review-form, .my-reviews { border: 1px solid var(--line, #e8e0d8); border-radius: 16px; padding: 28px; background: var(--surface, #fffdfa); }
.review-form h2, .my-reviews h2 { margin: 0 0 20px; font-size: 1.1rem; }
.form-field { margin-bottom: 18px; }
.form-field label { display: block; margin-bottom: 6px; font-size: .82rem; font-weight: 700; color: #695b51; }
.submit-message { margin-top: 12px; font-size: .84rem; }
.submit-message.success { color: #2e7d32; }
.submit-message.error { color: #c62828; }
.empty-state { color: #88776c; font-size: .88rem; }
.my-reviews ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 14px; }
.review-item { border: 1px solid #efe8e0; border-radius: 12px; padding: 14px 16px; }
.review-item__header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.review-item__content { margin: 0 0 8px; font-size: .88rem; color: #392d26; line-height: 1.6; }
.review-item__meta { display: flex; gap: 14px; font-size: .76rem; color: #88776c; }
.pagination { margin-top: 16px; display: flex; justify-content: center; }
</style>
