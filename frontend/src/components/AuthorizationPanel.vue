<template>
  <div class="panel">
    <h3>出站授权</h3>
    <p class="muted">
      发送前需同时满足：同任务、同分析基准、同接收方、同实际发送范围、授权当前有效（五项缺一不可）。
      撤销后发送量为 0。
    </p>

    <form class="stack-tight" @submit.prevent="create">
      <label>
        接收方
        <input v-model="receiver" type="text" :disabled="busy" />
      </label>
      <fieldset class="types">
        <legend>数据类型</legend>
        <label v-for="type in typeOptions" :key="type" class="inline">
          <input v-model="dataTypes" type="checkbox" :value="type" :disabled="busy" />
          {{ type }}
        </label>
      </fieldset>
      <label>
        发送范围（路径，每行一个；留空表示按默认范围）
        <textarea v-model="pathsText" rows="3" :disabled="busy" placeholder="src/app.py"></textarea>
      </label>

      <details>
        <summary>确认前预览：拟发送内容与默认排除</summary>
        <p class="muted">需求文本（当前正式版本）：</p>
        <pre class="preview">{{ requirementContent || '（尚未提交需求版本）' }}</pre>
        <p class="muted">
          默认排除由服务端在生成时执行：敏感文件（如 .env、密钥文件）、未授权路径、LFS 指针、
          symlink、submodule/gitlink，以及可验证的 export-ignore；具体命中项在生成响应
          `snapshot.excluded` 中如实列出。无法核验属性时按 fail-closed 处理。
        </p>
      </details>

      <button type="submit" :disabled="busy || !receiver.trim()">创建授权</button>
    </form>
    <p v-if="error" class="error" role="alert">{{ error }}</p>

    <ul class="auth-list">
      <li v-for="auth in authorizations" :key="auth.id">
        <div>
          <strong>#{{ auth.id }}</strong>
          <span :class="['chip', auth.status === 'approved' ? 'ok' : 'muted-chip']">
            {{ auth.status }}
          </span>
          <span class="muted">receiver={{ auth.receiver }}</span>
        </div>
        <div class="muted">
          data_types={{ auth.data_types.join(', ') }} · paths={{ auth.send_scope.paths?.join(', ') || '默认' }}
        </div>
        <div v-if="auth.revoked_at" class="muted">撤销于 {{ auth.revoked_at }}</div>
        <button
          v-if="auth.status === 'approved'"
          type="button"
          class="danger"
          :disabled="busy"
          @click="revoke(auth.id)"
        >
          撤销
        </button>
      </li>
      <li v-if="authorizations.length === 0" class="muted">暂无授权。</li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { api, type Authorization } from '../api'
import { describeError } from '../api/errors'

const props = defineProps<{
  taskId: number
  authorizations: Authorization[]
  requirementContent: string
}>()
const emit = defineEmits<{ changed: [] }>()

const receiver = ref('dashscope')
const typeOptions = ['requirement', 'feedback', 'source']
const dataTypes = ref<string[]>([...typeOptions])
const pathsText = ref('')
const busy = ref(false)
const error = ref('')

async function create(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    const paths = pathsText.value
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
    await api.createAuthorization(props.taskId, {
      receiver: receiver.value.trim(),
      data_types: [...dataTypes.value],
      send_scope: paths.length ? { paths } : {},
    })
    emit('changed')
  } catch (err) {
    error.value = describeError(err)
  } finally {
    busy.value = false
  }
}

async function revoke(authorizationId: number): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    await api.revokeAuthorization(authorizationId)
    emit('changed')
  } catch (err) {
    error.value = describeError(err)
  } finally {
    busy.value = false
  }
}
</script>