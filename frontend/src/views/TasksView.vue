<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import StateTag from '@/components/StateTag.vue'
import { taskApi } from '@/api'
import { useAppStore } from '@/stores/app'
import { useDetailStore } from '@/stores/detail'
import { fmtRuntime, fmtTime, truncate } from '@/utils/format'

const store = useAppStore()
const route = useRoute()
const router = useRouter()
const detail = useDetailStore()

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const autoRefresh = ref(true)
let timer = null

const query = reactive({
  limit: 20,
  offset: 0,
  workername: '',
  taskname: '',
  state: '',
  search: '',
  sort_by: '-received',
  received_range: null,
  root_id: route.query.root_id || '',
  parent_id: route.query.parent_id || ''
})

const page = computed({
  get: () => Math.floor(query.offset / query.limit) + 1,
  set: (v) => (query.offset = (v - 1) * query.limit)
})

function buildParams() {
  const p = {
    limit: query.limit,
    offset: query.offset,
    sort_by: query.sort_by
  }
  if (query.workername) p.workername = query.workername
  if (query.taskname) p.taskname = query.taskname
  if (query.state) p.state = query.state
  if (query.search?.trim()) p.search = query.search.trim()
  if (query.root_id) p.root_id = query.root_id
  if (query.parent_id) p.parent_id = query.parent_id
  if (query.received_range?.length === 2) {
    p.received_start = query.received_range[0]
    p.received_end = query.received_range[1]
  }
  return p
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const res = await taskApi.table(buildParams())
    rows.value = res.data || []
    total.value = res.total || 0
  } catch (err) {
    if (!silent) ElMessage.error(err?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

function reset() {
  Object.assign(query, {
    offset: 0, workername: '', taskname: '', state: '',
    search: '', received_range: null, root_id: '', parent_id: ''
  })
  router.replace({ query: {} })
  load()
}

function onSort({ prop, order }) {
  if (!order) {
    query.sort_by = '-received'
  } else {
    query.sort_by = (order === 'ascending' ? '' : '-') + prop
  }
  query.offset = 0
  load()
}

/* ------------------------- 任务操作 ------------------------- */
async function revoke(row, terminate) {
  const text = terminate
    ? `强制终止任务 ${row.uuid}？将向执行进程发送 SIGTERM。`
    : `撤销任务 ${row.uuid}？未开始执行的任务将被丢弃。`
  const ok = await ElMessageBox.confirm(text, terminate ? '确认终止' : '确认撤销', {
    type: 'warning'
  }).catch(() => false)
  if (!ok) return
  try {
    const res = await taskApi.revoke(row.uuid, terminate)
    ElMessage.success(res?.message || '操作成功')
    setTimeout(() => load(true), 400)
  } catch (err) {
    ElMessage.error(err?.message || '操作失败')
  }
}

const searchTips = [
  'result:success — 按结果内容匹配',
  'args:user_id — 按位置参数匹配',
  'kwargs:template=welcome — 按关键字参数匹配',
  'state:FAILURE — 按状态匹配',
  '直接输入文本则匹配任务 ID / 名称'
]

watch(() => [query.limit], () => { query.offset = 0; load() })

onMounted(async () => {
  if (!store.filters.task_types?.length) await store.loadFilters()
  await load()
  timer = setInterval(() => autoRefresh.value && load(true), 5000)
})

onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="page">
    <div class="panel mb">
      <div class="filters">
        <el-select v-model="query.state" placeholder="全部状态" clearable style="width: 138px"
          @change="query.offset = 0; load()">
          <el-option v-for="s in store.filters.states" :key="s" :label="s" :value="s" />
        </el-select>

        <el-select v-model="query.taskname" placeholder="全部任务类型" clearable filterable style="width: 230px"
          @change="query.offset = 0; load()">
          <el-option v-for="t in store.filters.task_types" :key="t" :label="t" :value="t" />
        </el-select>

        <el-select v-model="query.workername" placeholder="全部 Worker" clearable filterable style="width: 190px"
          @change="query.offset = 0; load()">
          <el-option v-for="w in store.filters.workers" :key="w" :label="w" :value="w" />
        </el-select>

        <el-date-picker v-model="query.received_range" type="datetimerange" range-separator="→"
          start-placeholder="接收起" end-placeholder="接收止" value-format="YYYY-MM-DD HH:mm"
          format="MM-DD HH:mm" style="width: 300px" @change="query.offset = 0; load()" />

        <el-tooltip placement="bottom-start">
          <template #content>
            <div style="line-height: 1.8">
              <div v-for="t in searchTips" :key="t">{{ t }}</div>
            </div>
          </template>
          <el-input v-model="query.search" placeholder="搜索：result: / args: / kwargs: / state:"
            clearable style="width: 300px" :prefix-icon="'Search'"
            @keyup.enter="query.offset = 0; load()" @clear="query.offset = 0; load()" />
        </el-tooltip>

        <el-button type="primary" :icon="'Search'" @click="query.offset = 0; load()">查询</el-button>
        <el-button :icon="'RefreshLeft'" @click="reset">重置</el-button>

        <div class="grow" />
        <el-checkbox v-model="autoRefresh">自动刷新</el-checkbox>
      </div>

      <div v-if="query.root_id || query.parent_id" class="chain-tip">
        <el-tag type="warning" size="small" closable @close="reset">
          {{ query.root_id ? `调用链 root=${query.root_id.slice(0, 12)}…`
            : `子任务 parent=${query.parent_id.slice(0, 12)}…` }}
        </el-tag>
      </div>
    </div>

    <div class="panel">
      <el-table v-loading="loading" :data="rows" size="small" stripe @sort-change="onSort"
        :default-sort="{ prop: 'received', order: 'descending' }">
        <el-table-column prop="uuid" label="任务 ID" width="132" fixed>
          <template #default="{ row }">
            <span class="link mono" @click="detail.openTask(row.uuid)">
              {{ row.uuid.slice(0, 8) }}…
            </span>
          </template>
        </el-table-column>

        <el-table-column prop="name" label="任务名" min-width="210" show-overflow-tooltip sortable="custom">
          <template #default="{ row }">
            <span class="mono">{{ row.name || '-' }}</span>
          </template>
        </el-table-column>

        <el-table-column prop="state" label="状态" width="102" align="center" sortable="custom">
          <template #default="{ row }"><StateTag :state="row.state" /></template>
        </el-table-column>

        <el-table-column label="参数" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="mono text-muted args">
              {{ truncate(row.args, 40) }}{{ row.kwargs && row.kwargs !== '{}' ? ' ' + truncate(row.kwargs, 30) : '' }}
            </span>
          </template>
        </el-table-column>

        <el-table-column prop="received" label="接收时间" width="162" sortable="custom">
          <template #default="{ row }">
            <span class="mono" style="font-size: 12px">{{ fmtTime(row.received) }}</span>
          </template>
        </el-table-column>

        <el-table-column prop="runtime" label="耗时" width="96" align="right" sortable="custom">
          <template #default="{ row }">
            <span class="mono" style="font-size: 12px">{{ fmtRuntime(row.runtime) }}</span>
          </template>
        </el-table-column>

        <el-table-column prop="worker" label="Worker" width="150" show-overflow-tooltip sortable="custom">
          <template #default="{ row }">
            <span v-if="row.worker" class="link mono"
              @click="detail.openWorker(row.worker)">{{ row.worker }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>

        <el-table-column label="结果 / 异常" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.exception" class="mono bad">{{ truncate(row.exception, 50) }}</span>
            <span v-else class="mono text-muted">{{ truncate(row.result, 50) }}</span>
          </template>
        </el-table-column>

        <el-table-column prop="retries" label="重试" width="70" align="right" />

        <el-table-column label="操作" width="150" fixed="right" align="center">
          <template #default="{ row }">
            <el-button text size="small" type="primary" @click="detail.openTask(row.uuid)">
              详情
            </el-button>
            <el-button text size="small" type="warning" @click="revoke(row, false)">撤销</el-button>
            <el-button text size="small" type="danger" @click="revoke(row, true)">终止</el-button>
          </template>
        </el-table-column>

        <template #empty><el-empty description="没有匹配的任务" :image-size="80" /></template>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="query.limit"
          :page-sizes="[10, 20, 50, 100, 200]"
          :total="total"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @current-change="load()"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
}

.chain-tip {
  padding: 0 16px 12px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  padding: 12px 16px;
  border-top: 1px solid var(--fu-border);
}

.args {
  font-size: 12px;
}

.bad {
  color: var(--el-color-danger);
  font-size: 12px;
}
</style>
