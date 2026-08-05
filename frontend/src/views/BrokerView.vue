<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { brokerApi } from '@/api'
import { AXIS_STYLE, CHART_GRID, useChart } from '@/composables/useChart'
import { fmtFromNow } from '@/utils/format'

const data = ref({ queues: [] })
const loading = ref(false)
let timer = null

const queues = computed(() => data.value.queues || [])
const totalMessages = computed(() => queues.value.reduce((s, q) => s + (q.messages || 0), 0))
const totalReady = computed(() => queues.value.reduce((s, q) => s + (q.messages_ready || 0), 0))
const totalUnacked = computed(() =>
  queues.value.reduce((s, q) => s + (q.messages_unacknowledged || 0), 0))
const totalConsumers = computed(() => queues.value.reduce((s, q) => s + (q.consumers || 0), 0))

const { el: chartEl } = useChart(
  () => {
    const rows = queues.value
    return {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { right: 8, top: 0, itemWidth: 12, itemHeight: 8,
        textStyle: { fontSize: 11, color: '#606266' } },
      grid: { ...CHART_GRID, bottom: 46 },
      xAxis: {
        type: 'category',
        data: rows.map((q) => q.name),
        ...AXIS_STYLE,
        axisLabel: { ...AXIS_STYLE.axisLabel, rotate: rows.length > 6 ? 28 : 0 }
      },
      yAxis: { type: 'value', minInterval: 1, ...AXIS_STYLE },
      series: [
        { name: '待消费 (ready)', type: 'bar', stack: 'm', barMaxWidth: 34,
          itemStyle: { color: '#409eff', borderRadius: [0, 0, 0, 0] },
          data: rows.map((q) => q.messages_ready || 0) },
        { name: '未确认 (unacked)', type: 'bar', stack: 'm', barMaxWidth: 34,
          itemStyle: { color: '#e6a23c', borderRadius: [3, 3, 0, 0] },
          data: rows.map((q) => q.messages_unacknowledged || 0) }
      ]
    }
  },
  [queues]
)

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    data.value = await brokerApi.overview()
  } catch (err) {
    if (!silent) ElMessage.error(err?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

function levelType(n) {
  if (n > 500) return 'danger'
  if (n > 100) return 'warning'
  return 'success'
}

onMounted(async () => {
  await load()
  timer = setInterval(() => load(true), 5000)
})

onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="page" v-loading="loading">
    <div class="panel mb">
      <div class="bhead">
        <div class="bhead-left">
          <el-tag type="primary" effect="light" size="large">
            {{ data.transport || '-' }}
          </el-tag>
          <span class="mono burl">{{ data.broker_url }}</span>
          <el-tag v-if="data.mock_mode" type="warning" size="small">演示数据</el-tag>
        </div>
        <el-button size="small" :icon="'Refresh'" @click="load()">刷新</el-button>
      </div>
    </div>

    <div class="mini-grid mb">
      <div class="mini"><div class="mini-label">队列总数</div>
        <div class="mini-val">{{ queues.length }}</div></div>
      <div class="mini"><div class="mini-label">消息总量</div>
        <div class="mini-val">{{ totalMessages }}</div></div>
      <div class="mini"><div class="mini-label">待消费</div>
        <div class="mini-val" style="color: #409eff">{{ totalReady }}</div></div>
      <div class="mini"><div class="mini-label">未确认</div>
        <div class="mini-val" style="color: #e6a23c">{{ totalUnacked }}</div></div>
      <div class="mini"><div class="mini-label">消费者</div>
        <div class="mini-val" style="color: #67c23a">{{ totalConsumers }}</div></div>
    </div>

    <div class="panel mb">
      <div class="panel-head">
        <span class="panel-title">队列积压分布</span>
        <span class="text-muted panel-sub">每 5 秒自动刷新</span>
      </div>
      <div ref="chartEl" style="height: 280px" />
    </div>

    <div class="panel">
      <div class="panel-head"><span class="panel-title">队列明细</span></div>
      <el-table :data="queues" size="default" stripe>
        <el-table-column prop="name" label="队列名称" min-width="180" sortable>
          <template #default="{ row }"><span class="mono">{{ row.name }}</span></template>
        </el-table-column>
        <el-table-column prop="messages" label="消息总数" width="120" align="right" sortable>
          <template #default="{ row }">
            <el-tag :type="levelType(row.messages)" size="small" effect="light">
              {{ row.messages ?? 0 }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="messages_ready" label="待消费" width="110" align="right" sortable />
        <el-table-column prop="messages_unacknowledged" label="未确认" width="110" align="right" sortable />
        <el-table-column prop="consumers" label="消费者" width="100" align="right" sortable />
        <el-table-column label="积压水位" min-width="200">
          <template #default="{ row }">
            <el-progress
              :percentage="Math.min(100, Math.round((row.messages || 0) / 10))"
              :stroke-width="10"
              :status="row.messages > 500 ? 'exception' : row.messages > 100 ? 'warning' : 'success'"
              :show-text="false" />
          </template>
        </el-table-column>
        <el-table-column label="空闲自" width="140">
          <template #default="{ row }">
            <span class="text-muted">{{ row.idle_since ? fmtFromNow(row.idle_since) : '-' }}</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :image-size="80"
            description="无法获取队列信息（RabbitMQ 需配置 --broker_api，Redis 需可连接）" />
        </template>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.bhead {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  gap: 14px;
  flex-wrap: wrap;
}

.bhead-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.burl {
  font-size: 13px;
  color: var(--fu-text);
}

.mini-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
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
  font-size: 22px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  line-height: 1.4;
}
</style>
