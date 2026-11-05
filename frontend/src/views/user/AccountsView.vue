<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { usersApi, rolesApi } from '@/api'
import { useAppStore } from '@/stores/app'

defineOptions({ name: 'AccountsView' })

const store = useAppStore()
const users = ref([])
const roles = ref([])
const loading = ref(false)
const showAddDialog = ref(false)
const newUser = ref({ username: '', password: '', role: 'viewer', email: '' })

const hasPermission = computed(() => {
  return store.userPermissions.includes('user.manage')
})

async function loadUsers() {
  loading.value = true
  try {
    const res = await usersApi.list()
    users.value = res || []
  } catch (err) {
    ElMessage.error(err.message || '加载用户列表失败')
  } finally {
    loading.value = false
  }
}

async function loadRoles() {
  try {
    const res = await rolesApi.list()
    roles.value = res || []
  } catch (err) {
    console.error('加载角色失败', err)
  }
}

async function addUser() {
  if (!newUser.value.username) {
    ElMessage.warning('请输入用户名')
    return
  }
  try {
    await usersApi.create(newUser.value)
    ElMessage.success('用户创建成功')
    showAddDialog.value = false
    newUser.value = { username: '', password: '', role: 'viewer', email: '' }
    await loadUsers()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '创建失败')
  }
}

async function deleteUser(username) {
  try {
    await ElMessageBox.confirm('确定要删除用户「' + username + '」吗？', '确认删除', { type: 'warning' })
    await usersApi.delete(username)
    ElMessage.success('用户已删除')
    await loadUsers()
  } catch (err) {
    if (err !== 'cancel') {
      ElMessage.error(err.response?.data?.detail || '删除失败')
    }
  }
}

onMounted(async () => {
  await Promise.all([loadUsers(), loadRoles()])
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h3>用户列表</h3>
      <el-button v-if="hasPermission" type="primary" @click="showAddDialog = true">
        <el-icon><Plus /></el-icon> 新增用户
      </el-button>
    </div>
    
    <el-table v-loading="loading" :data="users" stripe>
      <el-table-column prop="username" label="用户名" width="150" />
      <el-table-column prop="role" label="角色" width="120">
        <template #default="{ row }">
          <el-tag size="small">{{ row.role }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="email" label="邮箱" width="200" />
      <el-table-column prop="is_active" label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '启用' : '禁用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" v-if="hasPermission">
        <template #default="{ row }">
          <el-button size="small" @click="deleteUser(row.username)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    
    <el-dialog v-model="showAddDialog" title="新增用户" width="400px">
      <el-form :model="newUser" label-width="80px">
        <el-form-item label="用户名">
          <el-input v-model="newUser.username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="newUser.password" type="password" show-password />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="newUser.role" style="width: 100%">
            <el-option v-for="r in roles" :key="r.name" :label="r.name" :value="r.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="newUser.email" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" @click="addUser">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
</style>
