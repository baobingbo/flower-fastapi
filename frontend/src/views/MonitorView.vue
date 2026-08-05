<script setup>
import { computed, onMounted, ref } from 'vue'

import { dashboardApi } from '@/api'
import { useAppStore } from '@/stores/app'
import { AXIS_STYLE, CHART_GRID, useChart } from '@/composables/useChart'
import { fmtTimeShort } from '@/utils/format'

const store = useAppStore()
const distribution = ref([])
const range = ref(120)

const points = computed(() => (store.timeline || []).slice(-range.value))

/* ---------------- 成功 / 失败速率 ---------------- */
const { el: rateEl } = useChart(
  () => ({
    tooltip: { trigger: 'axis' },
    legend: { data: ['成功', '失败', '重试', '撤销'], right: 8, top: 0,
      itemWidth: 12, itemHeight: 8, textStyle: { fontSize: 11, color: '#606266' } },
    grid: CHART_GRID,
    xAxis: { type: 'category', boundaryGap: false,
      data: points.value.map((p) => fmtTimeShort(p.ts)), ...AXIS_STYLE },
    yAxis: { type: 'value', minInterval: 1, name: '任务数 / 2s',
      nameTextStyle: { fontSize: 11, color: '#909399' }, ...AXIS_STYLE },
    series: [
      { name: '成功', type: 'line', smooth: true, showSymbol: false, stack: 'a',
        areaStyle: { color: '#67c23a', opacity: 0.16 }, lineStyle: { color: '#67c23a', width: 2 },
        itemStyle: { color: '#67c23a' }, data: points.value.map((p) => p.succeeded || 0) },
      { name: '失败', type: 'line', smooth: true, showSymbol: false, stack: 'a',
        areaStyle: { color: '#f56c6c', opacity: 0.16 }, lineStyle: { color: '#f56c6c', width: 2 },
        itemStyle: { color: '#f56c6c' }, data: points.value.map((p) => p.failed || 0) },
      { name: '重试', type: 'line', smooth: true, showSymbol: false, stack: 'a',
        areaStyle: { color: '#e6a23c', opacity: 0.16 }, lineStyle: { color: '#e6a23c', width: 2 },
        itemStyle: { color: '#e6a23c' }, data: points.value.map((p) => p.retried || 0) },
      { name: '撤销', type: 'line', smooth: true, showSymbol: false, stack: 'a',
        areaStyle: { color: '#909399', opacity: 0.16 }, lineStyle: { color: '#909399', width: 2 },
        itemStyle: { color: '#909399' }, data: points.value.map((p) => p.revoked || 0) }
    ]
  }),
  [points]
)

/* ---------------- 并发度 ---------------- */
const { el: activeEl } = useChart(
  () => ({
    tooltip: { trigger: 'axis' },
    grid: CHART_GRID,
    xAxis: { type: 'category', boundaryGap: false,
      data: points.value.map((p) => fmtTimeShort(p.ts)), ...AXIS_STYLE },
    yAxis: { type: 'value', minInterval: 1, ...AXIS_STYLE },
    series: [{
      name: '执行中', type: 'line', smooth: true, showSymbol: false,
      lineStyle: { color: '#9254de', width: 2 }, itemStyle: { color: '#9254de' },
      areaStyle: { color: '#9254de', opacity: 0.14 },
      data: points.value.map((p) => p.active || 0)
    }]
  }),
  [points]
)

/* ---------------- 接收 vs 完成 ---------------- */
const { el: flowEl } = useChart(
  () => ({
    tooltip: { trigger: 'axis' },
    legend: { data: ['接收', '完成'], right: 8, top: 0, itemWidth: 12, itemHeight: 8,
      textStyle: { fontSize: 11, color: '#606266' } },
    grid: CHART_GRID,
    xAxis: { type: 'category', boundaryGap: false,
      data: points.value.map((p) => fmtTimeShort(p.ts)), ...AXIS_STYLE },
    yAxis: { type: 'value', minInterval: 1, ...AXIS_STYLE },
    series: [
      { name: '接收', type: 'bar', barMaxWidth: 10, itemStyle: { color: '#409eff' },
        data: points.value.map((p) => p.received || 0) },
      { name: '完成', type: 'bar', barMaxWidth: 10, itemStyle: { color: '#67c23a' },
        data: points.value.map((p) => (p.succeeded || 0) + (p.failed || 0)) }
    ]
  }),
  [points]
)

/* ---------------- 平均耗时排行 ---------------- */
const { el: runtimeEl } = useChart(
  () => {
    const rows = [...distribution.value]
      .filter((r) => r.avg_runtime !== null && r.avg_runtime !== undefined)
      .sort((a, b) => a.avg_runtime - b.avg_runtime)
    return {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: (p) => `${p[0].name}<br/>平均耗时 ${p[0].value} s` },
      grid: { ...CHART_GRID, left: 160 },
      xAxis: { type: 'value', name: '秒', nameTextStyle: { fontSize: 11, color: '#909399' },
        ...AXIS_STYLE },
      yAxis: { type: 'category', data: rows.map((r) => r.name.split('.').pop()), ...AXIS_STYLE },
      series: [{
        type: 'bar', barMaxWidth: 16,
        itemStyle: {
          color: (p) => ['#67c23a', '#95d475', '#e6a23c', '#f89898', '#f56c6c'][
            Math.min(4, Math.floor(p.value / 2))],
          borderRadius: [0, 4, 4, 0]
        },
        data: rows.map((r) => r.avg_runtime)
      }]
    }
  },
  [distribution]
)

async function loadDist() {
  const res = await dashboardApi.distribution(12).catch(() => ({ data: [] }))
  distribution.value = res.data || []
}

onMounted(async () => {
  if (!store.timeline.length) {
    const res = await dashboardApi.timeline(360).catch(() => ({ points: [] }))
    store.timeline = res.points || []
  }
  await loadDist()
  setInterval(loadDist, 15000)
})
</script>

<template>
  <div class="page">
    <div class="toolbar mb">
      <span class="text-muted" style="font-size: 12.5px">显示范围</span>
      <el-radio-group v-model="range" size="small">
        <el-radio-button :value="30">1 分钟</el-radio-button>
        <el-radio-button :value="90">3 分钟</el-radio-button>
        <el-radio-button :value="150">5 分钟</el-radio-button>
        <el-radio-button :value="360">12 分钟</el-radio-button>
      </el-radio-group>
      <div class="grow" />
      <span class="text-muted" style="font-size: 12.5px">
        <span class="dot" :class="store.connected ? 'on' : 'off'" />
        {{ store.connected ? '实时推送中' : '连接断开' }} · 采样点 {{ points.length }}
      </span>
      <el-button size="small" :icon="'Link'" tag="a" href="/metrics" target="_blank">
        Prometheus 指标
      </el-button>
    </div>

    <el-row :gutter="14" class="mb">
      <el-col :xs="24" :lg="14">
        <div class="panel">
          <div class="panel-head">
            <span class="panel-title">任务完成速率</span>
            <span class="text-muted panel-sub">按状态堆叠 · 每 2 秒采样</span>
          </div>
          <div ref="rateEl" style="height: 280px" />
        </div>
      </el-col>
      <el-col :xs="24" :lg="10">
        <div class="panel">
          <div class="panel-head">
            <span class="panel-title">并发执行数</span>
            <span class="text-muted panel-sub">STARTED 状态实时计数</span>
          </div>
          <div ref="activeEl" style="height: 280px" />
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="14">
      <el-col :xs="24" :lg="14">
        <div class="panel">
          <div class="panel-head">
            <span class="panel-title">接收 vs 完成</span>
            <span class="text-muted panel-sub">两者差值反映积压趋势</span>
          </div>
          <div ref="flowEl" style="height: 300px" />
        </div>
      </el-col>
      <el-col :xs="24" :lg="10">
        <div class="panel">
          <div class="panel-head">
            <span class="panel-title">平均耗时排行</span>
            <span class="text-muted panel-sub">按任务类型</span>
          </div>
          <div ref="runtimeEl" style="height: 300px" />
        </div>
      </el-col>
    </el-row>
  </div>
</template>
