/**
 * 主题注册表
 * ------------------------------------------------------------------
 * 内置主题在此硬编码（打包进 bundle，始终可用，作为离线兜底）。
 * 运行时从后端主题目录发现的「用户主题」由 useThemeStore 动态合并，
 * 其 CSS 由后端按文件提供（/api/themes/files/<id>.css），applyTheme 会注入 <link>。
 * 新增内置主题：在 THEMES 追加一项 + 在 src/styles/themes/ 加 css 即可。
 */

export const THEMES = [
  {
    id: 'light',
    name: '浅色',
    desc: '干净克制的浅灰蓝底，长时间看表格不累',
    scheme: 'light',
    glass: false,
    swatch: ['#f4f6fa', '#ffffff', '#3f7ef8']
  },
  {
    id: 'dark',
    name: '深色',
    desc: '中性冷灰底，夜间与暗色工作台首选',
    scheme: 'dark',
    glass: false,
    swatch: ['#14161c', '#1a1d25', '#5b93ff']
  }
]

/**
 * 注意：tech-liquid / aurora 已迁移到主题目录（themes/），
 * 不再打包进 bundle，而是由后端扫描并以 <link> 注入（见 useThemeStore.discovered）。
 * 源码内置主题仅保留 light / dark 作为离线兜底。
 */

/** 运行时从后端 /api/themes 发现、由主题目录扫描得到的用户主题 */
export const BUILTIN_IDS = new Set(THEMES.map((t) => t.id))

/** 用户主题 CSS 的基址（后端以静态方式提供） */
export const THEME_CSS_BASE = '/api/themes/files'

export const THEME_IDS = THEMES.map((t) => t.id)

/** 跟随系统时，深/浅两种系统偏好各自对应的默认主题 */
export const DEFAULT_LIGHT_THEME = 'light'
export const DEFAULT_DARK_THEME = 'dark'

export function getTheme(id) {
  return THEMES.find((t) => t.id === id) || THEMES[0]
}

export function themesByScheme(scheme) {
  return THEMES.filter((t) => t.scheme === scheme)
}

/**
 * 确保某个（用户）主题的 CSS 已通过 <link> 注入页面。
 * 内置主题打包在 bundle 中无需注入；用户主题由后端按文件提供。
 */
export function ensureThemeCss(theme) {
  if (!theme || !theme.remote || !theme.url) return
  const id = `fu-theme-${theme.id}`
  let link = document.getElementById(id)
  if (!link) {
    link = document.createElement('link')
    link.id = id
    link.rel = 'stylesheet'
    link.dataset.fuTheme = theme.id
    document.head.appendChild(link)
  }
  if (link.getAttribute('href') !== theme.url) link.href = theme.url
}

/**
 * 收拢页面上注入的远程主题 <link>：
 * 只保留「当前生效远程主题」对应的那张，其余全部移除。
 *
 * 必须为切换回内置主题（或切到别的远程主题）时清掉残留 link——
 * 否则旧的远程 CSS（含 base.css 的 :root 默认值）会靠"后加载"
 * 盖过内置主题的令牌，导致"切回内置主题必须刷新才生效"的 bug。
 */
export function reconcileThemeLinks(theme) {
  const keepId = theme.remote && theme.url ? `fu-theme-${theme.id}` : null
  document.querySelectorAll('link[data-fu-theme]').forEach((link) => {
    if (link.id !== keepId) link.remove()
  })
  if (keepId) ensureThemeCss(theme)
}

/**
 * 把主题应用到 document。
 * - data-theme      驱动令牌（内置走 bundle，用户主题走注入的 <link>）
 * - data-glass      驱动 themes/_glass.css 的液态玻璃增强
 * - .dark           兼容少数按 class 判断暗色的第三方组件
 * - color-scheme    让浏览器原生控件（滚动条/输入框）也跟随
 *
 * @param {string|object} idOrObj 主题 id（内置）或主题对象（含 scheme/glass/remote/url）
 */
export function applyTheme(idOrObj, opts = {}) {
  const theme = typeof idOrObj === 'string' ? getTheme(idOrObj) : idOrObj
  const root = document.documentElement

  root.dataset.theme = theme.id
  root.dataset.glass = theme.glass ? 'on' : 'off'
  root.classList.toggle('dark', theme.scheme === 'dark')
  root.style.colorScheme = theme.scheme

  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', (theme.swatch && theme.swatch[0]) || '#000000')

  // 用户主题：注入其 CSS 文件，并清掉其它残留的远程主题 <link>
  reconcileThemeLinks(theme)

  return theme
}
