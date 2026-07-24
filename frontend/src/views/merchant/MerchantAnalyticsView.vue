<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { merchantDirectoryApi } from '@/api/merchants'
import MerchantAnalyticsDashboard from '@/components/MerchantAnalyticsDashboard.vue'
import MerchantInsightWorkbench from '@/components/MerchantInsightWorkbench.vue'
import MerchantReviewsPanel from '@/components/MerchantReviewsPanel.vue'
import ProductTopBar from '@/components/ProductTopBar.vue'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const adminMerchantInput = ref('')
const merchantNames = ref<Record<string, string>>({})

const merchantIds = computed(() => [
  ...new Set(
    (authStore.currentUser?.resource_scopes ?? [])
      .filter((scope) => scope.resource_type === 'MERCHANT')
      .map((scope) => scope.resource_id.trim())
      .filter(Boolean),
  ),
])

const isPlatformAdmin = computed(() =>
  authStore.currentUser?.roles.some((role) => role.code.toUpperCase() === 'PLATFORM_ADMIN') ?? false,
)

const routeMerchantId = computed(() => String(route.params.merchantId ?? '').trim())
const selectedMerchantId = computed(() => {
  if (isPlatformAdmin.value) return routeMerchantId.value
  if (routeMerchantId.value) {
    return merchantIds.value.includes(routeMerchantId.value) ? routeMerchantId.value : ''
  }
  return merchantIds.value[0] ?? ''
})

const accessMessage = computed(() => {
  if (isPlatformAdmin.value && !selectedMerchantId.value) return '请输入需要查看的商家 ID。'
  if (routeMerchantId.value && !merchantIds.value.includes(routeMerchantId.value)) {
    return '当前账号未获得该商家的资源授权。'
  }
  return '当前账号没有任何商家资源授权，请联系管理员配置 MERCHANT 范围。'
})

function switchMerchant(event: Event): void {
  const merchantId = (event.target as HTMLSelectElement).value
  if (merchantId) void router.push({ name: 'merchant-home', params: { merchantId } })
}

function openAdminMerchant(): void {
  const merchantId = adminMerchantInput.value.trim()
  if (merchantId) void router.push({ name: 'merchant-home', params: { merchantId } })
}

function compactMerchantId(merchantId: string): string {
  return merchantId.length > 8 ? `…${merchantId.slice(-4)}` : merchantId
}

function merchantLabel(merchantId: string): string {
  const name = merchantNames.value[merchantId]?.trim()
  return name
    ? `${name}（${compactMerchantId(merchantId)}）`
    : `商家 ${compactMerchantId(merchantId)}`
}

async function loadMerchantNames(ids: string[]): Promise<void> {
  const entries = await Promise.all(ids.map(async (merchantId) => {
    try {
      const merchant = await merchantDirectoryApi.getMerchant(merchantId)
      return [merchantId, merchant.name] as const
    } catch {
      return [merchantId, ''] as const
    }
  }))
  merchantNames.value = Object.fromEntries(entries)
}

watch(routeMerchantId, (value) => {
  adminMerchantInput.value = value
}, { immediate: true })

watch(merchantIds, (ids) => {
  void loadMerchantNames(ids)
}, { immediate: true })
</script>

<template>
  <main class="merchant-page">
    <ProductTopBar active="merchant" />

    <section class="merchant-hero">
      <div>
        <span class="eyebrow">MERCHANT REPUTATION</span>
        <h1>读懂每一条<br>顾客反馈</h1>
        <p>从情感走势、点评特征和差评原因定位经营变化，并下钻核对参与统计的原点评。</p>
      </div>

      <aside
        v-if="merchantIds.length > 1 && !isPlatformAdmin"
        class="merchant-switcher"
      >
        <label for="merchant-scope">当前商家</label>
        <select
          id="merchant-scope"
          :value="selectedMerchantId"
          @change="switchMerchant"
        >
          <option
            v-for="merchantId in merchantIds"
            :key="merchantId"
            :value="merchantId"
          >
            {{ merchantLabel(merchantId) }}
          </option>
        </select>
        <small>显示商家名称与 ID 尾号，仅列出当前账号已授权的资源范围</small>
      </aside>

      <form
        v-else-if="isPlatformAdmin"
        class="merchant-switcher"
        @submit.prevent="openAdminMerchant"
      >
        <label for="admin-merchant-id">商家 ID</label>
        <div>
          <input
            id="admin-merchant-id"
            v-model="adminMerchantInput"
            placeholder="输入商家 ID"
          ><button type="submit">
            查看
          </button>
        </div>
        <small>平台管理员可按商家 ID 查看分析数据</small>
      </form>

      <aside
        v-else-if="selectedMerchantId"
        class="merchant-switcher"
      >
        <span>当前商家</span>
        <strong :title="selectedMerchantId">{{ merchantLabel(selectedMerchantId) }}</strong>
        <small>来自账号 MERCHANT 资源授权</small>
      </aside>
    </section>

    <MerchantAnalyticsDashboard
      v-if="selectedMerchantId"
      :key="selectedMerchantId"
      :merchant-id="selectedMerchantId"
    />

    <MerchantReviewsPanel
      v-if="selectedMerchantId"
      :key="`${selectedMerchantId}-reviews`"
      :merchant-id="selectedMerchantId"
    />

    <MerchantInsightWorkbench
      v-if="selectedMerchantId"
      :key="`${selectedMerchantId}-insights`"
      :merchant-id="selectedMerchantId"
    />

    <section
      v-else
      class="access-state"
      role="alert"
    >
      <strong>暂无可查看的商家</strong>
      <p>{{ accessMessage }}</p>
    </section>
  </main>
</template>

<style scoped>
.merchant-page { width: min(1160px, calc(100% - 48px)); margin: 0 auto; padding: 28px 0 80px; }
.merchant-header { display: flex; justify-content: space-between; gap: 24px; align-items: center; border-bottom: 1px solid var(--line); padding-bottom: 22px; }
.merchant-brand { color: var(--brand); font-size: .74rem; font-weight: 900; letter-spacing: .14em; text-decoration: none; }
.merchant-header > div { display: flex; gap: 14px; align-items: center; color: #695b51; font-size: .78rem; }
.merchant-header button { border: 0; padding: 6px; background: transparent; color: #9d3423; cursor: pointer; font-weight: 800; }
.merchant-hero { display: grid; grid-template-columns: 1fr minmax(260px, 340px); gap: 48px; align-items: end; padding: 58px 0 36px; }
.merchant-hero h1 { margin: 14px 0 16px; font-size: clamp(3rem, 7vw, 5.6rem); }
.merchant-hero p { max-width: 680px; margin: 0; color: var(--muted); line-height: 1.75; }
.merchant-switcher { display: grid; gap: 8px; border: 1px solid var(--line); border-radius: 15px; padding: 17px; background: var(--surface); box-shadow: 0 12px 32px rgb(73 53 40 / 6%); }
.merchant-switcher label, .merchant-switcher > span { color: #695b51; font-size: .72rem; font-weight: 800; }
.merchant-switcher select, .merchant-switcher input { width: 100%; min-height: 40px; border: 1px solid #d9ccc1; border-radius: 9px; padding: 8px 10px; background: #fffdfa; color: #392d26; }
.merchant-switcher > div { display: grid; grid-template-columns: 1fr auto; gap: 7px; }
.merchant-switcher button { border: 1px solid var(--brand); border-radius: 9px; padding: 7px 12px; background: var(--brand); color: white; cursor: pointer; font-weight: 800; box-shadow: 0 6px 14px rgb(176 60 39 / 16%); transition: transform .2s var(--ease-out), background .2s ease; }
.merchant-switcher button:hover { background: var(--brand-strong); transform: translateY(-1px); }
.merchant-switcher strong { overflow: hidden; color: #392d26; font-size: 1rem; text-overflow: ellipsis; }
.merchant-switcher small { color: #88776c; font-size: .66rem; line-height: 1.5; }
.access-state { border: 1px dashed #dfb7af; border-radius: 16px; padding: 46px 24px; background: #fff6f3; color: #8e3328; text-align: center; }
.access-state strong { font-size: 1.08rem; }
.access-state p { margin: 8px 0 0; }
@media (max-width: 760px) {
  .merchant-page { width: min(100% - 28px, 620px); }
  .merchant-hero { grid-template-columns: 1fr; gap: 28px; padding-top: 44px; }
}
@media (max-width: 480px) {
  .merchant-header > div > span { display: none; }
  .merchant-hero h1 { font-size: clamp(2.8rem, 16vw, 4.3rem); }
}
</style>
