<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { workerApi } from '@/api'
import { useAppStore } from '@/stores/app'
import { useSettingsStore } from '@/stores/settings'
import { downloadBlob, stampName } from '@/utils/download'
import { useDetailStore } from '@/stores/detail'

const store = useAppStore()
const settings = useSettingsStore()
const router = useRouter()
const detail = useDetailStore()

const loading = ref(false)
const keyword = ref('')
const onlyOnline = ref(false)

const rows = computed(() => {
  let list = store.workers || []
  if (onlyOnline.value) list = list.filter((w) => w.status)
  if (keyword.value.trim()) {
    const kw = keyword.value.trim().toLowerCase()
    list = list.filter((w) => w.name.toLowerCase().includes(kw))
  }
  return list
})

async function refresh(force = true) {
  loading.value = true
  try {
    const res = await workerApi.table(force)
    store.workers = res.data || []
  } catch (err) {
    ElMessage.error(err?.message || '刷新失败')
  } finally {
    loading.value = false
  }
}

/* ------------------------- 远程控制 ------------------------- */
async function run(action, name, fn, confirmText) {
  if (confirmText) {
    const ok = await ElMessageBox.confirm(confirmText, `确认${action}`, {
      type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消'
    }).catch(() => false)
    if (!ok) return
  }
  try {
    const res = await fn()
    ElMessage.success(res?.message || `${action}成功`)
    setTimeout(() => refresh(true), 400)
  } catch (err) {
    ElMessage.error(err?.message || `${action}失败`)
  }
}

const shutdown = (row) =>
  run('关闭', row.name, () => workerApi.shutdown(row.name),
    `确定要关闭 Worker「${row.name}」吗？该节点将停止消费任务。`)

const poolRestart = (row) =>
  run('重启进程池', row.name, () => workerApi.poolRestart(row.name),
    `重启「${row.name}」的进程池会中断正在执行的任务，确定继续？`)

const grow = (row) => run('扩容', row.name, () => workerApi.poolGrow(row.name, 1))
const shrink = (row) => run('缩容', row.name, () => workerApi.poolShrink(row.name, 1))

async function autoscale(row) {
  const res = await ElMessageBox.prompt('输入自动伸缩范围，格式 min,max', '设置 Autoscale', {
    inputValue: '2,10',
    inputPattern: /^\d+\s*,\s*\d+$/,
    inputErrorMessage: '格式应为 min,max，例如 2,10'
  }).catch(() => null)
  if (!res) return
  const [min, max] = res.value.split(',').map((x) => parseInt(x.trim(), 10))
  run('设置伸缩', row.name, () => workerApi.poolAutoscale(row.name, min, max))
}

async function addConsumer(row) {
  const res = await ElMessageBox.prompt('输入要订阅的队列名', '新增消费队列', {
    inputPattern: /\S+/, inputErrorMessage: '队列名不能为空'
  }).catch(() => null)
  if (!res) return
  run('新增队列', row.name, () => workerApi.addConsumer(row.name, res.value.trim()))
}

function cancelConsumer(row, queue) {
  run('取消队列', row.name, () => workerApi.cancelConsumer(row.name, queue),
    `确定让「${row.name}」停止消费队列「${queue}」？`)
}

/* ------------------------- F-05 导出 ------------------------- */
function exportParams(format) {
  const p = { format }
  if (keyword.value.trim()) p.workername = keyword.value.trim()
  if (onlyOnline.value) p.status = true
  return p
}

async function doExport(format) {
  try {
    const res = await workerApi.export(exportParams(format))
    downloadBlob(res, stampName('workers', format))
    ElMessage.success(`已导出 ${format.toUpperCase()}`)
  } catch (err) {
    let msg = err?.message || '导出失败'
    try {
      // 错误响应体是 blob，解析出服务端 detail 提示
      if (err?.response?.data instanceof Blob) {
        msg = JSON.parse(await err.response.data.text())?.detail || msg
      }
    } catch { /* 保持默认提示 */ }
    ElMessage.error(msg)
  }
}

onMounted(() => {
  if (!store.workers.length) refresh(false)
})
</script>

<template>
  <div class="page">
    <div class="toolbar mb">
      <el-input v-model="keyword" placeholder="搜索 Worker 名称" clearable style="width: 240px"
        :prefix-icon="'Search'" />
      <el-checkbox v-model="onlyOnline">仅显示在线</el-checkbox>
      <div class="grow" />
      <span class="text-muted" style="font-size: 12.5px">
        在线 {{ store.workers.filter((w) => w.status).length }} / 共 {{ store.workers.length }}
      </span>
      <el-button :icon="'Refresh'" :loading="loading" @click="refresh(true)">刷新</el-button>
      <el-dropdown trigger="click" @command="doExport">
        <el-button :icon="'Download'">导出<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="csv">导出 CSV（Excel）</el-dropdown-item>
            <el-dropdown-item command="json">导出 JSON</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>

    <div class="panel">
      <el-table v-loading="loading" :data="rows" :size="settings.tableSize" stripe>
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="expand">
              <el-descriptions :column="4" size="small" border>
                <el-descriptions-item label="PID">{{ row.pid ?? '-' }}</el-descriptions-item>
                <el-descriptions-item label="并发数">{{ row.concurrency ?? '-' }}</el-descriptions-item>
                <el-descriptions-item label="心跳周期">{{ row.freq ? row.freq + 's' : '-' }}</el-descriptions-item>
                <el-descriptions-item label="负载">
                  {{ row.loadavg ? row.loadavg.join(' / ') : '-' }}
                </el-descriptions-item>
                <el-descriptions-item label="软件">
                  {{ row.sw_ident || '-' }} {{ row.sw_ver || '' }}
                </el-descriptions-item>
                <el-descriptions-item label="系统">{{ row.sw_sys || '-' }}</el-descriptions-item>
                <el-descriptions-item label="撤销数">{{ row.revoked ?? 0 }}</el-descriptions-item>
                <el-descriptions-item label="重试数">{{ row.retried ?? 0 }}</el-descriptions-item>
              </el-descriptions>

              <div class="queues">
                <span class="text-muted" style="font-size: 12.5px">消费队列：</span>
                <el-tag v-for="q in row.queues" :key="q" size="small" closable class="qtag"
                  @close="cancelConsumer(row, q)">
                  {{ q }}
                </el-tag>
                <span v-if="!row.queues?.length" class="text-muted" style="font-size: 12.5px">无</span>
                <el-button text size="small" :icon="'Plus'" :disabled="!row.status"
                  @click="addConsumer(row)">添加</el-button>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="name" label="Worker" min-width="220" sortable show-overflow-tooltip>
          <template #default="{ row }">
            <span class="dot" :class="row.status ? 'on' : 'off'" />
            <span class="link mono" @click="detail.openWorker(row.name)">
              {{ row.name }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="92" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status ? 'success' : 'info'" size="small" effect="light">
              {{ row.status ? '在线' : '离线' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="concurrency" label="并发" width="76" align="right" sortable />
        <el-table-column prop="active" label="活跃" width="76" align="right" sortable>
          <template #default="{ row }">
            <span :class="row.active ? 'busy' : 'text-muted'">{{ row.active }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="processed" label="已处理" width="92" align="right" sortable />
        <el-table-column prop="succeeded" label="成功" width="82" align="right" sortable>
          <template #default="{ row }"><span class="ok">{{ row.succeeded }}</span></template>
        </el-table-column>
        <el-table-column prop="failed" label="失败" width="82" align="right" sortable>
          <template #default="{ row }">
            <span :class="row.failed ? 'bad' : 'text-muted'">{{ row.failed }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="retried" label="重试" width="76" align="right" sortable />
        <el-table-column label="负载" width="132">
          <template #default="{ row }">
            <span class="mono text-muted" style="font-size: 12px">
              {{ row.loadavg ? row.loadavg.map((x) => x.toFixed(2)).join(' ') : '-' }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="176" fixed="right" align="center">
          <template #default="{ row }">
            <el-dropdown trigger="click" :disabled="!row.status">
              <el-button size="small" :disabled="!row.status">
                控制<el-icon class="el-icon--right"><ArrowDown /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item :icon="'Plus'" @click="grow(row)">进程池 +1</el-dropdown-item>
                  <el-dropdown-item :icon="'Minus'" @click="shrink(row)">进程池 -1</el-dropdown-item>
                  <el-dropdown-item :icon="'Sort'" @click="autoscale(row)">设置 Autoscale</el-dropdown-item>
                  <el-dropdown-item :icon="'RefreshRight'" divided @click="poolRestart(row)">
                    重启进程池
                  </el-dropdown-item>
                  <el-dropdown-item :icon="'SwitchButton'" @click="shutdown(row)">关闭节点</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-button size="small" text type="primary"
              @click="detail.openWorker(row.name)">
              详情
            </el-button>
          </template>
        </el-table-column>

        <template #empty>
          <el-empty description="暂无 Worker 数据" :image-size="80" />
        </template>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.expand {
  padding: 12px 20px 14px 48px;
  background: #fafbfc;
}

.queues {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.qtag {
  margin-right: 2px;
}

.ok {
  color: var(--el-color-success);
}

.bad {
  color: var(--el-color-danger);
  font-weight: 600;
}

.busy {
  color: var(--el-color-primary);
  font-weight: 600;
}
</style>
