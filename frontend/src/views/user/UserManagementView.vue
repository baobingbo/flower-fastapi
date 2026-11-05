
<script setup>
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import LoginLogsView from './LoginLogsView.vue'
import AccountsView from './AccountsView.vue'
import MyAccountView from './MyAccountView.vue'
import LoginSettingsView from './LoginSettingsView.vue'
import SessionsView from './SessionsView.vue'

defineOptions({ name: 'UserManagementView' })

const route = useRoute()
const activeTab = ref(route.path.split('/').pop() || 'accounts')
</script>

<template>
  <div class="page">
    <h2 class="page-title">用户管理</h2>
    <el-tabs v-model="activeTab" class="user-mgmt-tabs">
      <el-tab-pane label="用户列表" name="accounts">
        <AccountsView />
      </el-tab-pane>
      <el-tab-pane label="我的账户" name="my-account">
        <MyAccountView />
      </el-tab-pane>
      <el-tab-pane label="登录记录" name="login-logs">
        <LoginLogsView />
      </el-tab-pane>
      <el-tab-pane label="会话管理" name="sessions">
        <SessionsView />
      </el-tab-pane>
      <el-tab-pane label="登录设置" name="settings">
        <LoginSettingsView />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.user-mgmt-tabs {
  background: var(--fu-surface);
  border-radius: var(--fu-radius);
  padding: 16px;
}
</style>
