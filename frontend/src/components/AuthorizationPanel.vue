<template>
  <div class="panel">
    <h3>出站授权</h3>
    <p class="muted">
      发送前需同时满足：同任务、同分析基准、同接收端点、实际发送范围在白名单内、授权当前有效（五项缺一不可）。
      撤销后发送量为 0。空范围<strong>不会</strong>被解释为“全部源码”。
    </p>

    <form class="stack-tight" @submit.prevent="create">
      <label>
        接收端点（必须与适配器实际端点一致）
        <input v-model="receiver" type="text" :disabled="busy" />
      </label>
      <p class="muted" v-if="receiverHint">服务端实际端点：{{ receiverHint }}</p>
      <fieldset class="types">
        <legend>数据类型</legend>
        <label v-for="type in typeOptions" :key="type" class="inline">
          <input v-model="dataTypes" type="checkbox" :value="type" :disabled="busy" />
          {{ type }}
        </label>
      </fieldset>
      <label>
        发送范围（仓库相对路径，每行一个；必须显式列出）
        <textarea v-model="pathsText" rows="4" :disabled="busy" placeholder="src/app.py"></textarea>
      </label>

      <details>
        <summary>确认前预览：拟发送内容与默认排除</summary>
        <p class="muted">需求文本（当前正式版本）：</p>
        <pre class="preview">{{ requirementContent || '（尚未提交需求版本）' }}</pre>
        <p class="muted">
          服务端在生成时还会执行：敏感文件（.env、密钥文件）、未授权路径、LFS 指针、symlink、
          submodule/gitlink、export-ignore 的排除；无法核验属性时 fail-closed。
        </p>
      </details>

      <button type="submit" :disabled="busy || !receiver.trim() || !pathsValid">创建授权</button>
      <p v-if="!pathsValid" class="muted">至少填写一个路径，否则不会授权任何源码。</p>
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
          data_types={{ auth.data_types.join(', ') }} · paths={{ auth.send_scope.paths?.join(', ') || '（无）' }}
        </div>
        <div v-if="auth.revoked_at" class="muted">撤销于 {{ auth.revoked_at }}</div>
        <button
          v-if="auth.status === 'approved'"
          type="button"
          :disabled="busy"
          @click="preview(auth.id)"
        >
          预览待发送范围
        </button>
        <button
          v-if="auth.status === 'approved'"
          type="button"
          class="danger"
          :disabled="busy"
          @click="revoke(auth.id)"
        >
          撤销
        </button>
        <div v-if="previewFor === auth.id && previewData" class="preview-block">
          <p class="muted">
            receiver={{ previewData.receiver }} · data_types={{ previewData.data_types.join(', ') }}
          </p>
          <p class="muted">request_digest={{ previewData.request_digest }}</p>
          <p class="muted">snapshot_digest={{ previewData.snapshot.digest }}</p>
          <p class="muted">
            需求：{{ previewData.requirement.chars }} 字符 · sha256={{ previewData.requirement.sha256 }}
          </p>
          <ul>
            <li v-for="item in previewData.source" :key="item.path">
              {{ item.path }} · {{ item.bytes }} B · {{ item.sha256 }}
            </li>
          </ul>
          <p class="muted" v-if="previewData.snapshot.excluded.length">
            排除：{{ previewData.snapshot.excluded.map((e) => `${e.path}(${e.reason})`).join(', ') }}
          </p>
        </div>
      </li>
      <li v-if="authorizations.length === 0" class="muted">暂无授权。</li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, type Authorization, type PreviewResponse } from '../api'
import { describeError } from '../api/errors'

const props = defineProps<{
  taskId: number
  authorizations: Authorization[]
  requirementContent: string
}>()
const emit = defineEmits<{ changed: [] }>()

const receiver = ref('')
const receiverHint = ref('')
const typeOptions = ['requirement', 'feedback', 'source']
const dataTypes = ref<string[]>([...typeOptions])
const pathsText = ref('')
const busy = ref(false)
const error = ref('')
const previewFor = ref<number | null>(null)
const previewData = ref<PreviewResponse | null>(null)

const pathsValid = computed(() => parsePaths().length > 0)

function parsePaths(): string[] {
  return pathsText.value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
}

onMounted(async () => {
  try {
    const info = await api.outboundReceiver()
    if (!receiver.value) receiver.value = info.receiver
    receiverHint.value = info.receiver
  } catch {
    // 端点信息只用于提示；创建时仍由服务端校验。
  }
})

async function create(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    const paths = parsePaths()
    await api.createAuthorization(props.taskId, {
      receiver: receiver.value.trim(),
      data_types: [...dataTypes.value],
      send_scope: { paths },
    })
    emit('changed')
  } catch (err) {
    error.value = describeError(err)
  } finally {
    busy.value = false
  }
}

async function preview(authorizationId: number): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    previewData.value = await api.previewGeneration(props.taskId, authorizationId)
    previewFor.value = authorizationId
  } catch (err) {
    error.value = describeError(err)
    previewData.value = null
    previewFor.value = null
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

<style scoped>
.preview-block {
  border-top: 1px solid #ddd;
  margin-top: 0.5rem;
  padding-top: 0.5rem;
}
.preview-block ul {
  margin: 0.25rem 0;
  padding-left: 1.2rem;
  font-family: monospace;
  font-size: 0.85rem;
}
</style>
