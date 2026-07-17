<script setup lang="ts">
import { useRouter } from 'vue-router'

import { loginRouteFor } from '@/router/auth-routing'

const router = useRouter()

const scenes = [
  {
    key: 'date',
    eyebrow: '约会',
    title: '氛围在线，也不超预算',
    description: '适合慢慢聊天的环境、双人预算与近期口碑。',
    tags: ['安静', '双人', '氛围感'],
  },
  {
    key: 'gathering',
    eyebrow: '聚餐',
    title: '多人都能吃得满意',
    description: '兼顾距离、口味差异、包间需求与人均价格。',
    tags: ['多人', '包间', '交通方便'],
  },
  {
    key: 'study',
    eyebrow: '学习办公',
    title: '坐得住，也连得稳',
    description: '关注噪声、插座、停留友好度与营业时间。',
    tags: ['插座', '安静', '可久坐'],
  },
]

function requireLogin(redirect = '/app'): void {
  void router.push(loginRouteFor(redirect))
}
</script>

<template>
  <div class="guest-shell">
    <header class="guest-header">
      <a
        class="brand-mark"
        href="/"
        aria-label="LocalLife Copilot 首页"
      >
        LOCAL LIFE · AI COPILOT
      </a>
      <nav aria-label="游客导航">
        <a href="#scenes">场景灵感</a>
        <button
          class="nav-action"
          type="button"
          @click="requireLogin('/app')"
        >
          我的会话
        </button>
        <el-button
          type="primary"
          @click="requireLogin('/app')"
        >
          登录
        </el-button>
      </nav>
    </header>

    <main class="guest-main">
      <section class="guest-hero">
        <div>
          <span class="eyebrow">GUEST MODE · 只读浏览</span>
          <h1>先看看，<br>再决定去哪家。</h1>
          <p class="intro">
            游客可以浏览公开的场景灵感。登录后，才能按距离、预算与口味发起探店、保存会话和提交反馈。
          </p>
          <div class="hero-actions">
            <el-button
              type="primary"
              @click="requireLogin('/app')"
            >
              登录后开始探店
            </el-button>
            <a href="#scenes">先浏览场景</a>
          </div>
        </div>
        <aside class="guest-boundary-card">
          <span>游客权限</span>
          <strong>公开内容只读</strong>
          <ul>
            <li>可浏览场景说明与使用边界</li>
            <li>探店、会话和反馈需要登录</li>
            <li>商家与管理能力按角色授权</li>
          </ul>
        </aside>
      </section>

      <section
        id="scenes"
        class="scene-section"
      >
        <div class="section-heading">
          <div>
            <span class="eyebrow">SCENE GUIDE</span>
            <h2>从今天的场景出发</h2>
          </div>
          <p>以下内容可直接浏览；进入个性化推荐时会要求登录。</p>
        </div>
        <div class="scene-grid">
          <article
            v-for="scene in scenes"
            :key="scene.key"
            class="scene-card"
          >
            <span>{{ scene.eyebrow }}</span>
            <h3>{{ scene.title }}</h3>
            <p>{{ scene.description }}</p>
            <div class="scene-tags">
              <small
                v-for="tag in scene.tags"
                :key="tag"
              >{{ tag }}</small>
            </div>
            <button
              type="button"
              @click="requireLogin(`/app?scene=${scene.key}`)"
            >
              登录后按此场景探店 →
            </button>
          </article>
        </div>
      </section>
    </main>

    <footer class="guest-footer">
      <span>AI 推荐仅供决策参考，请以商家最新公示信息为准。</span>
      <a
        href="/health/ready"
        target="_blank"
        rel="noopener noreferrer"
      >服务状态</a>
    </footer>
  </div>
</template>
