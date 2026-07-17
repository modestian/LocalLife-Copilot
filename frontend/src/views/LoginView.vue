<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'

import { ApiClientError } from '@/api/errors'
import { useAuthStore } from '@/stores/auth'
import type { LoginPayload } from '@/types/auth'

const authStore = useAuthStore()
const route = useRoute()
const router = useRouter()
const formRef = ref<FormInstance>()
const submitting = ref(false)
const form = reactive<LoginPayload>({ username: '', password: '' })
const rules: FormRules<LoginPayload> = {
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function submit(): Promise<void> {
  if (!(await formRef.value?.validate().catch(() => false))) return
  submitting.value = true
  try {
    await authStore.login(form)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    await router.replace(redirect)
  } catch (error) {
    ElMessage.error(error instanceof ApiClientError ? error.message : '登录失败，请稍后重试')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-intro">
      <span class="eyebrow">LOCAL LIFE · AI COPILOT</span>
      <h1>从一句需求，找到合适的店。</h1>
      <p>登录后可按距离、预算、菜系与场景探店，并继续多轮追问。</p>
    </section>

    <el-card
      class="login-card"
      shadow="never"
    >
      <template #header>
        <div>
          <h2>欢迎回来</h2>
          <p>使用你的平台账号登录</p>
        </div>
      </template>
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        @submit.prevent="submit"
      >
        <el-form-item
          label="账号"
          prop="username"
        >
          <el-input
            v-model.trim="form.username"
            autocomplete="username"
            placeholder="请输入账号"
          />
        </el-form-item>
        <el-form-item
          label="密码"
          prop="password"
        >
          <el-input
            v-model="form.password"
            autocomplete="current-password"
            placeholder="请输入密码"
            show-password
            type="password"
            @keyup.enter="submit"
          />
        </el-form-item>
        <el-button
          class="submit-button"
          type="primary"
          native-type="submit"
          :loading="submitting"
        >
          登录
        </el-button>
      </el-form>
    </el-card>
  </main>
</template>
