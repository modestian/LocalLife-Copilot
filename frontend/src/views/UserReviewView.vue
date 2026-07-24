<script setup lang="ts">
import ProductTopBar from '@/components/ProductTopBar.vue'
import UserReviewPanel from '@/components/UserReviewPanel.vue'
</script>

<template>
  <main class="review-page">
    <ProductTopBar active="discover" />

    <section class="review-hero">
      <span class="eyebrow">USER REVIEW</span>
      <h1>分享你的<br>真实体验</h1>
      <p>对去过的商家发表评价，帮助更多人做出更好的选择。评论审核通过后将公开展示。</p>
    </section>

    <UserReviewPanel />
  </main>
</template>

<style scoped>
.review-page { width: min(860px, calc(100% - 48px)); margin: 0 auto; padding: 28px 0 80px; }
.review-hero { padding: 48px 0 36px; }
.review-hero .eyebrow { color: var(--brand, #b03c27); font-size: .72rem; font-weight: 900; letter-spacing: .14em; }
.review-hero h1 { margin: 14px 0 16px; font-size: clamp(2.4rem, 5vw, 3.8rem); }
.review-hero p { max-width: 560px; margin: 0; color: var(--muted, #88776c); line-height: 1.75; }
@media (max-width: 760px) {
  .review-page { width: min(100% - 28px, 620px); }
  .review-hero { padding-top: 36px; }
}
</style>
