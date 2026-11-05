export default {
  login: { title: 'Login', username: 'Username', password: 'Password', remember: 'Remember me', submit: 'Login', oauth: 'Login with {provider}', error: 'Login failed', success: 'Login successful' },
  dashboard: { title: 'Dashboard', workers: 'Workers', tasks: 'Tasks', queues: 'Queues', uptime: 'Uptime' },
  workers: { title: 'Workers', name: 'Name', online: 'Online', inactive: 'Inactive', actions: 'Actions' },
  tasks: { title: 'Tasks', id: 'ID', name: 'Task Name', state: 'State', worker: 'Worker', received: 'Received', started: 'Started', runtime: 'Runtime', result: 'Result' },
  broker: { title: 'Broker Queues', queue: 'Queue', messages: 'Messages', consumers: 'Consumers' },
  monitor: { title: 'Real-time Charts', throughput: 'Throughput', success_rate: 'Success Rate' },
  apply: { title: 'Apply Task', taskName: 'Task Name', args: 'Positional Args', kwargs: 'Keyword Args', queue: 'Queue', apply: 'Apply' },
  config: { title: 'Configuration', save: 'Save', reset: 'Reset', restart: 'Restart' },
  system: { title: 'System Info', broker: 'Broker', resultBackend: 'Result Backend', version: 'Version' },
  userMgmt: { title: 'User Management', accounts: 'Accounts', myAccount: 'My Account', loginLogs: 'Login Logs', sessions: 'Sessions', settings: 'Settings' },
  dag: { title: 'DAG View' },
  beat: { title: 'Beat Management' },
  lang: { zh: '中文', en: 'English' }
}
