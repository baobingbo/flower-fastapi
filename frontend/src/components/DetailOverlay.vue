<script setup>
import { computed } from 'vue'
import { useDetailStore } from '@/stores/detail'
import WorkerDetail from '@/views/WorkerDetailView.vue'
import TaskDetail from '@/views/TaskDetailView.vue'

const detail = useDetailStore()

const isMobile = computed(() => window.innerWidth < 900)

// 监听窗口大小变化
import { onMounted, onUnmounted } from 'vue'
const updateMobile = () => {
  // 强制更新响应式
}
onMounted(() => {
  window.addEventListener('resize', updateMobile)
})
onUnmounted(() => {
  window.removeEventListener('resize', updateMobile)
})
</script>

<template>
  <el-drawer
    v-model="detail.visible"
    :title="detail.title"
    :size="detail.type === 'worker' ? '58%' : '50%'"
    :with-header="true"
    destroy-on-close
    class="fu-detail-drawer"
    :class="{ 'mobile-full': isMobile }"
  >
    <div class="detail-body">
      <WorkerDetail
        v-if="detail.type === 'worker'"
        :name="detail.id"
        @open-task="detail.openTask"
        @open-worker="detail.openWorker"
      />
      <TaskDetail
        v-else-if="detail.type === 'task'"
        :id="detail.id"
        @open-task="detail.openTask"
        @open-worker="detail.openWorker"
      />
    </div>
  </el-drawer>
</template>

<style scoped>
.detail-body {
  padding: 0 6px 8px;
}

/* 移动端全屏抽屉 */
.fu-detail-drawer.mobile-full {
  width: 100% !important;
}

@media (max-width: 900px) {
  :deep(.el-drawer) {
    width: 100% !important;
  }
}
</style>
