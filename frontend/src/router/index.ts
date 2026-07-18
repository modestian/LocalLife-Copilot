import { createRouter, createWebHistory } from 'vue-router'

import { tokenStorage } from '@/api/token-storage'
import { useAuthStore } from '@/stores/auth'

import { canAccessRoles, loginRouteFor, resolveWorkbenchRouteName } from './auth-routing'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { guestOnly: true, title: '登录' },
    },
    {
      path: '/',
      name: 'root',
      component: () => import('@/views/GuestHomeView.vue'),
      meta: {
        publicReadOnly: true,
        redirectAuthenticated: true,
        title: '发现好店',
      },
    },
    {
      path: '/app',
      name: 'user-home',
      component: () => import('@/views/HomeView.vue'),
      meta: { publicReadOnly: true, roles: ['USER'], title: '用户工作台' },
    },
    {
      path: '/merchant/:merchantId?',
      name: 'merchant-home',
      component: () => import('@/views/merchant/MerchantAnalyticsView.vue'),
      meta: {
        requiresAuth: true,
        roles: ['MERCHANT_ADMIN', 'MERCHANT_OPERATOR'],
        title: '商家口碑工作台',
      },
    },
    {
      path: '/admin',
      name: 'admin-home',
      component: () => import('@/views/RoleWorkspaceView.vue'),
      props: {
        title: '管理工作台',
        description: '查看知识库、平台与模型管理能力；游客访问时保持只读。',
        entries: [
          {
            to: '/admin/knowledge-bases',
            label: '进入知识库管理',
            description: '查看知识库状态、文档与 Chunk 统计及配置权限。',
          },
          {
            to: '/admin/models',
            label: '进入模型管理',
            description: '管理数据集、LoRA 训练、模型卡、审批和发布操作。',
          },
        ],
      },
      meta: {
        publicReadOnly: true,
        roles: ['PLATFORM_ADMIN', 'KB_ADMIN', 'OPS_ADMIN', 'MODEL_ADMIN'],
        title: '管理工作台',
      },
    },
    {
      path: '/admin/knowledge-bases',
      name: 'knowledge-bases',
      component: () => import('@/views/admin/KnowledgeBaseListView.vue'),
      meta: {
        publicReadOnly: true,
        roles: ['PLATFORM_ADMIN', 'KB_ADMIN'],
        title: '知识库管理',
      },
    },
    {
      path: '/admin/knowledge-bases/:id',
      name: 'knowledge-base-detail',
      component: () => import('@/views/admin/KnowledgeBaseDetailView.vue'),
      meta: {
        publicReadOnly: true,
        roles: ['PLATFORM_ADMIN', 'KB_ADMIN'],
        title: '知识库详情',
      },
    },
    {
      path: '/admin/models',
      name: 'model-management',
      component: () => import('@/views/admin/ModelManagementView.vue'),
      meta: {
        requiresAuth: true,
        roles: ['PLATFORM_ADMIN', 'MODEL_ADMIN'],
        title: '模型管理',
      },
    },
    {
      path: '/service-unavailable',
      name: 'service-unavailable',
      component: () => import('@/views/ServiceUnavailableView.vue'),
      meta: { title: '服务暂不可用' },
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(async (to) => {
  const authStore = useAuthStore()
  const hasSession = tokenStorage.get() !== null

  if (to.meta.guestOnly && !hasSession) return true
  if (to.meta.publicReadOnly && !hasSession) return true
  if (to.meta.requiresAuth && !hasSession) {
    return loginRouteFor(to.fullPath)
  }

  if (
    hasSession &&
    (to.meta.requiresAuth ||
      to.meta.publicReadOnly ||
      to.meta.guestOnly ||
      to.meta.redirectAuthenticated)
  ) {
    try {
      await authStore.initialize()
    } catch {
      if (to.meta.publicReadOnly || to.meta.redirectAuthenticated) return true
      if (!tokenStorage.get()) {
        return to.meta.guestOnly ? true : loginRouteFor(to.fullPath)
      }
      return { name: 'service-unavailable', query: { redirect: to.fullPath } }
    }
  }

  const user = authStore.currentUser
  if (to.meta.redirectAuthenticated && user) return { name: resolveWorkbenchRouteName(user) }
  if (to.meta.guestOnly && user) return { name: resolveWorkbenchRouteName(user) }
  if (!to.meta.requiresAuth && !to.meta.publicReadOnly) return true
  if (to.meta.publicReadOnly && !user) return true
  if (!user) return loginRouteFor(to.fullPath)
  if (!canAccessRoles(user, to.meta.roles)) return { name: resolveWorkbenchRouteName(user) }
  return true
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${String(to.meta.title)} · LocalLife Copilot` : 'LocalLife Copilot'
})

export default router
