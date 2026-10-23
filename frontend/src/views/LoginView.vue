<template>
  <section class="panel login-panel">
    <h1>登录 ADLL</h1>
    <p class="muted">
      口令由服务端环境变量注入；登录成功后会话 Cookie 为 HttpOnly，CSRF Token 仅保存在内存。
    </p>
    <form @submit.prevent="submit">
      <label for="password">口令</label>
      <input
        id="password"
        v-model="password"
        type="password"
        autocomplete="current-password"
        required
        :disabled="busy"
      />
      <button type="submit" :disabled="busy || !password">
        {{ busy ? '登录中…' : '登录' }}
      </button>
    </form>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { setCsrfToken } from '../api/client'
import { describeError } from '../api/errors'
import { markAuthenticated } from '../state/session'

const router = useRouter()
const route = useRoute()
const password = ref('')
const busy = ref(false)
const error = ref('')

async function submit(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    const result = await api.login(password.value)
    setCsrfToken(result.csrf_token)
    markAuthenticated(result.role)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    await router.push(redirect)
  } catch (err) {
    error.value = describeError(err)
  } finally {
    busy.value = false
  }
}
</script>