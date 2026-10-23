import { createRouter, createWebHistory } from 'vue-router'
import { api } from '../api'
import { setCsrfToken } from '../api/client'
import { clearSession, markAuthenticated, session } from '../state/session'

declare module 'vue-router' {
  interface RouteMeta {
    public?: boolean
  }
}

const routes = [
  { path: '/', name: 'dashboard', component: () => import('../views/DashboardView.vue') },
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/LoginView.vue'),
    meta: { public: true },
  },
  { path: '/tasks/:id', name: 'task', component: () => import('../views/TaskView.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  if (to.meta.public) return true
  if (session.authenticated) return true
  try {
    // 刷新后仅剩 HttpOnly 会话 Cookie：由服务端同源会话重新下发 CSRF 同步器令牌。
    const me = await api.me()
    setCsrfToken(me.csrf_token)
    markAuthenticated(me.role)
    return true
  } catch {
    clearSession()
    return { name: 'login', query: { redirect: to.fullPath } }
  }
})

export default router