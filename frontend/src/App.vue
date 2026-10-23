<template>
  <div class="app">
    <header class="topbar">
      <router-link to="/" class="brand">ADLL V1.1</router-link>
      <nav v-if="session.authenticated" class="nav">
        <router-link to="/">工作台</router-link>
        <span class="role">role={{ session.role }}</span>
        <button class="link-button" type="button" @click="logout">退出</button>
      </nav>
    </header>

    <p v-if="runtime.loaded && runtime.testing" class="banner banner-testing">
      测试/离线模式（ADLL_TESTING=1）：生成结果由 Mock 合成，<strong>不会调用外部 AI</strong>，
      也不代表真实模型能力或生产安全验证。
    </p>
    <p v-else-if="runtime.loaded && !runtime.realAiEnabled" class="banner banner-prod">
      生产模式：真实 AI 发送默认关闭（fail-closed）。仅当隔离与出站核验通过并显式启用后才会发送。
    </p>

    <p v-if="healthError" class="banner banner-error">健康检查失败：{{ healthError }}</p>

    <main class="content">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from './api'
import { setUnauthorizedHandler } from './api/client'
import { describeError } from './api/errors'
import { clearSession, runtime, session } from './state/session'

const router = useRouter()
const healthError = ref('')

onMounted(async () => {
  setUnauthorizedHandler(() => {
    clearSession()
    if (router.currentRoute.value.name !== 'login') {
      router.push({ name: 'login', query: { redirect: router.currentRoute.value.fullPath } })
    }
  })
  try {
    const health = await api.health()
    runtime.testing = health.testing
    runtime.realAiEnabled = health.real_ai_enabled
  } catch (error) {
    healthError.value = describeError(error)
  } finally {
    runtime.loaded = true
  }
})

async function logout(): Promise<void> {
  try {
    await api.logout()
  } catch {
    // 会话可能已失效；本地状态仍需清理。
  }
  clearSession()
  await router.push({ name: 'login' })
}
</script>