<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'

import { notifyApiError } from '@/api/error-feedback'
import { resolveWorkbenchRouteName, safeRedirect } from '@/router/auth-routing'
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
    const user = await authStore.login(form)
    await router.replace(safeRedirect(route.query.redirect) ?? { name: resolveWorkbenchRouteName(user) })
  } catch (error) {
    notifyApiError(error, '登录失败，请稍后重试')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main class="auth-page app-auth-page">
    <section class="auth-intro">
      <div class="auth-brand">
        <span class="auth-brand__seal">L</span>
        <span>LOCAL LIFE<small>AI 智能探店</small></span>
      </div>
      <span class="eyebrow">LOCAL DISCOVERY · MEMBER ACCESS</span>
      <h1>让每一次出发，<br>都更值得。</h1>
      <p>用距离、预算和场景告诉 AI 你的期待，少一点翻找，多一点恰到好处。</p>
      <div class="auth-benefits">
        <span>真实口碑</span><span>场景推荐</span><span>来源可查</span>
      </div>
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
      <el-alert
        v-if="route.query.passwordChanged === '1'"
        class="password-change-notice"
        title="密码已修改，请使用新密码重新登录。"
        type="success"
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
