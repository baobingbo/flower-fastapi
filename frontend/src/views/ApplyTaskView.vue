<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import StateTag from '@/components/StateTag.vue'
import { taskApi } from '@/api'
import { useDetailStore } from '@/stores/detail'
import { fmtRuntime, fmtTimeShort, prettyJson } from '@/utils/format'

const router = useRouter()
const detail = useDetailStore()

const registered = ref([])
const tasksDetail = ref([])
const queues = ref([])
const submitting = ref(false)
const history = ref([])

const form = reactive({
  taskname: '',
  mode: 'async-apply',
  args: '[]',
  kwargs: '{}',
  queue: '',
  countdown: null,
  expires: null,
  priority: null,
  routing_key: '',
  timeout: 10
})

const MODES = [
  { value: 'async-apply', label: '异步下发', desc: '调用本地注册的任务，立即返回 task-id' },
  { value: 'send-task', label: '按名称发送', desc: '不要求本地注册任务源，直接投递到 broker' },
  { value: 'apply', label: '同步执行', desc: '下发后阻塞等待结果返回（受超时限制）' }
]

function parseJson(text, fallback, label) {
  const t = (text || '').trim()
  if (!t) return fallback
  try {
    return JSON.parse(t)
  } catch {
    throw new Error(`${label} 不是合法的 JSON`)
  }
}

async function submit() {
  if (!form.taskname) return ElMessage.warning('请填写任务名称')

  let payload
  try {
    payload = {
      args: parseJson(form.args, [], 'args'),
      kwargs: parseJson(form.kwargs, {}, 'kwargs')
    }
  } catch (err) {
    return ElMessage.error(err.message)
  }
  if (!Array.isArray(payload.args)) return ElMessage.error('args 必须是数组')

  for (const k of ['queue', 'routing_key']) if (form[k]) payload[k] = form[k]
  for (const k of ['countdown', 'expires', 'priority']) {
    if (form[k] !== null && form[k] !== '') payload[k] = form[k]
  }

  submitting.value = true
  try {
    let res
    if (form.mode === 'apply') {
      res = await taskApi.apply(form.taskname, payload, form.timeout)
    } else if (form.mode === 'send-task') {
      res = await taskApi.sendTask(form.taskname, payload)
    } else {
      res = await taskApi.asyncApply(form.taskname, payload)
    }
    ElMessage.success('任务已下发')
    history.value.unshift({
      ts: Date.now() / 1000,
      taskname: form.taskname,
      mode: form.mode,
      id: res['task-id'] || res.task_id,
      state: res.state || 'PENDING',
      result: res.result,
      runtime: res.runtime,
      raw: res
    })
    history.value = history.value.slice(0, 30)
  } catch (err) {
    ElMessage.error(err?.message || '下发失败')
  } finally {
    submitting.value = false
  }
}

async function refreshRow(row) {
  try {
    const res = await taskApi.info(row.id)
    row.state = res.state
    row.result = res.result
    row.runtime = res.runtime
    row.raw = res
  } catch {
    ElMessage.warning('任务尚未产生事件记录')
  }
}

function fillExample() {
  form.args = '["user@example.com"]'
  form.kwargs = '{"template": "welcome", "retry": true}'
}

onMounted(async () => {
  try {
    const res = await taskApi.registered()
    registered.value = res.tasks || []
    tasksDetail.value = res.tasks_detail || []
    queues.value = res.queues || []
    if (registered.value.length) {
      form.taskname = registered.value[0]
      syncQueue(registered.value[0])
    }
  } catch (err) {
    ElMessage.error(err?.message || '注册任务加载失败')
  }
})

// 选择任务后，自动预填其默认队列（任务↔队列联动）。
function syncQueue(name) {
  const hit = tasksDetail.value.find((t) => t.name === name)
  form.queue = hit ? hit.queue : ''
}
</script>

<template>
  <div class="page">
    <el-row :gutter="14">
      <el-col :xs="24" :lg="14">
        <div class="panel">
          <div class="panel-head"><span class="panel-title">下发任务</span></div>
          <el-form label-width="96px" size="default" class="form">
            <el-form-item label="下发方式">
              <el-radio-group v-model="form.mode">
                <el-radio-button v-for="m in MODES" :key="m.value" :value="m.value">
                  {{ m.label }}
                </el-radio-button>
              </el-radio-group>
              <div class="mode-desc text-muted">
                {{ MODES.find((m) => m.value === form.mode)?.desc }}
              </div>
            </el-form-item>

            <el-form-item label="任务名称" required>
              <el-select v-model="form.taskname" filterable allow-create default-first-option
                @change="syncQueue" placeholder="选择或输入任务名（如 app.tasks.send_email）" style="width: 100%">
                <el-option v-for="t in registered" :key="t" :label="t" :value="t" />
              </el-select>
            </el-form-item>

            <el-form-item label="args">
              <el-input v-model="form.args" type="textarea" :rows="2" class="mono"
                placeholder='位置参数，JSON 数组，例如 ["user@example.com", 42]' />
            </el-form-item>

            <el-form-item label="kwargs">
              <el-input v-model="form.kwargs" type="textarea" :rows="3" class="mono"
                placeholder='关键字参数，JSON 对象，例如 {"template": "welcome"}' />
              <el-button text size="small" type="primary" @click="fillExample">填入示例</el-button>
            </el-form-item>

            <el-divider content-position="left">
              <span class="text-muted" style="font-size: 12.5px">投递选项（可选）</span>
            </el-divider>

            <el-row :gutter="12">
              <el-col :span="12">
                <el-form-item label="队列">
                  <el-select v-model="form.queue" filterable allow-create default-first-option
                    placeholder="选择队列（默认路由）" style="width: 100%">
                    <el-option label="（默认路由）" value="" />
                    <el-option v-for="q in queues" :key="q" :label="q" :value="q" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="Routing Key">
                  <el-input v-model="form.routing_key" placeholder="默认" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="延迟(s)">
                  <el-input-number v-model="form.countdown" :min="0" controls-position="right"
                    style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="过期(s)">
                  <el-input-number v-model="form.expires" :min="0" controls-position="right"
                    style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="优先级">
                  <el-input-number v-model="form.priority" :min="0" :max="255" controls-position="right"
                    style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col v-if="form.mode === 'apply'" :span="8">
                <el-form-item label="等待超时">
                  <el-input-number v-model="form.timeout" :min="1" :max="120" controls-position="right"
                    style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>

            <el-form-item>
              <el-button type="primary" :icon="'Promotion'" :loading="submitting" @click="submit">
                下发任务
              </el-button>
              <span class="text-muted" style="font-size: 12px; margin-left: 10px">
                对应 flower API：/api/task/{{ form.mode }}/&lt;taskname&gt;
              </span>
            </el-form-item>
          </el-form>
        </div>
      </el-col>

      <el-col :xs="24" :lg="10">
        <div class="panel" style="height: 100%">
          <div class="panel-head">
            <span class="panel-title">下发记录</span>
            <el-button v-if="history.length" text size="small" @click="history = []">清空</el-button>
          </div>
          <div class="history">
            <el-empty v-if="!history.length" description="尚未下发任务" :image-size="70" />
            <div v-for="(h, i) in history" :key="i" class="hrow">
              <div class="hrow-top">
                <StateTag :state="h.state" />
                <span class="link mono hid" @click="detail.openTask(h.id)">
                  {{ (h.id || '').slice(0, 12) }}…
                </span>
                <div class="grow" />
                <span class="text-muted mono" style="font-size: 11.5px">
                  {{ fmtTimeShort(h.ts) }}
                </span>
              </div>
              <div class="hname mono">{{ h.taskname }}</div>
              <div class="hmeta">
                <el-tag size="small" effect="plain">{{ h.mode }}</el-tag>
                <span v-if="h.runtime" class="text-muted" style="font-size: 11.5px">
                  耗时 {{ fmtRuntime(h.runtime) }}
                </span>
                <div class="grow" />
                <el-button text size="small" :icon="'Refresh'" @click="refreshRow(h)">刷新</el-button>
                <el-button text size="small" type="primary" @click="detail.openTask(h.id)">
                  详情
                </el-button>
              </div>
              <pre v-if="h.result" class="hresult">{{ prettyJson(h.result) }}</pre>
            </div>
          </div>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.form {
  padding: 16px 20px 8px;
}

.mode-desc {
  font-size: 12px;
  margin-top: 4px;
  line-height: 1.4;
}

.history {
  padding: 8px 14px 14px;
  max-height: 640px;
  overflow: auto;
}

.hrow {
  border: 1px solid var(--fu-border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 10px;
  background: var(--fu-card, #fcfdfe);
}

.hrow-top {
  display: flex;
  align-items: center;
  gap: 8px;
}

.hid {
  font-size: 12px;
}

.hname {
  font-size: 12.5px;
  margin: 6px 0;
  word-break: break-all;
}

.hmeta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.hresult {
  margin: 8px 0 0;
  padding: 8px 10px;
  background: var(--fu-surface-2, #f6f8fa);
  border-radius: 6px;
  font-family: var(--fu-mono);
  font-size: 11.5px;
  max-height: 120px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
