<script setup lang="ts">
import { useRouter } from 'vue-router'

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

function openSection(path: string): void {
  void router.push(path)
}

function login(): void {
  void router.push({ name: 'login' })
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
        <router-link to="/app">
          探店
        </router-link>
        <router-link to="/merchant">
          商家板块
        </router-link>
        <router-link to="/admin">
          管理板块
        </router-link>
        <el-button
          type="primary"
          @click="login"
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
            无需登录即可进入所有板块浏览内容；游客仅有读取权限，提交、编辑、删除等操作需要登录并通过权限校验。
          </p>
          <div class="hero-actions">
            <el-button
              type="primary"
              @click="openSection('/app')"
            >
              进入探店板块
            </el-button>
            <a href="#scenes">先浏览场景</a>
          </div>
        </div>
        <aside class="guest-boundary-card">
          <span>游客权限</span>
          <strong>公开内容只读</strong>
          <ul>
            <li>可进入探店、商家和管理板块查看</li>
            <li>不能新建、编辑、删除或提交内容</li>
            <li>登录后仍按账号角色授予操作权限</li>
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
          <p>以下内容和各业务板块均可直接浏览；执行操作时才会要求登录。</p>
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
              @click="openSection(`/app?scene=${scene.key}`)"
            >
              按此场景进入探店 →
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
