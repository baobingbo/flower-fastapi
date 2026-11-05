export default {
  login: { title: '登录', username: '用户名', password: '密码', remember: '记住我', submit: '登录', oauth: '使用 {provider} 登录', error: '登录失败', success: '登录成功' },
  dashboard: { title: '监控总览', workers: 'Workers', tasks: '任务', queues: '队列', uptime: '运行时间' },
  workers: { title: 'Workers', name: '名称', online: '在线', inactive: '不活跃', actions: '操作' },
  tasks: { title: '任务列表', id: 'ID', name: '任务名', state: '状态', worker: 'Worker', received: '接收时间', started: '开始时间', runtime: '运行时长', result: '结果' },
  broker: { title: 'Broker 队列', queue: '队列名', messages: '消息数', consumers: '消费者' },
  monitor: { title: '实时图表', throughput: '吞吐量', success_rate: '成功率' },
  apply: { title: '下发任务', taskName: '任务名', args: '位置参数', kwargs: '关键字参数', queue: '队列', apply: '下发任务' },
  config: { title: '系统配置', save: '保存', reset: '恢复默认', restart: '重启系统' },
  system: { title: '系统信息', broker: 'Broker', resultBackend: '结果后端', version: '版本' },
  userMgmt: { title: '用户管理', accounts: '用户列表', myAccount: '我的账户', loginLogs: '登录记录', sessions: '会话管理', settings: '登录设置' },
  dag: { title: 'DAG 视图' },
  beat: { title: 'Beat 管理' },
  lang: { zh: '中文', en: 'English' }
}
