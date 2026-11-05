<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { dashboardApi } from '@/api'
import { useAppStore } from '@/stores/app'
import { fmtUptime } from '@/utils/format'

const store = useAppStore()
const sys = ref({})

const API_GROUPS = [
  {
    title: 'Worker 监控',
    items: [
      ['GET', '/api/workers', '全部 worker 快照（对齐 flower）'],
      ['GET', '/api/workers/table', '表格视图聚合数据'],
      ['GET', '/api/worker/{name}', 'worker 详情：pool / 队列 / 配置 / rusage']
    ]
  },
  {
    title: 'Worker 控制',
    items: [
      ['POST', '/api/worker/shutdown/{name}', '关闭节点'],
      ['POST', '/api/worker/pool/restart/{name}', '重启进程池'],
      ['POST', '/api/worker/pool/grow/{name}?n=', '进程池扩容'],
      ['POST', '/api/worker/pool/shrink/{name}?n=', '进程池缩容'],
      ['POST', '/api/worker/pool/autoscale/{name}?min=&max=', '自动伸缩'],
      ['POST', '/api/worker/queue/add-consumer/{name}?queue=', '新增消费队列'],
      ['POST', '/api/worker/queue/cancel-consumer/{name}?queue=', '取消消费队列']
    ]
  },
  {
    title: '任务查询',
    items: [
      ['GET', '/api/tasks', '任务映射（对齐 flower）'],
      ['GET', '/api/tasks/table', '分页表格 + 搜索 DSL'],
      ['GET', '/api/task/info/{id}', '任务详情 + 子任务链'],
      ['GET', '/api/task/types', '已出现的任务类型'],
      ['GET', '/api/task/registered', 'worker 注册任务列表'],
      ['GET', '/api/queues/length', '队列长度']
    ]
  },
  {
    title: '任务控制与下发',
    items: [
      ['POST', '/api/task/apply/{name}', '同步执行并等待结果'],
      ['POST', '/api/task/async-apply/{name}', '异步下发'],
      ['POST', '/api/task/send-task/{name}', '按名称投递'],
      ['GET', '/api/task/result/{id}', '获取结果'],
      ['POST', '/api/task/revoke/{id}?terminate=', '撤销 / 终止'],
      ['POST', '/api/task/abort/{id}', '中止 AbortableTask'],
      ['POST', '/api/task/rate-limit/{name}?workername=&ratelimit=', '限流'],
      ['POST', '/api/task/timeout/{name}?workername=&soft=&hard=', '超时设置']
    ]
  },
  {
    title: '运维与实时',
    items: [
      ['GET', '/metrics', 'Prometheus 指标'],
      ['GET', '/healthcheck', '健康检查'],
      ['GET', '/api/broker', 'Broker 队列概览'],
      ['GET', '/api/dashboard/summary', '总览聚合'],
      ['GET', '/api/dashboard/timeline', '时间线采样'],
      ['WS', '/ws/events', '实时事件推送']
    ]
  }
]

const METHOD_TYPE = { GET: 'success', POST: 'warning', WS: 'primary' }

onMounted(async () => {
  sys.value = await dashboardApi.system().catch((err) => {
    ElMessage.error(err?.message || '系统信息加载失败')
    return {}
  })
})
</script>

<template>
  <div class="page">
    <el-row :gutter="14" class="mb">
      <el-col :xs="24" :lg="12">
        <div class="panel" style="height: 100%">
          <div class="panel-head"><span class="panel-title">运行环境</span></div>
          <el-descriptions :column="1" border size="small" class="desc">
            <el-descriptions-item label="运行模式">
              <el-tag :type="sys.mock_mode ? 'warning' : 'success'" size="small">
                {{ sys.mock_mode ? '演示模式（内置模拟集群）' : '生产模式（真实 Broker）' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="Broker URL">
              <span class="mono">{{ sys.broker_url || '-' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="传输协议">
              <span class="mono">{{ sys.transport || '-' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="服务运行时长">
              {{ fmtUptime(sys.uptime) }}
            </el-descriptions-item>
            <el-descriptions-item label="Python 版本">
              <span class="mono">{{ sys.python_version || '-' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="Celery 版本">
              <span class="mono">{{ sys.celery_version || '-' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="平台">
              <span class="mono">{{ sys.platform || '-' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="内存中的 Worker">
              {{ sys.workers_in_memory ?? '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="内存中的任务">
              {{ sys.tasks_in_memory ?? '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="鉴权">
              {{ store.authEnabled ? `已启用（当前用户 ${store.user}）` : '未启用' }}
            </el-descriptions-item>
          </el-descriptions>
        </div>
      </el-col>

      <el-col :xs="24" :lg="12">
        <div class="panel" style="height: 100%">
          <div class="panel-head"><span class="panel-title">快捷入口</span></div>
          <div class="links">
            <a class="link-card" href="/docs" target="_blank">
              <el-icon :size="20" color="var(--fu-brand, #409eff)"><Document /></el-icon>
              <div>
                <div class="lc-title">Swagger API 文档</div>
                <div class="lc-sub">/docs — 交互式接口调试</div>
              </div>
            </a>
            <a class="link-card" href="/redoc" target="_blank">
              <el-icon :size="20" color="var(--fu-chart-5, #9254de)"><Reading /></el-icon>
              <div>
                <div class="lc-title">ReDoc 文档</div>
                <div class="lc-sub">/redoc — 结构化接口说明</div>
              </div>
            </a>
            <a class="link-card" href="/metrics" target="_blank">
              <el-icon :size="20" color="var(--fu-warning, #e6a23c)"><TrendCharts /></el-icon>
              <div>
                <div class="lc-title">Prometheus 指标</div>
                <div class="lc-sub">/metrics — 对齐 flower 全量指标集</div>
              </div>
            </a>
            <a class="link-card" href="/healthcheck" target="_blank">
              <el-icon :size="20" color="var(--fu-success, #67c23a)"><CircleCheck /></el-icon>
              <div>
                <div class="lc-title">健康检查</div>
                <div class="lc-sub">/healthcheck — 存活探针</div>
              </div>
            </a>
          </div>

          <div class="panel-head" style="border-top: 1px solid var(--fu-border)">
            <span class="panel-title">WebSocket 实时通道</span>
          </div>
          <div class="ws-box">
            <div class="ws-row">
              <span class="dot" :class="store.connected ? 'on' : 'off'" />
              <span>{{ store.connected ? '已连接' : '未连接' }}</span>
              <span class="mono text-muted">/ws/events</span>
            </div>
            <div class="text-muted ws-tip">
              推送 snapshot（初始快照）、summary（总览刷新）、timeline（采样点）、event（原始 Celery 事件）
              四类消息，支持 ping/pong 保活与断线自动重连。
            </div>
          </div>
        </div>
      </el-col>
    </el-row>

    <div class="panel">
      <div class="panel-head">
        <span class="panel-title">API 能力清单</span>
        <span class="text-muted panel-sub">全量对齐 Flower 2.0.1 的功能点</span>
      </div>
      <div class="api-groups">
        <div v-for="g in API_GROUPS" :key="g.title" class="api-group">
          <div class="ag-title">{{ g.title }}</div>
          <div v-for="(it, i) in g.items" :key="i" class="ag-row">
            <el-tag :type="METHOD_TYPE[it[0]]" size="small" effect="plain" class="method">
              {{ it[0] }}
            </el-tag>
            <span class="mono path">{{ it[1] }}</span>
            <span class="text-muted note">{{ it[2] }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.desc {
  padding: 0 16px 16px;
}

.links {
  padding: 14px 16px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 10px;
}

.link-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 13px;
  border: 1px solid var(--fu-border);
  border-radius: 9px;
  text-decoration: none;
  color: inherit;
  transition: all 0.16s ease;
}

.link-card:hover {
  border-color: var(--el-color-primary);
  background: var(--fu-brand-soft);
}

.lc-title {
  font-size: 13px;
  font-weight: 600;
}

.lc-sub {
  font-size: 11.5px;
  color: var(--fu-text-muted);
}

.ws-box {
  padding: 12px 16px 16px;
}

.ws-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  margin-bottom: 6px;
}

.ws-tip {
  font-size: 12px;
  line-height: 1.6;
}

.api-groups {
  padding: 14px 16px 18px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(420px, 100%), 1fr));
  gap: 20px 26px;
}

.ag-title {
  font-size: 13px;
  font-weight: 650;
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--fu-border);
}

.ag-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 12px;
}

.method {
  width: 46px;
  flex-shrink: 0;
  justify-content: center;
}

.path {
  color: var(--fu-text);
  flex-shrink: 0;
}

.note {
  font-size: 11.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
