<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'

import { useAuthStore } from '@/stores/auth'

const MERCHANT_UID_KEY = 'local-life-copilot.merchant-uid'

const authStore = useAuthStore()
const router = useRouter()
const formRef = ref<FormInstance>()
const submitting = ref(false)
const errorMessage = ref('')
const form = reactive({ uid: '' })

const merchantScopes = computed(() =>
  (authStore.currentUser?.resource_scopes ?? [])
    .filter((scope) => scope.resource_type === 'MERCHANT')
    .map((scope) => scope.resource_id.trim())
    .filter(Boolean),
)

const rules: FormRules = {
  uid: [
    { required: true, message: '请输入商铺 UID', trigger: 'blur' },
  ],
}

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
</style>
