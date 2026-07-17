import { createApp } from 'vue'
import { ElButton, ElCard, ElConfigProvider, ElForm, ElFormItem, ElInput } from 'element-plus'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import { setAuthExpiredHandler } from './api/client'
import { useAuthStore } from './stores/auth'
import 'element-plus/es/components/base/style/css'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/card/style/css'
import 'element-plus/es/components/config-provider/style/css'
import 'element-plus/es/components/form/style/css'
import 'element-plus/es/components/form-item/style/css'
import 'element-plus/es/components/input/style/css'
import 'element-plus/es/components/message/style/css'
import './style.css'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)
app.use(ElButton)
app.use(ElCard)
app.use(ElConfigProvider)
app.use(ElForm)
app.use(ElFormItem)
app.use(ElInput)

const authStore = useAuthStore(pinia)
setAuthExpiredHandler(() => {
  authStore.clearSession()
  const currentRoute = router.currentRoute.value
  if (currentRoute.meta.requiresAuth) {
    void router.replace({ name: 'login', query: { redirect: currentRoute.fullPath } })
  }
})

app.mount('#app')
