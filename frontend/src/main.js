import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import 'element-plus/dist/index.css'
// 模块化样式入口（tokens / themes / vendor / base / components / utilities）
import '@/styles/index.css'

import App from './App.vue'
import router from './router'
import { DEFAULT_DARK_THEME, DEFAULT_LIGHT_THEME, THEME_IDS, applyTheme } from '@/theme/registry'

/**
 * 首屏防闪烁：在 Vue 挂载之前就把主题写到 <html> 上。
 * 若不这样做，页面会先按默认浅色渲染一帧再切到深色。
 */
;(function bootstrapTheme() {
  // 优先用上次生效主题的完整对象重建（含远程主题的 url / scheme / glass）
  const raw = localStorage.getItem('flower_theme_obj')
  if (raw) {
    try {
      const obj = JSON.parse(raw)
      if (obj && obj.id) {
        applyTheme(obj)
        return
      }
    } catch {
      /* 解析失败则走下面的兜底逻辑 */
    }
  }
  const pref = localStorage.getItem('flower_theme') || 'auto'
  if (pref !== 'auto' && THEME_IDS.includes(pref)) {
    applyTheme(pref)
    return
  }
  const dark = window.matchMedia?.('(prefers-color-scheme: dark)').matches
  const fallback = dark
    ? localStorage.getItem('flower_theme_dark') || DEFAULT_DARK_THEME
    : localStorage.getItem('flower_theme_light') || DEFAULT_LIGHT_THEME
  applyTheme(fallback)
})()

const app = createApp(App)

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })
app.mount('#app')
