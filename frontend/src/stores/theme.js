import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

import {
  BUILTIN_IDS,
  DEFAULT_DARK_THEME,
  DEFAULT_LIGHT_THEME,
  THEMES,
  THEME_IDS,
  applyTheme,
  getTheme
} from '@/theme/registry'
import { themeApi } from '@/api'

const LS_PREFERENCE = 'flower_theme'
const LS_LIGHT = 'flower_theme_light'
const LS_DARK = 'flower_theme_dark'
/** 完整生效主题对象（含远程主题的 url/scheme 等），用于刷新后无损重建 */
const LS_THEME_OBJ = 'flower_theme_obj'

const REFRESH_MS = 5000 // 轮询主题目录，保证"上传/放入文件后自动出现"

/** 系统是否处于深色偏好 */
function systemPrefersDark() {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
}

/** 上次生效主题的完整描述（来自 localStorage，刷新时用于兜底重建） */
const persistedObj = (() => {
  try {
    const raw = localStorage.getItem(LS_THEME_OBJ)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
})()

export const useThemeStore = defineStore('theme', () => {
  /**
   * preference：'auto' 表示跟随系统；否则是具体主题 id。
   * 默认值刻意是 'auto'——需求要求"默认跟随系统主题"。
   */
  const storedPref = persistedObj?.id || localStorage.getItem(LS_PREFERENCE)
  const preference = ref(
    storedPref == null || storedPref === 'auto' ? 'auto' : storedPref
  )

  /** 跟随系统时，浅色/深色分别落到哪个主题（允许用户自定义，比如深色时用科技液态） */
  const lightTheme = ref(localStorage.getItem(LS_LIGHT) || DEFAULT_LIGHT_THEME)
  const darkTheme = ref(localStorage.getItem(LS_DARK) || DEFAULT_DARK_THEME)

  const systemDark = ref(systemPrefersDark())

  /** 运行时从后端发现的用户主题（主题目录扫描得到） */
  const discovered = ref([])

  /** 全部主题 = 内置（打包）+ 用户（目录发现）。这就是主题切换器的数据源。 */
  const themes = computed(() => {
    const builtins = THEMES.map((t) => ({ ...t, builtin: true, remote: false }))
    const users = discovered.value.map((t) => ({ ...t, builtin: false, remote: true }))
    return [...builtins, ...users]
  })

  const themeIds = computed(() => themes.value.map((t) => t.id))

  /** 最终生效的主题 id */
  const activeId = computed(() => {
    const id = preference.value !== 'auto'
      ? preference.value
      : systemDark.value
        ? darkTheme.value
        : lightTheme.value
    // 兜底：解析出的主题已不存在（用户主题被删后的残留态）时，
    // 回退到当前系统深浅色对应的内置主题，避免 applyTheme 加载不存在的 CSS
    if (themeIds.value.includes(id)) return id
    return systemDark.value ? DEFAULT_DARK_THEME : DEFAULT_LIGHT_THEME
  })

  /** 当前生效主题对象（含 scheme/glass/swatch/remote/url），供 applyTheme 使用 */
  const active = computed(() => {
    const id = activeId.value
    const found = themes.value.find((t) => t.id === id)
    if (found) return found
    // 远程主题尚未从后端发现时，用本地持久化对象兜底，避免回退到默认浅色
    if (persistedObj && persistedObj.id === id) return persistedObj
    return getTheme(id)
  })
  const isDark = computed(() => active.value.scheme === 'dark')
  const isAuto = computed(() => preference.value === 'auto')

  /** 切换主题时加一层短暂的全局过渡，避免生硬闪切 */
  let transitionTimer = null
  function withTransition(fn) {
    const root = document.documentElement
    root.classList.add('fu-theme-transition')
    fn()
    clearTimeout(transitionTimer)
    transitionTimer = setTimeout(() => root.classList.remove('fu-theme-transition'), 420)
  }

  function apply() {
    withTransition(() => applyTheme(active.value))
    persistThemeObj()
  }

  /** 把生效主题的完整描述落盘，刷新时可直接重建（含远程主题 url） */
  function persistThemeObj() {
    try {
      // 跟随系统时不清空也会“脏读”：旧的主观选择残留会盖过实时系统主题
      if (preference.value === 'auto') {
        localStorage.removeItem(LS_THEME_OBJ)
        return
      }
      const t = active.value
      localStorage.setItem(
        LS_THEME_OBJ,
        JSON.stringify({
          id: t.id,
          name: t.name,
          scheme: t.scheme,
          glass: t.glass,
          remote: t.remote,
          url: t.url,
          swatch: t.swatch
        })
      )
    } catch {
      /* localStorage 不可用时忽略 */
    }
  }

  function setPreference(value) {
    preference.value = value === 'auto' || themeIds.value.includes(value) ? value : 'auto'
  }

  /** 在浅色/深色两组之间快速对切，同时脱离 auto */
  function toggle() {
    setPreference(isDark.value ? lightTheme.value : darkTheme.value)
  }

  function setSchemeDefault(scheme, id) {
    if (!themeIds.value.includes(id)) return
    if (scheme === 'dark') darkTheme.value = id
    else lightTheme.value = id
  }

  /* ---------------- 运行时主题发现 ---------------- */
  async function refresh() {
    try {
      const data = await themeApi.list()
      const list = (data?.themes || []).filter((t) => !BUILTIN_IDS.has(t.id))
      discovered.value = list
    } catch {
      /* 忽略：后端不可达时仅用内置主题 */
    }
  }

  // 主题轮询由 WebSocket themes_updated 事件驱动（app.js:99-101），不再需要定时轮询
  // 仅在 WebSocket 不可用时的兜底：监听连接状态，断开超过 30s 才启用低频轮询
  let fallbackTimer = null
  const FALLBACK_INTERVAL = 30000 // 30s 兜底间隔
  function startFallbackPolling(disconnectedSince) {
    if (fallbackTimer) return
    fallbackTimer = setInterval(() => {
      // 每 30s 检查一次，如果 WebSocket 仍断开则继续轮询
      if (disconnectedSince > 30000) refresh()
    }, FALLBACK_INTERVAL)
  }
  function stopFallbackPolling() {
    clearInterval(fallbackTimer)
    fallbackTimer = null
  }

  /** 监听系统主题变化——这是"默认跟随系统"的关键 */
  let mql = null
  function initSystemWatcher() {
    mql = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!mql) return
    // 使用 onchange 属性（更可靠的跨浏览器方式）
    mql.onchange = function(e) {
      systemDark.value = e.matches
    }
  }

  // WebSocket 连接状态追踪（由 app store 的 socket 事件驱动）
  let wsConnected = false
  let wsDisconnectTime = 0

  async function init() {
    initSystemWatcher()
    await refresh() // 首次拉取用户主题
    apply() // 应用并持久化当前生效主题
    // 启动兜底轮询（30s 间隔），仅在 WebSocket 断开时生效
    startFallbackPolling(0)
  }

  /** 暴露给 app store 的 WebSocket 状态回调 */
  function setWsConnected(val) {
    wsConnected = val
    if (val) {
      // WebSocket 重连成功，停止兜底轮询，立即刷新主题
      stopFallbackPolling()
      refresh()
    } else {
      // WebSocket 断开，记录时间
      wsDisconnectTime = Date.now()
      startFallbackPolling(wsDisconnectTime)
    }
  }

  watch(activeId, (newId, oldId) => {
    apply()
  })
  watch(preference, (v) => localStorage.setItem(LS_PREFERENCE, v))
  watch(lightTheme, (v) => localStorage.setItem(LS_LIGHT, v))
  watch(darkTheme, (v) => localStorage.setItem(LS_DARK, v))

  return {
    preference, lightTheme, darkTheme, systemDark,
    discovered, themes, themeIds, activeId, active, isDark, isAuto,
    init, apply, setPreference, setSchemeDefault, toggle, refresh,
    setWsConnected // 供 app store 在 WebSocket 状态变化时调用
  }
})
