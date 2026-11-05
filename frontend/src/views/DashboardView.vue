<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import StatCard from '@/components/StatCard.vue'
import { dashboardApi } from '@/api'
import { useAppStore } from '@/stores/app'
import { useSettingsStore } from '@/stores/settings'
import { useDetailStore } from '@/stores/detail'
import { CHART_GRID, axisColor, axisStyle, chartPalette, chartVar, useChart } from '@/composables/useChart'
import { TASK_STATE_COLOR, fmtTimeShort, truncate } from '@/utils/format'

const store = useAppStore()
const settings = useSettingsStore()
const router = useRouter()
const detail = useDetailStore()

const distribution = ref([])

const s = computed(() => store.summary || {})
const successRate = computed(() => {
  const done = (s.value.succeeded || 0) + (s.value.failed || 0)
  return done ? ((s.value.succeeded / done) * 100).toFixed(1) : '—'
})

/* ------------------------- 吞吐趋势 ------------------------- */
const { el: trendEl } = useChart(
  () => {
    const pts = store.timeline || []
    const xs = pts.map((p) => fmtTimeShort(p.ts))
    const pal = chartPalette()
    const series = [
      { key: 'succeeded', name: '成功', color: pal[1] },
      { key: 'failed', name: '失败', color: pal[3] },
      { key: 'started', name: '开始', color: pal[0] },
      { key: 'retried', name: '重试', color: pal[2] }
    ]
    return {
      tooltip: { trigger: 'axis' },
      legend: { data: series.map((x) => x.name), right: 8, top: 0, itemWidth: 12, itemHeight: 8,
        textStyle: { fontSize: 11, color: axisColor() } },
      grid: CHART_GRID,
      xAxis: { type: 'category', boundaryGap: false, data: xs, ...axisStyle() },
      yAxis: { type: 'value', minInterval: 1, ...axisStyle() },
      series: series.map((x) => ({
        name: x.name,
        type: 'line',
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, color: x.color },
        itemStyle: { color: x.color },
        areaStyle: { color: x.color, opacity: 0.08 },
        data: pts.map((p) => p[x.key] || 0)
      }))
    }
  },
  [() => store.timeline]
)

/* ------------------------- 状态分布 ------------------------- */
const { el: pieEl } = useChart(
  () => {
    const states = s.value.states || {}
    const pal = chartPalette()
    const data = Object.entries(states).map(([name, value]) => ({
      name,
      value,
      itemStyle: { color: TASK_STATE_COLOR[name] || pal[4] }
    }))
    return {
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { bottom: 0, itemWidth: 10, itemHeight: 8, textStyle: { fontSize: 11, color: axisColor() } },
      series: [{
        type: 'pie',
        radius: ['46%', '68%'],
        center: ['50%', '44%'],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: chartVar('--fu-card', '#fff'), borderWidth: 2 },
        label: { show: false },
        data: data.length ? data : [{ name: '暂无数据', value: 1, itemStyle: { color: pal[4] } }]
      }]
    }
  },
  [() => s.value.states]
)

/* ------------------------- Top 任务 ------------------------- */
const { el: barEl } = useChart(
  () => {
    const rows = [...distribution.value].reverse()
    const pal = chartPalette()
    return {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { right: 8, top: 0, itemWidth: 12, itemHeight: 8,
        textStyle: { fontSize: 11, color: axisColor() } },
      grid: { ...CHART_GRID, left: 150 },
      xAxis: { type: 'value', minInterval: 1, ...axisStyle() },
      yAxis: {
        type: 'category',
        data: rows.map((r) => truncate(r.name.split('.').pop(), 18)),
        ...axisStyle(),
        axisLabel: { ...axisStyle().axisLabel, fontSize: 11 }
      },
      series: [
        { name: '成功', type: 'bar', stack: 'x', barMaxWidth: 16,
          itemStyle: { color: pal[1] }, data: rows.map((r) => r.succeeded) },
        { name: '失败', type: 'bar', stack: 'x', barMaxWidth: 16,
          itemStyle: { color: pal[3] }, data: rows.map((r) => r.failed) },
        { name: '重试', type: 'bar', stack: 'x', barMaxWidth: 16,
          itemStyle: { color: pal[2] }, data: rows.map((r) => r.retried) }
      ]
    }
  },
  [distribution]
)

let distTimer = null

async function loadDistribution() {
  try {
    const res = await dashboardApi.distribution(8)
    distribution.value = res.data || []
  } catch (err) {
    ElMessage.error(err?.message || '任务分布加载失败')
  }
}

onMounted(async () => {
  if (!store.timeline.length) {
    try {
      const res = await dashboardApi.timeline(120)
      store.timeline = res.points || []
    } catch (err) {
      ElMessage.error(err?.message || '时间线数据加载失败')
    }
  }
  await loadDistribution()
  distTimer = setInterval(loadDistribution, 15000)
})

onBeforeUnmount(() => clearInterval(distTimer))

const onlineWorkers = computed(() => store.workers.filter((w) => w.status))
</script>

<template>
  <div class="page">
    <el-alert
      v-if="store.mockMode"
      type="warning"
      show-icon
      :closable="false"
      class="mb"
      title="演示模式"
      description="未检测到可用的 Celery Broker，当前展示的是内置模拟集群数据，所有功能均可正常操作体验。"
    />

    <div class="stat-grid mb">
      <StatCard label="在线 Worker" :value="s.workers_online || 0" icon="Cpu" color="var(--fu-brand, #409eff)"
        :hint="`共注册 ${s.workers_total || 0} 个节点`" />
      <StatCard label="执行中任务" :value="s.active || 0" icon="Loading" color="var(--fu-chart-5, #9254de)" hint="STARTED 状态" />
      <StatCard label="已处理" :value="s.processed || 0" icon="DataLine" color="var(--fu-text-secondary, #606266)"
        :hint="`保留 ${s.tasks_total || 0} 条记录`" />
      <StatCard label="成功" :value="s.succeeded || 0" icon="CircleCheck" color="var(--fu-success, #67c23a)"
        :hint="`成功率 ${successRate}%`" />
      <StatCard label="失败" :value="s.failed || 0" icon="CircleClose" color="var(--fu-danger, #f56c6c)" hint="含异常与拒绝" />
      <StatCard label="重试 / 撤销" :value="`${s.retried || 0} / ${s.revoked || 0}`" icon="RefreshRight"
        color="var(--fu-warning, #e6a23c)" hint="重试与撤销计数" />
    </div>

    <el-row :gutter="14" class="mb">
      <el-col :xs="24" :lg="16">
        <div class="panel">
          <div class="panel-head">
            <span class="panel-title">实时吞吐趋势</span>
            <span class="text-muted panel-sub">每 2 秒采样 · 最近 {{ store.timeline.length }} 个采样点</span>
          </div>
          <div ref="trendEl" class="chart" style="height: 268px" />
        </div>
      </el-col>
      <el-col :xs="24" :lg="8">
        <div class="panel">
          <div class="panel-head"><span class="panel-title">任务状态分布</span></div>
          <div ref="pieEl" class="chart" style="height: 268px" />
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="14" class="mb">
      <el-col :xs="24" :lg="12">
        <div class="panel">
          <div class="panel-head">
            <span class="panel-title">Top 任务类型</span>
            <el-button text size="small" @click="router.push('/tasks')">查看全部</el-button>
          </div>
          <div ref="barEl" class="chart" style="height: 300px" />
        </div>
      </el-col>

      <el-col :xs="24" :lg="12">
        <div class="panel">
          <div class="panel-head">
            <span class="panel-title">Worker 概览</span>
            <span class="text-muted panel-sub">{{ onlineWorkers.length }} / {{ store.workers.length }} 在线</span>
          </div>
          <el-table :data="store.workers" :size="settings.tableSize" height="300" @row-click="(r) => detail.openWorker(r.name)"
            class="clickable">
            <el-table-column prop="name" label="名称" min-width="150" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="dot" :class="row.status ? 'on' : 'off'" />
                <span class="mono">{{ row.name }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="active" label="活跃" width="66" align="right" />
            <el-table-column prop="processed" label="已处理" width="78" align="right" />
            <el-table-column prop="succeeded" label="成功" width="66" align="right">
              <template #default="{ row }"><span class="ok">{{ row.succeeded }}</span></template>
            </el-table-column>
            <el-table-column prop="failed" label="失败" width="66" align="right">
              <template #default="{ row }">
                <span :class="row.failed ? 'bad' : 'text-muted'">{{ row.failed }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-col>
    </el-row>

    <div class="panel">
      <div class="panel-head">
        <span class="panel-title">实时事件流</span>
        <span class="text-muted panel-sub">
          <span class="dot" :class="store.connected ? 'on' : 'off'" />
          {{ store.connected ? 'WebSocket 已连接' : '连接断开' }} · 最近 {{ store.eventFeed.length }} 条
        </span>
      </div>
      <div class="feed">
        <div v-if="!store.eventFeed.length" class="feed-empty text-muted">等待事件推送…</div>
        <div v-for="e in store.eventFeed.slice(0, 40)" :key="e._id" class="feed-row">
          <span class="feed-time mono">{{ fmtTimeShort(e.timestamp) }}</span>
          <el-tag size="small" effect="plain" class="feed-type">{{ e.type }}</el-tag>
          <span class="mono feed-name">{{ truncate(e.name || e.hostname || '', 44) }}</span>
          <span class="mono text-muted feed-uuid">{{ (e.uuid || '').slice(0, 8) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(186px, 1fr));
  gap: 12px;
}

.chart {
  width: 100%;
}

.clickable :deep(.el-table__row) {
  cursor: pointer;
}

.feed {
  max-height: 260px;
  overflow: auto;
  padding: 4px 0 8px;
}

.feed-empty {
  padding: 28px 0;
  text-align: center;
  font-size: 13px;
}

.feed-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 5px 16px;
  font-size: 12.5px;
  border-bottom: 1px dashed var(--fu-border);
}

.feed-row:hover {
  background: var(--fu-card-hover, #fafbfe);
}

.feed-time {
  color: var(--fu-text-muted);
  width: 66px;
  flex-shrink: 0;
}

.feed-type {
  width: 128px;
  flex-shrink: 0;
  justify-content: center;
}

.feed-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.feed-uuid {
  flex-shrink: 0;
}

.ok {
  color: var(--el-color-success);
}

.bad {
  color: var(--el-color-danger);
  font-weight: 600;
}
</style>
