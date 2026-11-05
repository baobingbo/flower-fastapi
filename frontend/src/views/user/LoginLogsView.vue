<script setup>
import { ref, onMounted } from 'vue'

defineOptions({ name: 'LoginLogsView' })

const logs = ref([])
const loading = ref(false)

async function loadLogs() {
  loading.value = true
  try {
    // TODO: 调用后端API
  } finally {
    loading.value = false
  }
}

onMounted(loadLogs)
</script>

<template>
  <div class="page">
    <h3>登录记录</h3>
    <el-table :data="logs" v-loading="loading">
      <el-table-column prop="ts" label="时间" />
      <el-table-column prop="user" label="用户" />
      <el-table-column prop="ip" label="IP" />
      <el-table-column prop="result" label="结果" />
    </el-table>
  </div>
</template>