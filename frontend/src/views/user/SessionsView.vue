<script setup>
import { ref, onMounted } from 'vue'

defineOptions({ name: 'SessionsView' })

const sessions = ref([])
const loading = ref(false)

async function loadSessions() {
  loading.value = true
  try {
    // TODO: 调用后端API
  } finally {
    loading.value = false
  }
}

onMounted(loadSessions)
</script>

<template>
  <div class="page">
    <h3>会话管理</h3>
    <el-table :data="sessions" v-loading="loading">
      <el-table-column prop="jti" label="Token ID" />
      <el-table-column prop="issued_at" label="颁发时间" />
      <el-table-column prop="exp" label="过期时间" />
      <el-table-column prop="ip" label="IP" />
      <el-table-column label="操作">
        <el-button size="small" type="danger">撤销</el-button>
      </el-table-column>
    </el-table>
  </div>
</template>