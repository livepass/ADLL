<template>
  <section class="stack">
    <div class="panel">
      <h2>仓库关联</h2>
      <form class="row" @submit.prevent="link">
        <input
          v-model="repoPath"
          class="grow"
          type="text"
          placeholder="本地 Git 仓库绝对路径（须在服务端授权根目录内）"
          :disabled="busy"
        />
        <button type="submit" :disabled="busy || !repoPath.trim()">
          {{ busy ? '关联中…' : '关联仓库' }}
        </button>
      </form>
      <p v-if="error" class="error" role="alert">{{ error }}</p>

      <div v-if="repository" class="repo-meta">
        <dl>
          <dt>路径</dt>
          <dd class="mono">{{ repository.path }}</dd>
          <dt>repo_identity</dt>
          <dd class="mono">{{ repository.repo_identity }}</dd>
          <dt>object_format</dt>
          <dd>{{ repository.object_format }}</dd>
          <dt>分支</dt>
          <dd>{{ repository.branch || '（detached / 未知）' }}</dd>
        </dl>

        <template v-if="baseline">
          <p class="muted">分析基准（完整 Commit SHA，不做截断）</p>
          <p class="hash">{{ baseline.commit_sha }}</p>
          <p class="muted">
            workspace_decision={{ baseline.workspace_decision }} ·
            available={{ baseline.available ? '是' : '否' }}
          </p>
          <p v-if="baseline.snapshot_digest" class="muted">
            snapshot_digest <span class="hash">{{ baseline.snapshot_digest }}</span>
          </p>
          <p v-if="!baseline.available" class="error">
            基准不可用：{{ baseline.unavailable_reason || '未知原因' }}（生成/审批将被阻止，HTTP 423）
          </p>
        </template>
        <p v-else class="warning">尚未建立分析基准：工作区需先处理（FR-003）。</p>

        <div v-if="workspace" class="workspace">
          <p>
            工作区状态：
            <strong>{{ workspace.clean ? '干净' : '不干净' }}</strong>
            （staged={{ workspace.staged }} modified={{ workspace.modified }}
            untracked={{ workspace.untracked }}）
          </p>
          <ul v-if="!workspace.clean" class="entries">
            <li v-for="line in workspace.entries.slice(0, 20)" :key="line" class="mono">{{ line }}</li>
          </ul>
          <div v-if="workspace && !workspace.clean && !baseline" class="row">
            <button type="button" :disabled="busy" @click="decide('clean')">
              按当前已提交内容建立基准
            </button>
            <button type="button" :disabled="busy" @click="decide('accept_uncommitted')">
              接受未提交内容作为基准
            </button>
          </div>
          <p class="muted">决定只记录基准，不修改工作区文件（FR-006）。</p>
        </div>
      </div>
    </div>

    <div class="panel">
      <h2>任务</h2>
      <form v-if="repository && baseline" class="row" @submit.prevent="create">
        <input v-model="title" class="grow" type="text" placeholder="任务标题" :disabled="busy" />
        <input v-model="description" class="grow" type="text" placeholder="描述（可选）" :disabled="busy" />
        <button type="submit" :disabled="busy || !title.trim()">创建任务</button>
      </form>
      <p v-else class="muted">关联仓库并建立可用基准后可创建任务。</p>
      <p v-if="taskError" class="error" role="alert">{{ taskError }}</p>

      <ul class="task-list">
        <li v-for="task in tasks" :key="task.id">
          <router-link :to="{ name: 'task', params: { id: task.id } }">
            #{{ task.id }} {{ task.title }}
          </router-link>
          <span class="muted">
            状态={{ task.status }} · 需求版本=
            {{ task.current_requirement_version ? `v${task.current_requirement_version.seq}` : '未提交' }}
          </span>
        </li>
        <li v-if="tasks.length === 0" class="muted">暂无任务。</li>
      </ul>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, type Baseline, type Repository, type Task, type WorkspaceStatus } from '../api'
import { describeError } from '../api/errors'

const router = useRouter()
const repoPath = ref('')
const title = ref('')
const description = ref('')
const busy = ref(false)
const error = ref('')
const taskError = ref('')
const repository = ref<Repository | null>(null)
const baseline = ref<Baseline | null>(null)
const workspace = ref<WorkspaceStatus | null>(null)
const tasks = ref<Task[]>([])

onMounted(load)

async function load(): Promise<void> {
  try {
    const [active, listed] = await Promise.all([api.activeRepository(), api.listTasks()])
    repository.value = active.repository
    baseline.value = active.baseline
    tasks.value = listed.tasks
  } catch (err) {
    error.value = describeError(err)
  }
}

async function link(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    const result = await api.linkRepository(repoPath.value.trim())
    repository.value = result.repository
    baseline.value = result.baseline
    workspace.value = result.workspace_status
  } catch (err) {
    error.value = describeError(err)
  } finally {
    busy.value = false
  }
}

async function decide(decision: 'clean' | 'accept_uncommitted'): Promise<void> {
  if (!repository.value) return
  busy.value = true
  error.value = ''
  try {
    const result = await api.workspaceDecision(repository.value.id, decision)
    baseline.value = result.baseline
  } catch (err) {
    error.value = describeError(err)
  } finally {
    busy.value = false
  }
}

async function create(): Promise<void> {
  if (!repository.value || !baseline.value) return
  busy.value = true
  taskError.value = ''
  try {
    const result = await api.createTask({
      repository_id: repository.value.id,
      baseline_id: baseline.value.id,
      title: title.value.trim(),
      description: description.value.trim() || undefined,
    })
    await router.push({ name: 'task', params: { id: result.task.id } })
  } catch (err) {
    taskError.value = describeError(err)
  } finally {
    busy.value = false
  }
}
</script>