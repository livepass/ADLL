/** 会话与运行模式（仅内存；CSRF Token 不落任何持久化存储）。 */
import { reactive } from 'vue'
import { clearCsrfToken } from '../api/client'

export const session = reactive({
  authenticated: false,
  role: '',
})

export const runtime = reactive({
  loaded: false,
  testing: false,
  realAiEnabled: false,
})

export function markAuthenticated(role: string): void {
  session.authenticated = true
  session.role = role
}

export function clearSession(): void {
  session.authenticated = false
  session.role = ''
  clearCsrfToken()
}