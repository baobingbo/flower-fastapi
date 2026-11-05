<template>
  <div class="beat-view">
    <div class="beat-header">
      <h2>Beat 管理</h2>
      <el-button type="primary" @click="openAddDialog">
        <el-icon><Plus /></el-icon>
        新增 Beat
      </el-button>
    </div>

    <el-table :data="beats" v-loading="loading" style="width: 100%">
      <el-table-column prop="name" label="名称" width="180" />
      <el-table-column prop="task" label="任务" min-width="200" />
      <el-table-column prop="schedule" label="调度" width="150" />
      <el-table-column prop="args" label="参数" width="150">
        <template #default="{ row }">
          <span class="args-text">{{ JSON.stringify(row.args) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="kwargs" label="关键字参数" width="150">
        <template #default="{ row }">
          <span class="kwargs-text">{{ JSON.stringify(row.kwargs) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openEditDialog(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && beats.length === 0" description="暂无 Beat 调度任务" />

    <!-- 新增/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑 Beat' : '新增 Beat'"
      width="500px"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" :disabled="isEdit" placeholder="请输入 Beat 名称" />
        </el-form-item>
        <el-form-item label="任务" prop="task">
          <el-select
            v-model="form.task"
            filterable
            allow-create
            placeholder="选择或输入任务名"
            style="width: 100%"
          >
            <el-option
              v-for="t in registeredTasks"
              :key="t.name"
              :label="t.name"
              :value="t.name"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="调度">
          <el-input v-model="form.schedule" placeholder="如：0 0 * * * 或 30s" />
        </el-form-item>
        <el-form-item label="参数">
          <el-input v-model="form.argsStr" type="textarea" :rows="3" placeholder='["arg1", "arg2"]' />
        </el-form-item>
        <el-form-item label="关键字参数">
          <el-input v-model="form.kwargsStr" type="textarea" :rows="3" placeholder='{"key": "value"}' />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit" :loading="submitting">
          确定
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { taskApi } from '@/api'

const loading = ref(false)
const beats = ref([])
const registeredTasks = ref([])
const dialogVisible = ref(false)
const isEdit = ref(false)
const submitting = ref(false)
const formRef = ref(null)

const form = ref({
  name: '',
  task: '',
  schedule: '',
  argsStr: '[]',
  kwargsStr: '{}'
})

const rules = {
  name: [{ required: true, message: '请输入 Beat 名称', trigger: 'blur' }],
  task: [{ required: true, message: '请选择或输入任务名', trigger: 'change' }]
}

async function fetchBeats() {
  try {
    loading.value = true
    const response = await fetch('/api/beats')
    const data = await response.json()
    beats.value = data.beats || []
  } catch (error) {
    console.error('获取 Beat 列表失败:', error)
    ElMessage.error('获取 Beat 列表失败')
  } finally {
    loading.value = false
  }
}

async function fetchRegisteredTasks() {
  try {
    const data = await taskApi.registered()
    registeredTasks.value = data || []
  } catch (error) {
    console.error('获取已注册任务失败:', error)
  }
}

function openAddDialog() {
  isEdit.value = false
  form.value = {
    name: '',
    task: '',
    schedule: '',
    argsStr: '[]',
    kwargsStr: '{}'
  }
  dialogVisible.value = true
}

function openEditDialog(row) {
  isEdit.value = true
  form.value = {
    name: row.name,
    task: row.task,
    schedule: row.schedule,
    argsStr: JSON.stringify(row.args || []),
    kwargsStr: JSON.stringify(row.kwargs || {})
  }
  dialogVisible.value = true
}

async function handleSubmit() {
  try {
    await formRef.value.validate()
    submitting.value = true
    
    const payload = {
      name: form.value.name,
      task: form.value.task,
      schedule: form.value.schedule || null,
      args: JSON.parse(form.value.argsStr || '[]'),
      kwargs: JSON.parse(form.value.kwargsStr || '{}'),
      options: {}
    }
    
    const url = isEdit.value ? '/api/beats/' + encodeURIComponent(form.value.name) : '/api/beats'
    const method = isEdit.value ? 'PUT' : 'POST'
    
    const response = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    
    if (!response.ok) {
      throw new Error('操作失败')
    }
    
    ElMessage.success(isEdit.value ? 'Beat 已更新' : 'Beat 已创建')
    dialogVisible.value = false
    await fetchBeats()
  } catch (error) {
    console.error('提交失败:', error)
    ElMessage.error('操作失败')
  } finally {
    submitting.value = false
  }
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      '确定要删除 Beat ' + row.name + ' 吗？',
      '确认删除',
      { type: 'warning' }
    )
    
    const response = await fetch('/api/beats/' + encodeURIComponent(row.name), {
      method: 'DELETE'
    })
    
    if (!response.ok) {
      throw new Error('删除失败')
    }
    
    ElMessage.success('Beat 已删除')
    await fetchBeats()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除失败:', error)
      ElMessage.error('删除失败')
    }
  }
}

onMounted(async () => {
  await Promise.all([fetchBeats(), fetchRegisteredTasks()])
})
</script>

<style scoped>
.beat-view {
  padding: 16px;
}

.beat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.beat-header h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
}

.args-text, .kwargs-text {
  font-family: monospace;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
