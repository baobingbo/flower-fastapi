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
    if (preference.value !== 'auto') return preference.value
    return systemDark.value ? darkTheme.value : lightTheme.value
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

  let timer = null
  function startPolling() {
    if (timer) return
    timer = setInterval(refresh, REFRESH_MS)
  }

  /** 监听系统主题变化——这是"默认跟随系统"的关键 */
  let mql = null
  function initSystemWatcher() {
    mql = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!mql) return
    const onChange = (e) => (systemDark.value = e.matches)
    if (mql.addEventListener) mql.addEventListener('change', onChange)
    else mql.addListener(onChange)
  }

  async function init() {
    initSystemWatcher()
    await refresh() // 拉取目录中的用户主题
    startPolling() // 持续监控目录变化
    apply() // 应用并持久化当前生效主题
  }

  watch(activeId, apply)
  watch(preference, (v) => localStorage.setItem(LS_PREFERENCE, v))
  watch(lightTheme, (v) => localStorage.setItem(LS_LIGHT, v))
  watch(darkTheme, (v) => localStorage.setItem(LS_DARK, v))

  return {
    preference, lightTheme, darkTheme, systemDark,
    discovered, themes, themeIds, activeId, active, isDark, isAuto,
    init, apply, setPreference, setSchemeDefault, toggle, refresh
  }
})
