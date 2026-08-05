<script setup>
import { useDetailStore } from '@/stores/detail'
import WorkerDetail from '@/views/WorkerDetailView.vue'
import TaskDetail from '@/views/TaskDetailView.vue'

const detail = useDetailStore()
</script>

<template>
  <el-drawer
    v-model="detail.visible"
    :title="detail.title"
    :size="detail.type === 'worker' ? '58%' : '50%'"
    :with-header="true"
    destroy-on-close
    class="fu-detail-drawer"
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
</style>
