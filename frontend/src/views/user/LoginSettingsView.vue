<script setup>
import { ref } from 'vue'

defineOptions({ name: 'LoginSettingsView' })

const settings = ref({
  password_min_length: 8,
  password_require_upper: false,
  password_require_digit: false,
  password_require_special: false
})

async function save() {
  // TODO: 调用后端API保存设置
}
</script>

<template>
  <div class="page">
    <h3>登录设置</h3>
    <el-form>
      <el-form-item label="密码最小长度">
        <el-input-number v-model="settings.password_min_length" :min="1" :max="32" />
      </el-form-item>
      <el-form-item label="要求大写字母">
        <el-switch v-model="settings.password_require_upper" />
      </el-form-item>
      <el-form-item label="要求数字">
        <el-switch v-model="settings.password_require_digit" />
      </el-form-item>
      <el-form-item label="要求特殊字符">
        <el-switch v-model="settings.password_require_special" />
      </el-form-item>
      <el-button type="primary" @click="save">保存设置</el-button>
    </el-form>
  </div>
</template>
