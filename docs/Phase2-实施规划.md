
---

## 四、实施路线图(甘特图式)

```
Week 1:   [Phase-1 已完成]
Week 2:   [U-1][U-2][U-3][U-4][U-5][U-6]          User 模块改造
Week 3:            [S-1][S-2][S-3][S-4][S-5]       安全加固
Week 4:                          [M-1][M-3]          告警 + Inspector 修复
Week 5:                                    [M-2]     历史数据归档一期
Week 6:                                              [UI-1][UI-2][UI-3][UI-6]
Week 7:                                                            [UI-4][UI-5]
Week 8:                                                                              [F-06]
Week 9:                                                                                                [F-07]
Week 10:                                                                                                                  [F-08][F-09][F-10]
```

> 注:批次间可并行——U 与 S 可并行(不同文件),M-3 可与 U 并行,UI 系列可跨 U/S/M 穿插。

---

## 五、用户模块改造详细设计

### 5.1 架构决策

**Q:为何废除 basic_auth header 方式?**
- HTTP Basic Auth header 与 JWT Bearer 混用会让安全边界模糊
- 现代 SPA 应用标准模式是 token 认证,Basic header 主要用于 CLI/内部工具
- 用户明确需求,且 Phase-1 已清理后门(B-03),现在是彻底切换的最佳时机

**Q:过渡期是否保留 Basic Auth?**
- 默认 `legacy_basic_auth_enabled=false`,**建议立即切断**
- 如有内部工具依赖,给 2 周迁移期后强制关闭
- 迁移指南:把 `Authorization: Basic base64(user:pass)` 替换为 `Authorization: Bearer <token>`(token 从 `/api/auth/login` 获取)

**Q:密码存储方式不变?**
- 保持现有 `user:pass` 明文 HMAC 比对(已用 compare_digest 防时序攻击)
- 下一步(F-03 RBAC)可升级为 bcrypt/argon2,本次不引入额外复杂度

### 5.2 API 契约

```
# 登录
POST /api/auth/login
  req: {username, password}
  res: {access_token, token_type, username}
  失败: 401 {detail: "用户名或密码错误"}

# 注销
POST /api/auth/logout
  res: {message: "已注销"}
  仅清服务端黑名单(若实现);前端清 localStorage

# 改密
POST /api/auth/password/change
  req: {old_password, new_password}
  res: {message: "密码已修改,所有会话已失效"}
  失败: 400 {detail: "旧密码错误"} / 422 {detail: "新密码不满足复杂度"}

# 我的 session 列表
GET /api/auth/sessions
  res: {sessions: [{jti, issued_at, exp, ip, ua}]}

# 撤销单个 session
DELETE /api/auth/sessions/{jti}
  res: {message: "已撤销"}

# 登录限流查询
GET /api/auth/lockout/status?username=&ip=
  res: {locked: bool, remaining_seconds: int}

# 登录日志
GET /api/auth/login-logs?limit=&user=&start=&end=
  res: {items: [{ts, user, ip, ua, result: success|failed, error?}]}
```

### 5.3 前端路由

```js
// router/index.js 新增
{
  path: '/users',
  name: 'users',
  component: () => import('@/views/UserManagementView.vue'),
  meta: { title: '用户管理', icon: 'User', requiresAuth: true }
},
{
  path: '/users/login-logs',
  name: 'users-login-logs',
  component: () => import('@/views/user/LoginLogsView.vue'),
  meta: { title: '登录记录', parent: 'users' }
},
{
  path: '/users/accounts',
  name: 'users-accounts',
  component: () => import('@/views/user/AccountsView.vue'),
  meta: { title: '用户列表', parent: 'users' }
},
{
  path: '/users/my-account',
  name: 'users-my-account',
  component: () => import('@/views/user/MyAccountView.vue'),
  meta: { title: '我的账户', parent: 'users' }
},
{
  path: '/users/settings',
  name: 'users-settings',
  component: () => import('@/views/user/LoginSettingsView.vue'),
  meta: { title: '登录设置', parent: 'users' }
},
{
  path: '/users/sessions',
  name: 'users-sessions',
  component: () => import('@/views/user/SessionsView.vue'),
  meta: { title: '会话管理', parent: 'users' }
}
```

### 5.4 侧边栏菜单结构

```
🌸 FlowerUI
├─ 📊 监控总览      /dashboard
├─ 💻 Workers       /workers
├─ 📋 任务列表      /tasks
├─ 📨 Broker 队列   /broker
├─ 📈 实时图表      /monitor
├─ 🚀 下发任务      /apply
├─ 👤 用户管理      /users (仅 auth_enabled 时显示)
│  ├─ 登录记录
│  ├─ 用户列表
│  ├─ 我的账户
│  ├─ 登录设置
│  └─ 会话管理
├─ ⚙️ 系统配置      /config
└─ ℹ️ 系统信息      /system
```

### 5.5 配置项变更

```
# config.py
basic_auth_enabled: bool  →  label="启用密码登录", 语义不变
basic_auth: List[str]     →  label="用户列表",         hint="每行 user:pass"
oauth2_*                  →  已有,不变
password_min_length: int  →  新增,默认 8
password_require_upper: bool → 新增,默认 false
password_require_digit: bool → 新增,默认 false
password_require_special: bool → 新增,默认 false
legacy_basic_auth_enabled: bool → 新增,默认 false(过渡期 flag)
```

### 5.6 验收标准

- [ ] `curl -H "Authorization: Basic dXNlcjpwYXNz" http://127.0.0.1:5555/api/tasks` 返回 **401**
- [ ] `curl -X POST http://127.0.0.1:5555/api/auth/login -d '{\"username\":\"admin\",\"password\":\"admin\"}'` 返回 JWT
- [ ] 用返回的 Bearer token 访问 `/api/tasks` 成功
- [ ] `/api/auth/password/change` 改密后旧 token **全部失效**
- [ ] 连续 5 次错误密码 → 429 + 5min 锁定
- [ ] 前端侧边栏出现 👤 用户管理 分组
- [ ] 5 个子页面均能正常渲染.无控制台报错
- [ ] `npm run build` 通过
- [ ] py_compile 全部后端文件通过
- [ ] TestClient 冒烟通过(新增 15 项断言)

---

## 六、文档更新清单

实施完毕后需同步更新:
1. `docs/不足与方案梳理.md` — 第五节追加 U-1~U-6.S-1~S-5 条目,更新总览表
2. `docs/设置模块验收报告.md` — 补充用户模块改造的验收记录
3. `CHANGELOG.md` — 新增「v0.9.0 · 用户模块 JWT 迁移」章节
4. `README.md` — 鉴权方式一节改为 JWT Bearer 为主,标注 legacy_basic_auth_enabled 过渡 flag

---

## 七、风险提示

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 现有内部工具依赖 Basic Auth | 中 | 高 | 加 2 周过渡期 flag,提前发公告 |
| JWT jti 导致存量 token 失效 | 高 | 中 | changelog 明确告知,提供迁移脚本 |
| 登录限流误封正常用户 | 低 | 中 | 默认宽松(5 次/5min),可配置;提供 IP 白名单 |
| 移动端适配改动影响桌面布局 | 低 | 中 | 断点 900px 只在 <900 生效,桌面零 diff |
| 告警系统 F-01 与 RBAC F-03 耦合 | 中 | 中 | 先实现 F-01 基础版(无角色),F-03 时再接入 |

---

> **本文档由 captain 人工编制,未经 AgentTeams 自动生成。建议作为 Phase-2 工作的唯一 source of truth,所有任务 ticket 与之对应。**