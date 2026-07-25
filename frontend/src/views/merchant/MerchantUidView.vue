<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'

import { merchantDirectoryApi, type MerchantDirectoryEntry } from '@/api/merchants'
import { useAuthStore } from '@/stores/auth'

const MERCHANT_UID_KEY = 'local-life-copilot.merchant-uid'

const authStore = useAuthStore()
const router = useRouter()
const formRef = ref<FormInstance>()
const submitting = ref(false)
const errorMessage = ref('')
const form = reactive({ uid: '' })

const allMerchants = ref<MerchantDirectoryEntry[]>([])
const loadingMerchants = ref(false)

const merchantScopes = computed(() =>
  (authStore.currentUser?.resource_scopes ?? [])
    .filter((scope) => scope.resource_type === 'MERCHANT')
    .map((scope) => scope.resource_id.trim())
    .filter(Boolean),
)

/** 当前用户有权访问的商户列表（仅供展示） */
const authorizedMerchants = computed(() => {
  const scopeSet = new Set(merchantScopes.value)
  return allMerchants.value.filter((m) => scopeSet.has(m.id))
})

const rules: FormRules = {
  uid: [
    { required: true, message: '请输入商铺 UID', trigger: 'blur' },
  ],
}

onMounted(async () => {
  loadingMerchants.value = true
  try {
    const result = await merchantDirectoryApi.listMerchants()
    allMerchants.value = result.items
  } catch {
    // 加载失败时不影响手动输入
  } finally {
    loadingMerchants.value = false
  }
})

async function submit(): Promise<void> {
  errorMessage.value = ''
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  const trimmed = form.uid.trim()
  if (!merchantScopes.value.includes(trimmed)) {
    errorMessage.value = '该 UID 不在当前账号的授权范围内，请检查后重试。'
    return
  }
  submitting.value = true
  try {
    localStorage.setItem(MERCHANT_UID_KEY, trimmed)
    await router.replace({ name: 'merchant-home', params: { merchantId: trimmed } })
  } finally {
    submitting.value = false
  }
}

async function logout(): Promise<void> {
  await authStore.logout()
  await router.replace({ name: 'root' })
}
</script>

<template>
  <main class="auth-page app-auth-page">
    <section class="auth-intro">
      <div class="auth-brand">
        <span class="auth-brand__seal">L</span>
        <span>LOCAL LIFE<small>AI 智能探店</small></span>
      </div>
      <span class="eyebrow">MERCHANT · SHOP VERIFICATION</span>
      <h1>请输入您的<br>商铺 UID</h1>
      <p>为保障数据安全，商家需要输入自己商铺的 UID 才能查看经营数据与评论。</p>
    </section>

    <el-card
      class="login-card"
      shadow="never"
    >
      <template #header>
        <div>
          <h2>商铺身份验证</h2>
          <p>输入您所属商铺的 UID 以进入商家工作台</p>
        </div>
      </template>

      <el-alert
        v-if="errorMessage"
        class="uid-error"
        :title="errorMessage"
        type="error"
        :closable="false"
        show-icon
      />

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        @submit.prevent="submit"
      >
        <el-form-item
          label="商铺 UID"
          prop="uid"
        >
          <el-input
            v-model="form.uid"
            placeholder="请输入商铺 UID"
            @keyup.enter="submit"
          />
        </el-form-item>
        <el-button
          class="submit-button"
          type="primary"
          native-type="submit"
          :loading="submitting"
        >
          进入商家工作台
        </el-button>
      </el-form>

      <!-- 商户列表（仅供查看 UID，不可点击） -->
      <div class="merchant-ref-section">
        <div class="merchant-ref-header">
          <span>我的商铺列表</span>
          <small>请找到您的商铺并复制 UID 填入上方输入框</small>
        </div>

        <div
          v-if="loadingMerchants"
          class="merchant-ref-loading"
        >
          加载中…
        </div>

        <div
          v-else-if="authorizedMerchants.length === 0"
          class="merchant-ref-empty"
        >
          当前账号没有关联的商铺，请联系管理员。
        </div>

        <ul
          v-else
          class="merchant-ref-list"
        >
          <li
            v-for="merchant in authorizedMerchants"
            :key="merchant.id"
            class="merchant-ref-item"
          >
            <span class="merchant-ref-name">{{ merchant.name }}</span>
            <span class="merchant-ref-category">{{ merchant.category }}</span>
          </li>
        </ul>
      </div>

      <div class="uid-actions">
        <el-button
          text
          type="danger"
          @click="logout"
        >
          退出登录
        </el-button>
      </div>
    </el-card>
  </main>
</template>

<style scoped>
.uid-error { margin-bottom: 16px; }
.uid-actions { margin-top: 16px; text-align: center; }

.merchant-ref-section {
  margin-top: 20px;
  padding-top: 18px;
  border-top: 1px solid #e8ddd4;
}
.merchant-ref-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 12px;
}
.merchant-ref-header span {
  color: #392d26;
  font-size: 0.88rem;
  font-weight: 700;
}
.merchant-ref-header small {
  color: #88776c;
  font-size: 0.72rem;
}
.merchant-ref-loading,
.merchant-ref-empty {
  color: #88776c;
  font-size: 0.82rem;
  text-align: center;
  padding: 12px 0;
}
.merchant-ref-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 280px;
  overflow-y: auto;
}
.merchant-ref-item {
  display: grid;
  grid-template-columns: 1fr auto auto;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: #faf6f2;
  border: 1px solid #ede5dc;
  border-radius: 8px;
  cursor: default;
  user-select: text;
}
.merchant-ref-name {
  color: #392d26;
  font-size: 0.84rem;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.merchant-ref-category {
  padding: 2px 6px;
  background: #f0e8e0;
  border-radius: 4px;
  color: #7b6d63;
  font-size: 0.68rem;
  font-weight: 600;
  white-space: nowrap;
}
.merchant-ref-uid {
  font-family: 'Courier New', Courier, monospace;
  font-size: 0.68rem;
  color: #695b51;
  word-break: break-all;
  text-align: right;
  min-width: 0;
}
</style>
