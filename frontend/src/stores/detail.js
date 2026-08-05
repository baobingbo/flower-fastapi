import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

/**
 * 全局「查看详情」悬浮层状态。
 * 任何页面（列表、Dashboard、下发任务、甚至详情页内部互链）都能触发，
 * 由 <DetailOverlay> 统一渲染一个 el-drawer 承载详情内容，避免跳转到独立路由页。
 */
export const useDetailStore = defineStore('detail', () => {
  // type: 'worker' | 'task' | null
  const type = ref(null)
  const id = ref('')

  /** 可写：el-drawer 关闭时把 type 置空，从而驱动 v-model 收起 */
  const visible = computed({
    get: () => type.value !== null,
    set: (v) => {
      if (!v) close()
    }
  })

  const title = computed(() => {
    if (type.value === 'worker') return `Worker · ${id.value}`
    if (type.value === 'task') return `任务详情 · ${id.value}`
    return ''
  })

  function openWorker(name) {
    type.value = 'worker'
    id.value = name
  }

  function openTask(taskId) {
    type.value = 'task'
    id.value = taskId
  }

  function open(t, value) {
    type.value = t
    id.value = value
  }

  function close() {
    type.value = null
    id.value = ''
  }

  return { type, id, visible, title, openWorker, openTask, open, close }
})
