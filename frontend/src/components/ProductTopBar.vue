<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const props = withDefaults(defineProps<{
  active?: 'discover' | 'merchant' | 'admin'
}>(), {
  active: undefined,
})

const authStore = useAuthStore()
const route = useRoute()
const router = useRouter()

function login(): void {
  void router.push({ name: 'login', query: { redirect: route.fullPath } })
}

async function logout(): Promise<void> {
  await authStore.logout()
  await router.replace({ name: 'root' })
}
</script>

<template>
  <header class="product-topbar">
    <router-link
      class="product-topbar__brand"
      to="/"
      aria-label="Local Life 首页"
    >
      <span class="product-topbar__seal">L</span>
      <span>LOCAL LIFE<small>AI 智能探店</small></span>
    </router-link>

    <nav aria-label="主导航">
      <router-link
        to="/app"
        :class="{ 'is-active': props.active === 'discover' }"
      >
        探店
      </router-link>
      <router-link
        to="/merchant"
        :class="{ 'is-active': props.active === 'merchant' }"
      >
        商家板块
      </router-link>
      <router-link
        to="/admin"
        :class="{ 'is-active': props.active === 'admin' }"
      >
        管理板块
      </router-link>
      <button
        v-if="authStore.isAuthenticated"
        class="product-topbar__user"
        type="button"
        @click="logout"
      >
        退出登录
      </button>
      <button
        v-else
        class="product-topbar__login"
        type="button"
        @click="login"
      >
        登录
      </button>
    </nav>
  </header>
</template>

<style scoped>
.product-topbar { display: flex; align-items: center; justify-content: space-between; min-height: 70px; border-bottom: 1px solid #e8e8e8; }
.product-topbar__brand { display: inline-flex; align-items: center; gap: 10px; color: #24201d; font-size: .78rem; font-weight: 900; letter-spacing: .04em; text-decoration: none; }
.product-topbar__seal { display: grid; width: 30px; height: 30px; place-items: center; border-radius: 9px; background: linear-gradient(135deg, #ff8144, #e94a2e); box-shadow: 0 5px 12px rgb(233 74 46 / 22%); color: #fff; font-family: Georgia, serif; font-size: 1.15rem; letter-spacing: 0; }
.product-topbar__brand small { display: block; margin-top: 2px; color: #9a928a; font-size: .58rem; font-weight: 650; letter-spacing: .13em; }
.product-topbar nav { display: flex; align-items: center; gap: 24px; }
.product-topbar nav a, .product-topbar button { border: 0; color: #605c58; background: transparent; font: inherit; font-size: .86rem; font-weight: 700; text-decoration: none; cursor: pointer; }
.product-topbar nav a:hover, .product-topbar nav a.is-active { color: #e75233; }
.product-topbar__login { border-radius: 12px !important; padding: 11px 18px !important; background: linear-gradient(135deg, #ff7b43, #d7462e) !important; box-shadow: 0 8px 18px rgb(215 70 46 / 18%); color: #fff !important; transition: transform .2s ease, box-shadow .2s ease; }
.product-topbar__login:hover { box-shadow: 0 11px 22px rgb(215 70 46 / 24%); transform: translateY(-1px); }
.product-topbar__user { color: #b8442f !important; }
@media (max-width: 700px) { .product-topbar nav { gap: 12px; }.product-topbar nav a { display: none; }.product-topbar nav a.is-active { display: inline; }.product-topbar__login { padding: 9px 14px !important; } }
</style>
