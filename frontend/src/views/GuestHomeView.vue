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

const popularSearches = ['约会餐厅', '附近咖啡', '朋友聚餐', '周末遛娃']

const discoveryCards = [
  { icon: '✦', title: '约会晚餐', detail: '氛围、距离与双人预算', meta: '今晚就能去' },
  { icon: '◎', title: '朋友聚餐', detail: '包间、菜系与多人评价', meta: '按人数筛选' },
  { icon: '⌁', title: '安静咖啡', detail: '插座、久坐与环境口碑', meta: '适合工作日' },
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
        <span class="brand-mark__seal">L</span>
        <span>LOCAL LIFE<small>AI 智能探店</small></span>
      </a>
      <nav aria-label="游客导航">
        <router-link to="/app">
          探店
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
        <div class="guest-hero__copy">
          <span class="eyebrow">LOCAL DISCOVERY · AI COPILOT</span>
          <h1>今天想吃点什么？</h1>
          <p class="intro">
            不只看评分。告诉 AI 你的距离、预算和场景，找到真正适合此刻的好去处。
          </p>
          <div
            class="hero-search"
            role="search"
          >
            <span class="hero-search__icon">⌕</span>
            <button
              type="button"
              @click="openSection('/app')"
            >
              搜餐厅、咖啡、周末好去处
            </button>
            <span class="hero-search__action">AI 搜索</span>
          </div>
          <div class="popular-searches">
            <span>热门：</span>
            <button
              v-for="item in popularSearches"
              :key="item"
              type="button"
              @click="openSection(`/app?query=${encodeURIComponent(item)}`)"
            >
              {{ item }}
            </button>
          </div>
        </div>
        <aside class="discovery-panel">
          <div class="discovery-panel__header">
            <div>
              <span>AI 为你发现</span>
              <strong>今晚的灵感</strong>
            </div>
            <small>实时匹配</small>
          </div>
          <button
            v-for="(item, index) in discoveryCards"
            :key="item.title"
            class="discovery-card"
            type="button"
            @click="openSection(`/app?scene=${scenes[index]?.key ?? 'date'}`)"
          >
            <span class="discovery-card__icon">{{ item.icon }}</span>
            <span>
              <strong>{{ item.title }}</strong>
              <small>{{ item.detail }}</small>
            </span>
            <em>{{ item.meta }} →</em>
          </button>
          <p class="discovery-panel__note">
            基于位置、营业状态、口碑与偏好综合推荐
          </p>
        </aside>
      </section>

      <section
        class="service-strip"
        aria-label="产品能力"
      >
        <div>
          <span>01</span><strong>本地口碑</strong><small>结合真实点评与商家信息</small>
        </div>
        <div>
          <span>02</span><strong>场景推荐</strong><small>预算、距离、人数都能说清</small>
        </div>
        <div>
          <span>03</span><strong>有据可查</strong><small>每条建议都附来源依据</small>
        </div>
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
          <p>从真实需求开始，不必在长列表里反复筛选。</p>
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
              开始探索 <span>→</span>
            </button>
          </article>
        </div>
      </section>
    </main>

    <footer class="guest-footer">
      <span>游客可浏览公开内容；登录后可开启对话、保存偏好与提交反馈。</span>
      <a
        href="/health/ready"
        target="_blank"
        rel="noopener noreferrer"
      >服务状态</a>
    </footer>
  </div>
</template>
