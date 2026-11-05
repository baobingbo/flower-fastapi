
<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { userApi } from '@/api'
import { useAppStore } from '@/stores/app'

defineOptions({ name: 'MyAccountView' })

const store = useAppStore()
const oldPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const loading = ref(false)

async function changePassword() {
  if (newPassword.value !== confirmPassword.value) {
    ElMessage.error('两次输入的新密码不一致')
    return
  }
  if (newPassword.value.length < 8) {
    ElMessage.warning('密码长度至少8位')
    return
  }
  loading.value = true
  try {
    await userApi.changePassword(oldPassword.value, newPassword.value)
    ElMessage.success('密码已修改，所有会话已失效')
    oldPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || err.message || '修改失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="page">
    <h3>我的账户</h3>
    <el-descriptions :column="2" border>
      <el-descriptions-item label="用户名">{{ store.user || '未登录' }}</el-descriptions-item>
      <el-descriptions-item label="角色">
        <el-tag>{{ store.userRole || 'viewer' }}</el-tag>
      </el-descriptions-item>
    </el-descriptions>
    
    <el-divider />
    
    <h4>修改密码</h4>
    <el-form @submit.prevent="changePassword" max-width="400px">
      <el-form-item label="旧密码">
        <el-input v-model="oldPassword" type="password" show-password />
      </el-form-item>
      <el-form-item label="新密码">
        <el-input v-model="newPassword" type="password" show-password placeholder="至少8位" />
      </el-form-item>
      <el-form-item label="确认密码">
        <el-input v-model="confirmPassword" type="password" show-password />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="loading" @click="changePassword">
          修改密码
        </el-button>
      </el-form-item>
    </el-form>
  </div>
</template>
