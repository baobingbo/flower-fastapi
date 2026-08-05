<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { taskApi, workerApi } from '@/api'
import { fmtBytes, fmtRuntime, fmtTime, fmtUptime, prettyJson, truncate } from '@/utils/format'

// 作为悬浮抽屉的内容：由父级传入 name，内部跳转通过 emit 交给抽屉处理
const props = defineProps({ name: { type: String, default: '' } })
const emit = defineEmits(['open-task', 'open-worker'])

const name = computed(() => props.name)
const info = ref(null)
const loading = ref(false)
const notFound = ref(false)
const tab = ref('active')
let timer = null

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    info.value = await workerApi.detail(name.value, !silent)
    notFound.value = false
  } catch (err) {
    if (err?.status === 404) notFound.value = true
    else if (!silent) ElMessage.error(err?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

/* ------------------------- 控制动作 ------------------------- */
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

const growN = ref(1)
const shrinkN = ref(1)

const shutdown = () => act('关闭节点', () => workerApi.shutdown(name.value),
  `确定关闭 Worker「${name.value}」？该节点将停止消费任务。`)
const poolRestart = () => act('重启进程池', () => workerApi.poolRestart(name.value),
  '重启进程池会中断当前正在执行的任务，确定继续？')
const grow = () => act('扩容', () => workerApi.poolGrow(name.value, growN.value))
const shrink = () => act('缩容', () => workerApi.poolShrink(name.value, shrinkN.value))

const autoMin = ref(2)
const autoMax = ref(10)
const autoscale = () => act('设置伸缩',
  () => workerApi.poolAutoscale(name.value, autoMin.value, autoMax.value))

const newQueue = ref('')
async function addConsumer() {
  if (!newQueue.value.trim()) return ElMessage.warning('请输入队列名')
  await act('新增队列', () => workerApi.addConsumer(name.value, newQueue.value.trim()))
  newQueue.value = ''
}
const cancelConsumer = (q) => act('取消队列', () => workerApi.cancelConsumer(name.value, q),
  `确定停止消费队列「${q}」？`)

/* ------------------------- 限流 / 超时 ------------------------- */
const limitForm = ref({ taskname: '', ratelimit: '10/m' })
const timeoutForm = ref({ taskname: '', soft: 30, hard: 60 })

const setRateLimit = () => {
  if (!limitForm.value.taskname) return ElMessage.warning('请选择任务类型')
  act('设置限流', () => taskApi.rateLimit(
    limitForm.value.taskname, name.value, limitForm.value.ratelimit))
}

const setTimeout_ = () => {
  if (!timeoutForm.value.taskname) return ElMessage.warning('请选择任务类型')
  act('设置超时', () => taskApi.timeout(
    timeoutForm.value.taskname, name.value, timeoutForm.value.soft, timeoutForm.value.hard))
}

const revokeTask = (uuid, terminate) => act(terminate ? '终止任务' : '撤销任务',
  () => taskApi.revoke(uuid, terminate),
  `确定${terminate ? '终止' : '撤销'}任务 ${uuid}？`)

/* ------------------------- 展示辅助 ------------------------- */
const pool = computed(() => info.value?.pool || {})
const totalRows = computed(() =>
  Object.entries(info.value?.total || {})
    .map(([k, v]) => ({ name: k, count: v }))
    .sort((a, b) => b.count - a.count)
)
const confRows = computed(() =>
  Object.entries(info.value?.conf || {}).map(([k, v]) => ({ key: k, value: v }))
)
const rusageRows = computed(() =>
  Object.entries(info.value?.rusage || {}).map(([k, v]) => ({ key: k, value: v }))
)

const RUSAGE_LABEL = {
  utime: '用户态 CPU 时间(s)', stime: '内核态 CPU 时间(s)', maxrss: '最大常驻内存',
  idrss: '非共享数据段', isrss: '非共享栈', ixrss: '共享内存',
  majflt: '主缺页', minflt: '次缺页', nswap: '换页次数',
  inblock: '块输入', oublock: '块输出', msgsnd: '发送消息',
  msgrcv: '接收消息', nsignals: '信号数', nvcsw: '主动上下文切换', nivcsw: '被动上下文切换'
}

function rusageValue(k, v) {
  if (k === 'maxrss') return fmtBytes(v)
  if (k === 'utime' || k === 'stime') return `${Number(v).toFixed(2)} s`
  return v
}

watch(() => props.name, () => load())

onMounted(async () => {
  await load()
  timer = setInterval(() => load(true), 5000)
})

onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="page" v-loading="loading">
    <el-result v-if="notFound" icon="warning" title="Worker 不存在"
      :sub-title="`未找到 Worker ${name}`" />

    <template v-else-if="info">
      <!-- 顶部信息条 -->
      <div class="panel mb">
        <div class="head">
          <div class="head-left">
            <span class="dot" :class="info.online ? 'on' : 'off'" />
            <span class="wname mono">{{ info.name }}</span>
            <el-tag :type="info.online ? 'success' : 'info'" size="small">
              {{ info.online ? '在线' : '离线' }}
            </el-tag>
            <span class="text-muted" style="font-size: 12.5px">
              PID {{ info.pid ?? '-' }} · 心跳 {{ fmtTime(info.timestamp) }}
            </span>
          </div>
          <div class="head-right">
            <el-button size="small" :icon="'Refresh'" @click="load()">刷新</el-button>
            <el-button size="small" type="warning" plain :disabled="!info.online" @click="poolRestart">
              重启进程池
            </el-button>
            <el-button size="small" type="danger" plain :disabled="!info.online" @click="shutdown">
              关闭节点
            </el-button>
          </div>
        </div>
      </div>

      <!-- 概览指标 -->
      <div class="mini-grid mb">
        <div class="mini"><div class="mini-label">进程池并发</div>
          <div class="mini-val">{{ pool['max-concurrency'] ?? '-' }}</div></div>
        <div class="mini"><div class="mini-label">最小并发</div>
          <div class="mini-val">{{ pool['min-concurrency'] ?? '-' }}</div></div>
        <div class="mini"><div class="mini-label">Prefetch</div>
          <div class="mini-val">{{ info.prefetch_count ?? '-' }}</div></div>
        <div class="mini"><div class="mini-label">子进程数</div>
          <div class="mini-val">{{ pool.processes?.length ?? '-' }}</div></div>
        <div class="mini"><div class="mini-label">运行时长</div>
          <div class="mini-val sm">{{ fmtUptime(info.other?.uptime) }}</div></div>
        <div class="mini"><div class="mini-label">Autoscaler</div>
          <div class="mini-val sm">
            {{ info.autoscaler ? `${info.autoscaler.min}~${info.autoscaler.max}` : '未启用' }}
          </div></div>
      </div>

      <el-row :gutter="14" class="mb">
        <!-- 进程池控制 -->
        <el-col :xs="24" :lg="12">
          <div class="panel" style="height: 100%">
            <div class="panel-head"><span class="panel-title">进程池控制</span></div>
            <div class="ctrl">
              <div class="ctrl-row">
                <span class="ctrl-label">扩容</span>
                <el-input-number v-model="growN" :min="1" :max="64" size="small" controls-position="right" />
                <el-button size="small" type="primary" plain :disabled="!info.online" @click="grow">
                  Grow
                </el-button>
              </div>
              <div class="ctrl-row">
                <span class="ctrl-label">缩容</span>
                <el-input-number v-model="shrinkN" :min="1" :max="64" size="small" controls-position="right" />
                <el-button size="small" type="primary" plain :disabled="!info.online" @click="shrink">
                  Shrink
                </el-button>
              </div>
              <div class="ctrl-row">
                <span class="ctrl-label">自动伸缩</span>
                <el-input-number v-model="autoMin" :min="0" :max="64" size="small" controls-position="right"
                  style="width: 96px" />
                <span class="text-muted">~</span>
                <el-input-number v-model="autoMax" :min="1" :max="128" size="small" controls-position="right"
                  style="width: 96px" />
                <el-button size="small" type="primary" plain :disabled="!info.online" @click="autoscale">
                  Autoscale
                </el-button>
              </div>
              <el-divider style="margin: 6px 0 12px" />
              <div class="ctrl-row">
                <span class="ctrl-label">子进程</span>
                <div class="pids">
                  <el-tag v-for="p in pool.processes" :key="p" size="small" effect="plain" class="mono">
                    {{ p }}
                  </el-tag>
                  <span v-if="!pool.processes?.length" class="text-muted">-</span>
                </div>
              </div>
              <div class="ctrl-row">
                <span class="ctrl-label">超时设置</span>
                <span class="mono text-muted">
                  soft={{ pool.timeouts?.[0] ?? '-' }} / hard={{ pool.timeouts?.[1] ?? '-' }}
                </span>
              </div>
              <div class="ctrl-row">
                <span class="ctrl-label">写入分布</span>
                <span class="mono text-muted">
                  all={{ pool.writes?.all ?? '-' }} avg={{ pool.writes?.avg ?? '-' }}
                  total={{ pool.writes?.total ?? '-' }}
                </span>
              </div>
            </div>
          </div>
        </el-col>

        <!-- 队列订阅 -->
        <el-col :xs="24" :lg="12">
          <div class="panel" style="height: 100%">
            <div class="panel-head"><span class="panel-title">消费队列</span></div>
            <div class="ctrl">
              <div class="ctrl-row">
                <el-input v-model="newQueue" size="small" placeholder="新队列名称" style="width: 200px"
                  @keyup.enter="addConsumer" />
                <el-button size="small" type="primary" :icon="'Plus'" :disabled="!info.online"
                  @click="addConsumer">添加消费</el-button>
              </div>
              <el-table :data="info.active_queues" size="small" max-height="228" style="margin-top: 8px">
                <el-table-column prop="name" label="队列" min-width="110">
                  <template #default="{ row }"><span class="mono">{{ row.name }}</span></template>
                </el-table-column>
                <el-table-column label="Exchange" min-width="110">
                  <template #default="{ row }">
                    <span class="mono text-muted">
                      {{ row.exchange?.name || '-' }}<span v-if="row.exchange?.type">
                        ({{ row.exchange.type }})</span>
                    </span>
                  </template>
                </el-table-column>
                <el-table-column prop="routing_key" label="Routing Key" min-width="100">
                  <template #default="{ row }">
                    <span class="mono text-muted">{{ row.routing_key || '-' }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="76" align="center">
                  <template #default="{ row }">
                    <el-button text size="small" type="danger" :disabled="!info.online"
                      @click="cancelConsumer(row.name)">取消</el-button>
                  </template>
                </el-table-column>
                <template #empty><el-empty description="无订阅队列" :image-size="54" /></template>
              </el-table>
            </div>
          </div>
        </el-col>
      </el-row>

      <!-- 限流与超时 -->
      <div class="panel mb">
        <div class="panel-head"><span class="panel-title">任务限流与超时</span></div>
        <div class="ctrl limit-area">
          <div class="ctrl-row">
            <span class="ctrl-label">限流</span>
            <el-select v-model="limitForm.taskname" placeholder="选择任务类型" filterable size="small"
              style="width: 260px">
              <el-option v-for="t in info.registered" :key="t" :label="t" :value="t" />
            </el-select>
            <el-input v-model="limitForm.ratelimit" size="small" style="width: 110px" placeholder="10/m" />
            <el-button size="small" type="primary" plain :disabled="!info.online" @click="setRateLimit">
              应用限流
            </el-button>
            <span class="text-muted tip">格式：10/s、100/m、1000/h</span>
          </div>
          <div class="ctrl-row">
            <span class="ctrl-label">超时</span>
            <el-select v-model="timeoutForm.taskname" placeholder="选择任务类型" filterable size="small"
              style="width: 260px">
              <el-option v-for="t in info.registered" :key="t" :label="t" :value="t" />
            </el-select>
            <el-input-number v-model="timeoutForm.soft" :min="1" size="small" controls-position="right"
              style="width: 104px" />
            <el-input-number v-model="timeoutForm.hard" :min="1" size="small" controls-position="right"
              style="width: 104px" />
            <el-button size="small" type="primary" plain :disabled="!info.online" @click="setTimeout_">
              应用超时
            </el-button>
            <span class="text-muted tip">soft / hard，单位秒</span>
          </div>
        </div>
      </div>

      <!-- 任务标签页 -->
      <div class="panel mb">
        <el-tabs v-model="tab" class="tabs">
          <el-tab-pane :label="`执行中 (${info.active?.length || 0})`" name="active">
            <el-table :data="info.active" size="small" max-height="340">
              <el-table-column label="任务 ID" width="130">
                <template #default="{ row }">
                  <span class="link mono" @click="emit('open-task', row.id)">
                    {{ (row.id || '').slice(0, 8) }}…
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="name" label="任务名" min-width="200" show-overflow-tooltip />
              <el-table-column label="参数" min-width="180" show-overflow-tooltip>
                <template #default="{ row }">
                  <span class="mono text-muted">{{ truncate(row.args, 40) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="已运行" width="100" align="right">
                <template #default="{ row }">
                  {{ row.time_start ? fmtRuntime(Date.now() / 1000 - row.time_start) : '-' }}
                </template>
              </el-table-column>
              <el-table-column label="操作" width="130" align="center">
                <template #default="{ row }">
                  <el-button text size="small" type="warning" @click="revokeTask(row.id, false)">撤销</el-button>
                  <el-button text size="small" type="danger" @click="revokeTask(row.id, true)">终止</el-button>
                </template>
              </el-table-column>
              <template #empty><el-empty description="没有执行中的任务" :image-size="60" /></template>
            </el-table>
          </el-tab-pane>

          <el-tab-pane :label="`预取 (${info.reserved?.length || 0})`" name="reserved">
            <el-table :data="info.reserved" size="small" max-height="340">
              <el-table-column label="任务 ID" width="130">
                <template #default="{ row }">
                  <span class="link mono" @click="emit('open-task', row.id)">
                    {{ (row.id || '').slice(0, 8) }}…
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="name" label="任务名" min-width="200" show-overflow-tooltip />
              <el-table-column label="参数" min-width="200" show-overflow-tooltip>
                <template #default="{ row }">
                  <span class="mono text-muted">{{ truncate(row.args, 50) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="90" align="center">
                <template #default="{ row }">
                  <el-button text size="small" type="warning" @click="revokeTask(row.id, false)">撤销</el-button>
                </template>
              </el-table-column>
              <template #empty><el-empty description="没有预取任务" :image-size="60" /></template>
            </el-table>
          </el-tab-pane>

          <el-tab-pane :label="`计划中 (${info.scheduled?.length || 0})`" name="scheduled">
            <el-table :data="info.scheduled" size="small" max-height="340">
              <el-table-column label="任务 ID" width="130">
                <template #default="{ row }">
                  <span class="link mono" @click="emit('open-task', row.request?.id || row.id)">
                    {{ (row.request?.id || row.id || '').slice(0, 8) }}…
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="任务名" min-width="200" show-overflow-tooltip>
                <template #default="{ row }">{{ row.request?.name || row.name || '-' }}</template>
              </el-table-column>
              <el-table-column prop="eta" label="ETA" width="200" />
              <el-table-column prop="priority" label="优先级" width="80" align="right" />
              <template #empty><el-empty description="没有计划任务" :image-size="60" /></template>
            </el-table>
          </el-tab-pane>

          <el-tab-pane :label="`已撤销 (${info.revoked?.length || 0})`" name="revoked">
            <div class="revoked">
              <el-tag v-for="r in info.revoked" :key="r" size="small" effect="plain" class="mono rtag">
                {{ r }}
              </el-tag>
              <el-empty v-if="!info.revoked?.length" description="没有撤销记录" :image-size="60" />
            </div>
          </el-tab-pane>

          <el-tab-pane :label="`已注册 (${info.registered?.length || 0})`" name="registered">
            <div class="revoked">
              <el-tag v-for="r in info.registered" :key="r" size="small" effect="plain" class="mono rtag">
                {{ r }}
              </el-tag>
              <el-empty v-if="!info.registered?.length" description="没有注册任务" :image-size="60" />
            </div>
          </el-tab-pane>

          <el-tab-pane :label="`处理统计 (${totalRows.length})`" name="total">
            <el-table :data="totalRows" size="small" max-height="340">
              <el-table-column prop="name" label="任务名" min-width="260">
                <template #default="{ row }"><span class="mono">{{ row.name }}</span></template>
              </el-table-column>
              <el-table-column prop="count" label="执行次数" width="110" align="right" sortable />
              <el-table-column label="占比" min-width="200">
                <template #default="{ row }">
                  <el-progress
                    :percentage="Math.round(row.count / Math.max(...totalRows.map(r => r.count)) * 100)"
                    :stroke-width="10" :show-text="false" />
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </div>

      <!-- 底部：系统资源 + Broker + 配置 -->
      <el-row :gutter="14">
        <el-col :xs="24" :lg="12">
          <div class="panel" style="height: 100%">
            <div class="panel-head"><span class="panel-title">系统资源 (rusage)</span></div>
            <el-table :data="rusageRows" size="small" max-height="300" :show-header="false">
              <el-table-column width="190">
                <template #default="{ row }">
                  <span class="text-muted" style="font-size: 12.5px">
                    {{ RUSAGE_LABEL[row.key] || row.key }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column align="right">
                <template #default="{ row }">
                  <span class="mono">{{ rusageValue(row.key, row.value) }}</span>
                </template>
              </el-table-column>
              <template #empty><el-empty description="无 rusage 数据" :image-size="54" /></template>
            </el-table>
          </div>
        </el-col>

        <el-col :xs="24" :lg="12">
          <div class="panel" style="height: 100%">
            <div class="panel-head"><span class="panel-title">Broker 连接</span></div>
            <el-descriptions :column="1" size="small" border class="desc">
              <el-descriptions-item label="传输">{{ info.broker?.transport || '-' }}</el-descriptions-item>
              <el-descriptions-item label="地址">
                <span class="mono">{{ info.broker?.hostname }}:{{ info.broker?.port }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="Virtual Host">
                {{ info.broker?.virtual_host ?? '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="SSL">{{ info.broker?.ssl ? '是' : '否' }}</el-descriptions-item>
              <el-descriptions-item label="心跳">{{ info.broker?.heartbeat ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="连接超时">
                {{ info.broker?.connect_timeout ?? '-' }}
              </el-descriptions-item>
            </el-descriptions>
          </div>
        </el-col>
      </el-row>

      <div class="panel" style="margin-top: 14px">
        <div class="panel-head"><span class="panel-title">Worker 配置 (conf)</span></div>
        <el-table :data="confRows" size="small" max-height="320">
          <el-table-column prop="key" label="配置项" width="300">
            <template #default="{ row }"><span class="mono">{{ row.key }}</span></template>
          </el-table-column>
          <el-table-column label="值">
            <template #default="{ row }">
              <span class="mono text-muted">{{ truncate(prettyJson(row.value), 120) }}</span>
            </template>
          </el-table-column>
          <template #empty><el-empty description="无配置数据" :image-size="54" /></template>
        </el-table>
      </div>
    </template>
  </div>
</template>

<style scoped>
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  gap: 14px;
  flex-wrap: wrap;
}

.head-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.head-right {
  display: flex;
  gap: 6px;
}

.wname {
  font-size: 15.5px;
  font-weight: 660;
}

.mini-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
}

.mini {
  background: var(--fu-card);
  border: 1px solid var(--fu-border);
  border-radius: 10px;
  padding: 12px 14px;
}

.mini-label {
  font-size: 12px;
  color: var(--fu-text-muted);
}

.mini-val {
  font-size: 21px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  line-height: 1.4;
}

.mini-val.sm {
  font-size: 15px;
  font-weight: 600;
}

.ctrl {
  padding: 14px 16px 16px;
}

.ctrl-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.ctrl-row:last-child {
  margin-bottom: 0;
}

.ctrl-label {
  width: 64px;
  flex-shrink: 0;
  font-size: 12.5px;
  color: var(--fu-text-muted);
}

.limit-area .ctrl-label {
  width: 44px;
}

.tip {
  font-size: 11.5px;
}

.pids {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
}

.tabs {
  padding: 6px 16px 12px;
}

.revoked {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 300px;
  overflow: auto;
  padding: 6px 0;
}

.rtag {
  font-size: 11.5px;
}

.desc {
  padding: 0 16px 16px;
}
</style>
