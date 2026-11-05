import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

import { useThemeStore } from '@/stores/theme'

/** 统一的浅色主题网格与配色（网格尺寸与主题无关，保持不变） */
export const CHART_GRID = { left: 46, right: 18, top: 28, bottom: 30 }

/* ---------------- 主题自适应图表颜色（G1） ----------------
 * 主题 CSS（src/styles/themes/*.css、themes/*.css）在 data-theme 下定义：
 *   --fu-chart-1~6   系列配色（蓝/绿/橙/红/紫/青）
 *   --fu-chart-axis  轴线与图表文字
 *   --fu-chart-split 分割线
 * 以下函数在每次渲染时从 <html> 计算样式读取，变量缺失时回退到内置浅色值。
 */
const FALLBACK_PALETTE = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c', '#909399', '#9254de', '#36cfc9', '#ff85c0']

/** 读取 <html> 上的单个 CSS 变量；读不到（或 SSR 环境）时返回 fallback */
export function chartVar(name, fallback = '') {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name)
    return (v && v.trim()) || fallback
  } catch {
    return fallback
  }
}

/** 系列配色：1~4/5/6 取自 --fu-chart-1~6；第 5 位(灰)、第 8 位(粉)无主题变量，保留内置值 */
export function chartPalette() {
  return [
    chartVar('--fu-chart-1', FALLBACK_PALETTE[0]),
    chartVar('--fu-chart-2', FALLBACK_PALETTE[1]),
    chartVar('--fu-chart-3', FALLBACK_PALETTE[2]),
    chartVar('--fu-chart-4', FALLBACK_PALETTE[3]),
    FALLBACK_PALETTE[4],
    chartVar('--fu-chart-5', FALLBACK_PALETTE[5]),
    chartVar('--fu-chart-6', FALLBACK_PALETTE[6]),
    FALLBACK_PALETTE[7]
  ]
}

/** 轴线/图表文字色：--fu-chart-axis，兜底 #909399 */
export function axisColor() {
  return chartVar('--fu-chart-axis', '#909399')
}

/** 坐标轴样式（轴线 / 刻度文字 / 分割线），渲染时按当前主题取值 */
export function axisStyle() {
  return {
    axisLine: { lineStyle: { color: chartVar('--fu-chart-axis', '#dcdfe6') } },
    axisLabel: { color: axisColor(), fontSize: 11 },
    splitLine: { lineStyle: { color: chartVar('--fu-chart-split', '#f0f2f5') } }
  }
}

/**
 * 轻量 ECharts 封装：自动初始化、自适应尺寸、随数据刷新、跟随主题、卸载时销毁。
 * - G1：watch useThemeStore().activeId，主题切换时立即按新 --fu-chart-* 重绘
 *       （无循环依赖：stores/theme.js 不引用本文件）
 * - G2：首次渲染保留默认动画；后续更新用合并模式（notMerge:false + lazyUpdate）
 *       且浅合并 animation:false，消除 2s 定时刷新 notMerge 全量重绘的闪烁
 * @param {Function} optionFn 返回 ECharts option 的函数
 * @param {Array} deps 需要监听的响应式依赖
 */
export function useChart(optionFn, deps = []) {
  const el = ref(null)
  let chart = null
  let first = true

  function render() {
    if (!el.value) return
    if (!chart) chart = echarts.init(el.value)
    if (first) {
      first = false
      chart.setOption(optionFn()) // 首次：默认 merge，保留默认入场动画
    } else {
      // 后续：合并更新 + 关动画 + 延迟提交，避免整图重绘闪烁
      chart.setOption({ ...optionFn(), animation: false }, { notMerge: false, lazyUpdate: true })
    }
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

  // G1：主题切换即时重绘（读取渲染时的最新 --fu-chart-* 变量）
  const themeStore = useThemeStore()
  watch(() => themeStore.activeId, render)

  return { el, render, resize }
}
