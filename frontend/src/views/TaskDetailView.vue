<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import StateTag from '@/components/StateTag.vue'
import { taskApi } from '@/api'
import { fmtRuntime, fmtTime, prettyJson } from '@/utils/format'

// 作为悬浮抽屉的内容：由父级传入 id，内部跳转通过 emit 交给抽屉处理
const props = defineProps({ id: { type: String, default: '' } })
const emit = defineEmits(['open-task', 'open-worker'])
const router = useRouter()

const taskId = computed(() => props.id)
const task = ref(null)
const loading = ref(false)
const notFound = ref(false)
let timer = null

const TERMINAL = ['SUCCESS', 'FAILURE', 'REVOKED', 'REJECTED', 'IGNORED']
const finished = computed(() => TERMINAL.includes(task.value?.state))

const timeline = computed(() => {
  const t = task.value
  if (!t) return []
  return [
    { label: '发送 (sent)', ts: t.sent, type: 'info' },
    { label: '接收 (received)', ts: t.received, type: 'primary' },
    { label: '开始 (started)', ts: t.started, type: 'primary' },
    { label: '成功 (succeeded)', ts: t.succeeded, type: 'success' },
    { label: '失败 (failed)', ts: t.failed, type: 'danger' },
    { label: '重试 (retried)', ts: t.retried, type: 'warning' },
    { label: '撤销 (revoked)', ts: t.revoked, type: 'warning' },
    { label: '拒绝 (rejected)', ts: t.rejected, type: 'danger' }
  ].filter((x) => x.ts)
})

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    task.value = await taskApi.info(taskId.value)
    notFound.value = false
  } catch (err) {
    if (err?.status === 404) notFound.value = true
    else if (!silent) ElMessage.error(err?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function act(label, fn, confirmText) {
  if (confirmText) {
    const ok = await ElMessageBox.confirm(confirmText, `确认${label}`, { type: 'warning' })
      .catch(() => false)
    if (!ok) return
  }
  try {
    const res = await fn()
    ElMessage.success(res?.message || `${label}成功`)
    setTimeout(() => load(true), 500)
  } catch (err) {
    ElMessage.error(err?.message || `${label}失败`)
  }
}

const revoke = () => act('撤销', () => taskApi.revoke(taskId.value, false),
  '撤销后未开始执行的任务将被丢弃，确定继续？')
const terminate = () => act('终止', () => taskApi.revoke(taskId.value, true),
  '将向执行该任务的进程发送 SIGTERM 信号，确定继续？')
const abort = () => act('中止', () => taskApi.abort(taskId.value),
  '中止需要任务实现 AbortableTask，确定继续？')

async function fetchResult() {
  try {
    const res = await taskApi.result(taskId.value, 3)
    ElMessageBox.alert(
      `<pre style="max-height:340px;overflow:auto;margin:0;font-size:12px">${
        prettyJson(res).replace(/</g, '&lt;')}</pre>`,
      '任务结果',
      { dangerouslyUseHTMLString: true }
    )
  } catch (err) {
    ElMessage.error(err?.message || '获取结果失败')
  }
}

function copy(text) {
  navigator.clipboard?.writeText(String(text))
  ElMessage.success('已复制')
}

watch(() => props.id, load)

onMounted(async () => {
  await load()
  timer = setInterval(() => { if (!finished.value) load(true) }, 3000)
})

onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="page" v-loading="loading">
    <el-result v-if="notFound" icon="warning" title="任务不存在"
      :sub-title="`未找到任务 ${taskId}，可能已超出保留上限（--max_tasks）被淘汰。`" />

    <template v-else-if="task">
      <div class="panel mb">
        <div class="detail-head">
          <div class="head-left">
            <StateTag :state="task.state" size="default" />
            <span class="task-name mono">{{ task.name }}</span>
            <el-tag size="small" effect="plain" class="mono uuid" @click="copy(task.uuid)">
              {{ task.uuid }} <el-icon><CopyDocument /></el-icon>
            </el-tag>
          </div>
          <div class="head-right">
            <el-button size="small" :icon="'Download'" @click="fetchResult">获取结果</el-button>
            <el-button size="small" :icon="'Refresh'" @click="load()">刷新</el-button>
            <el-button size="small" type="warning" plain :disabled="finished" @click="revoke">撤销</el-button>
            <el-button size="small" type="danger" plain :disabled="finished" @click="terminate">终止</el-button>
            <el-button size="small" type="danger" plain :disabled="finished" @click="abort">中止</el-button>
          </div>
        </div>
      </div>

      <el-row :gutter="14" class="mb">
        <el-col :xs="24" :lg="16">
          <div class="panel">
            <div class="panel-head"><span class="panel-title">基本信息</span></div>
            <el-descriptions :column="2" border size="small" class="desc">
              <el-descriptions-item label="任务 ID">
                <span class="mono">{{ task.uuid }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="状态"><StateTag :state="task.state" /></el-descriptions-item>
              <el-descriptions-item label="Worker">
                <span v-if="task.worker" class="link mono"
                  @click="emit('open-worker', task.worker)">{{ task.worker }}</span>
                <span v-else class="text-muted">-</span>
              </el-descriptions-item>
              <el-descriptions-item label="运行耗时">{{ fmtRuntime(task.runtime) }}</el-descriptions-item>
              <el-descriptions-item label="重试次数">{{ task.retries ?? 0 }}</el-descriptions-item>
              <el-descriptions-item label="Exchange">
                <span class="mono">{{ task.exchange || '-' }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="Routing Key">
                <span class="mono">{{ task.routing_key || '-' }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="逻辑时钟">{{ task.clock ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="ETA">{{ task.eta || '-' }}</el-descriptions-item>
              <el-descriptions-item label="过期时间">{{ task.expires || '-' }}</el-descriptions-item>
              <el-descriptions-item label="接收时间">{{ fmtTime(task.received) }}</el-descriptions-item>
              <el-descriptions-item label="开始时间">{{ fmtTime(task.started) }}</el-descriptions-item>
            </el-descriptions>
          </div>
        </el-col>

        <el-col :xs="24" :lg="8">
          <div class="panel" style="height: 100%">
            <div class="panel-head"><span class="panel-title">执行时间线</span></div>
            <div class="tl-wrap">
              <el-timeline>
                <el-timeline-item v-for="item in timeline" :key="item.label" :type="item.type"
                  :timestamp="fmtTime(item.ts)" size="normal">
                  {{ item.label }}
                </el-timeline-item>
              </el-timeline>
              <div v-if="!timeline.length" class="text-muted" style="padding: 12px; font-size: 13px">
                暂无时间线数据
              </div>
            </div>
          </div>
        </el-col>
      </el-row>

      <el-row :gutter="14" class="mb">
        <el-col :xs="24" :lg="12">
          <div class="panel">
            <div class="panel-head">
              <span class="panel-title">位置参数 args</span>
              <el-button text size="small" :icon="'CopyDocument'" @click="copy(task.args)" />
            </div>
            <pre class="code">{{ prettyJson(task.args) }}</pre>
          </div>
        </el-col>
        <el-col :xs="24" :lg="12">
          <div class="panel">
            <div class="panel-head">
              <span class="panel-title">关键字参数 kwargs</span>
              <el-button text size="small" :icon="'CopyDocument'" @click="copy(task.kwargs)" />
            </div>
            <pre class="code">{{ prettyJson(task.kwargs) }}</pre>
          </div>
        </el-col>
      </el-row>

      <div v-if="task.result" class="panel mb">
        <div class="panel-head">
          <span class="panel-title">返回结果</span>
          <el-button text size="small" :icon="'CopyDocument'" @click="copy(task.result)" />
        </div>
        <pre class="code">{{ prettyJson(task.result) }}</pre>
      </div>

      <div v-if="task.exception" class="panel mb">
        <div class="panel-head">
          <span class="panel-title" style="color: var(--el-color-danger)">异常信息</span>
        </div>
        <pre class="code err">{{ task.exception }}</pre>
      </div>

      <div v-if="task.traceback" class="panel mb">
        <div class="panel-head">
          <span class="panel-title" style="color: var(--el-color-danger)">Traceback</span>
          <el-button text size="small" :icon="'CopyDocument'" @click="copy(task.traceback)" />
        </div>
        <pre class="code err">{{ task.traceback }}</pre>
      </div>

      <div v-if="task.parent_id || task.root_id || task.children_tasks?.length" class="panel">
        <div class="panel-head"><span class="panel-title">调用链</span></div>
        <div class="chain">
          <div class="chain-row">
            <span class="chain-label">根任务</span>
            <span v-if="task.root_id" class="link mono" @click="emit('open-task', task.root_id)">
              {{ task.root_id }}
            </span>
            <span v-else class="text-muted">当前任务即为根任务</span>
          </div>
          <div class="chain-row">
            <span class="chain-label">父任务</span>
            <span v-if="task.parent_id" class="link mono" @click="emit('open-task', task.parent_id)">
              {{ task.parent_id }}
            </span>
            <span v-else class="text-muted">无</span>
          </div>
          <div class="chain-row">
            <span class="chain-label">子任务</span>
            <template v-if="task.children_tasks?.length">
              <el-table :data="task.children_tasks" size="small" style="width: 100%">
                <el-table-column label="任务 ID" width="130">
                  <template #default="{ row }">
                  <span class="link mono" @click="emit('open-task', row.uuid)">
                    {{ row.uuid.slice(0, 8) }}…
                  </span>
                  </template>
                </el-table-column>
                <el-table-column prop="name" label="任务名" show-overflow-tooltip />
                <el-table-column label="状态" width="100" align="center">
                  <template #default="{ row }"><StateTag :state="row.state" /></template>
                </el-table-column>
                <el-table-column label="耗时" width="96" align="right">
                  <template #default="{ row }">{{ fmtRuntime(row.runtime) }}</template>
                </el-table-column>
              </el-table>
            </template>
            <span v-else class="text-muted">无</span>
          </div>
          <div v-if="task.root_id" class="chain-row">
            <span class="chain-label" />
            <el-button size="small" text type="primary"
              @click="router.push({ name: 'tasks', query: { root_id: task.root_id } })">
              查看整条调用链的全部任务 →
            </el-button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  gap: 16px;
  flex-wrap: wrap;
}

.head-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex-wrap: wrap;
}

.head-right {
  display: flex;
  gap: 6px;
}

.task-name {
  font-size: 15px;
  font-weight: 640;
}

.uuid {
  cursor: pointer;
  font-size: 11.5px;
}

.desc {
  padding: 0 16px 16px;
}

.tl-wrap {
  padding: 16px 16px 0 20px;
  max-height: 330px;
  overflow: auto;
}

.tl-wrap :deep(.el-timeline-item__timestamp) {
  font-size: 11.5px;
}

.code {
  margin: 0;
  padding: 12px 16px 16px;
  font-family: var(--fu-mono);
  font-size: 12.5px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 320px;
  overflow: auto;
  color: #3a3f47;
}

.code.err {
  color: #b34040;
  background: #fef7f7;
}

.chain {
  padding: 12px 16px 16px;
}

.chain-row {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 12px;
}

.chain-label {
  width: 66px;
  flex-shrink: 0;
  font-size: 12.5px;
  color: var(--fu-text-muted);
  padding-top: 3px;
}
</style>
