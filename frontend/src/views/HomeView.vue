<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { getReadiness } from '@/api/health'
import RecommendationResults from '@/components/RecommendationResults.vue'
import StatusCard from '@/components/StatusCard.vue'
import { useAuthStore } from '@/stores/auth'
import type { MerchantRecommendation, RecommendationSource } from '@/types/recommendation'

type ApiState = 'checking' | 'ready' | 'unavailable'

const apiState = ref<ApiState>('checking')
const authStore = useAuthStore()
const router = useRouter()

const sampleRecommendations: MerchantRecommendation[] = [
  {
    merchant_id: 'merchant-demo-001',
    name: '星光咖啡',
    category: '咖啡馆',
    reason: '环境安静、工作日下午客流较少，适合学习或小组讨论。',
    distance_meter: 850,
    avg_price_cent: 5800,
    rating: 4.6,
    business_status: 'OPEN',
    data_updated_at: '2026-07-17T04:00:00Z',
    source_chunk_ids: ['chunk-demo-001'],
    tags: ['安静', '有插座', '可久坐'],
  },
  {
    merchant_id: 'merchant-demo-002',
    name: '山岚小馆',
    category: '创意菜',
    reason: '座位间距舒适、近期服务评价稳定，适合两人约会。',
    distance_meter: 1600,
    avg_price_cent: 9600,
    rating: 4.7,
    business_status: 'OPEN',
    data_updated_at: '2026-07-14T08:00:00Z',
    source_chunk_ids: ['chunk-demo-002'],
    tags: ['约会', '环境舒适'],
  },
]

const sampleSources: RecommendationSource[] = [
  {
    chunk_id: 'chunk-demo-001',
    source_location: '点评 / 星光咖啡 / 2026-07-16',
    source_url: '/app/reviews/review-demo-001#chunk-demo-001',
    content: '工作日下午客流较少，靠窗位置安静，而且每张桌子附近都有插座。',
    highlight_text: '靠窗位置安静',
    score: 0.91,
  },
  {
    chunk_id: 'chunk-demo-002',
    source_location: '点评 / 山岚小馆 / 2026-07-13',
    source_url: '/app/reviews/review-demo-002#chunk-demo-002',
    content: '座位间距舒适，灯光柔和，服务员会主动确认忌口和上菜节奏。',
    highlight_text: '座位间距舒适',
    score: 0.88,
  },
]

onMounted(async () => {
  try {
    apiState.value = (await getReadiness()).status === 'ready' ? 'ready' : 'unavailable'
  } catch {
    apiState.value = 'unavailable'
  }
})

async function logout(): Promise<void> {
  await authStore.logout()
  await router.replace({ name: 'login' })
}
</script>

<template>
  <main class="home-page">
    <div class="topline">
      <span class="eyebrow">LOCAL LIFE · AI COPILOT</span>
      <el-button
        text
        @click="logout"
      >
        退出登录
      </el-button>
    </div>
    <h1>用户工作台已就绪</h1>
    <p class="intro">
      Vue、路由、状态管理、组件库与类型化 API Client 已接通，可继续实现探店和流式对话。
    </p>
    <StatusCard
      label="API 与数据依赖"
      :state="apiState"
    />
    <RecommendationResults
      :recommendations="sampleRecommendations"
      :sources="sampleSources"
      now="2026-07-17T05:00:00Z"
    />
    <nav aria-label="开发入口">
      <a
        href="/docs"
        target="_blank"
        rel="noopener noreferrer"
      >查看 API 文档</a>
      <a
        href="/health/ready"
        target="_blank"
        rel="noopener noreferrer"
      >查看健康状态</a>
    </nav>
  </main>
</template>
