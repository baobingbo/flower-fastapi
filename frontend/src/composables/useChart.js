import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

/**
 * 轻量 ECharts 封装：自动初始化、自适应尺寸、随数据刷新、卸载时销毁。
 * @param {Function} optionFn 返回 ECharts option 的函数
 * @param {Array} deps 需要监听的响应式依赖
 */
export function useChart(optionFn, deps = []) {
  const el = ref(null)
  let chart = null

  function render() {
    if (!el.value) return
    if (!chart) chart = echarts.init(el.value)
    chart.setOption(optionFn(), true)
  }

  function resize() {
    chart?.resize()
  }

  onMounted(() => {
    render()
    window.addEventListener('resize', resize)
  })

  onBeforeUnmount(() => {
    window.removeEventListener('resize', resize)
    chart?.dispose()
    chart = null
  })

  watch(deps, render, { deep: true })

  return { el, render, resize }
}

/** 统一的浅色主题网格与配色 */
export const CHART_GRID = { left: 46, right: 18, top: 28, bottom: 30 }

export const CHART_PALETTE = [
  '#409eff', '#67c23a', '#e6a23c', '#f56c6c',
  '#909399', '#9254de', '#36cfc9', '#ff85c0'
]

export const AXIS_STYLE = {
  axisLine: { lineStyle: { color: '#dcdfe6' } },
  axisLabel: { color: '#909399', fontSize: 11 },
  splitLine: { lineStyle: { color: '#f0f2f5' } }
}
