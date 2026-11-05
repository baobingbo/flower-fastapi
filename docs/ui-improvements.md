# FlowerUI 前端页面体验审计报告

> 审计对象：`frontend/src`（Vue 3 + Element Plus + ECharts + Pinia 的 Celery 实时监控平台）
> 审计范围：11 个视图（Dashboard / Workers / WorkerDetail / Tasks / TaskDetail / Monitor / Broker / Config / System / ApplyTask / Login）、通用组件、composables、stores、api、主题与样式系统
> 方法：逐文件通读源码，每个优化点均引用具体文件与行号/代码片段。行号以当前工作区版本为准。

## 目录

- [1. 汇总表](#1-汇总表)
- [2. 全局性问题](#2-全局性问题)：G1 图表主题失效 / G2 notMerge 重置交互 / G3 错误 toast 双弹 / G4 表格密度设置失效 / G5 配置未保存无提醒 / G6 后台标签页不暂停轮询 / G7 小屏适配缺失 / G8 散落硬编码浅色 / G9 无右键菜单与快捷键
- [3. 页面级优化点](#3-页面级优化点)：D1-D4（Dashboard）/ W1-W4（Workers）/ WD1-WD3（WorkerDetail）/ T1-T5（Tasks）/ TD1-TD4（TaskDetail）/ M1-M4（Monitor）/ B1-B2（Broker）/ C1-C5（Config）/ S1-S3（System）/ A1-A4（ApplyTask）/ L1-L2（Login）/ LAY1-LAY3（AppLayout 与 DetailOverlay）
- [4. 做得好的地方（保持）](#4-做得好的地方保持)
- [5. 实施建议（优先级路线图）](#5-实施建议优先级路线图)

---

## 1. 汇总表

优先级分布：**高 12 项 / 中 22 项 / 低 18 项，共 52 项**。

| # | 优先级 | 页面/组件 | 优化点 |
|---|--------|-----------|--------|
| G1 | 高 | 全局（useChart.js + 各视图图表） | 图表配色硬编码浅色，暗色/自定义主题下轴线和图例不可读 |
| G2 | 高 | 全局（useChart.js） | setOption(option, true) 每 2 秒重置用户交互；全站无 dataZoom |
| G3 | 高 | 全局（api/client.js + 各视图） | 同一失败弹两次错误 toast |
| G4 | 高 | 全局（settings.js + 全部 el-table） | 「表格密度」设置从未应用到任何表格 |
| G5 | 高 | ConfigView | 未保存改动无 beforeRouteLeave / beforeunload 保护 |
| G6 | 中 | 全局（stores/app.js 等） | 后台标签页仍按间隔轮询，不暂停 |
| G7 | 高 | AppLayout / DetailOverlay / SystemView | 移动端无断点适配：侧边栏、抽屉、网格均溢出 |
| G8 | 中 | 多页面 scoped 样式 | 散落硬编码浅色（#fafbfc / #fcfdfe / #f7faff / #fef7f7 等） |
| G9 | 低 | 全局 | 无右键菜单、无键盘快捷键 |
| D1 | 高 | DashboardView | loadDistribution 的 setInterval 永不清除（离开页面后持续发请求） |
| D2 | 中 | DashboardView | 事件流不可过滤/暂停/点击跳转，类型 tag 无状态色 |
| D3 | 中 | DashboardView | 饼图空态用假数据片渲染灰环 |
| D4 | 低 | DashboardView | 趋势图无 dataZoom；StatCard 不可点击联动 |
| W1 | 中 | WorkersView | 无多选批量操作（shutdown/重启只能逐行） |
| W2 | 中 | WorkersView | 展开行背景硬编码 #fafbfc，暗色主题下突兀 |
| W3 | 低 | WorkersView | 负载列无过载水位提示 |
| W4 | 低 | WorkersView | 离线行「控制」按钮禁用但无原因提示 |
| WD1 | 中 | WorkerDetailView | 「占比」进度条实为相对最大值的比值，最大者恒 100% |
| WD2 | 低 | WorkerDetailView | Grow / Shrink / Autoscale 按钮英文，其余全中文 |
| WD3 | 低 | WorkerDetailView | 限流表达式（10/m）无前端格式校验 |
| T1 | 高 | TasksView | 撤销/终止按钮恒可点，与详情页 :disabled 逻辑不一致 |
| T2 | 高 | TasksView + App.vue | keep-alive 缓存下 5s 轮询永不取消，离页后台请求+回页数据陈旧 |
| T3 | 中 | TasksView | 无多选批量撤销/终止 |
| T4 | 中 | TasksView | 搜索 DSL 提示包裹在 el-input 的 tooltip 上，交互别扭 |
| T5 | 低 | TasksView | 自动刷新不随标签页隐藏暂停 |
| TD1 | 中 | TaskDetailView | copy() 未处理 clipboard 失败仍提示「已复制」 |
| TD2 | 中 | TaskDetailView | 时间线只显示时间戳，无阶段耗时（排队/执行）拆解 |
| TD3 | 低 | TaskDetailView | .code / .code.err 硬编码浅色文字与背景 |
| TD4 | 低 | TaskDetailView | 「获取结果」弹框内无复制按钮 |
| M1 | 高 | MonitorView | loadDist 的 setInterval 永不清除（同 D1） |
| M2 | 中 | MonitorView | range 只切客户端 timeline，数据不足时无提示 |
| M3 | 中 | MonitorView | 「平均耗时排行」柱条不能点击跳转到对应任务列表 |
| M4 | 低 | MonitorView | 耗时排名色阶阈值硬编码且无图例说明 |
| B1 | 中 | BrokerView | 「积压水位」进度条 /10 封顶 100% 与 tag 阈值(100/500)两套标尺 |
| B2 | 低 | BrokerView | 队列行无联动操作（跳 worker/任务过滤） |
| C1 | 高 | ConfigView | 配置项多但无关键词搜索/过滤 |
| C2 | 中 | ConfigView | 轮询间隔 slider max=30000 与 input max=POLL_MAX=120000 不一致 |
| C3 | 中 | ConfigView | 重启后固定 2.5s reload，服务未就绪时用户看到报错页 |
| C4 | 低 | ConfigView | resetAll / removeTheme 的 confirm 无 catch，取消时抛未处理 rejection |
| C5 | 低 | ConfigView | dict 编辑器不检测重复键（Object.fromEntries 静默覆盖） |
| S1 | 中 | SystemView | dashboardApi.system() 失败静默，全页显示「-」却无任何报错 |
| S2 | 中 | SystemView | .api-groups minmax(420px) 小屏横向溢出；hover 背景 #f7faff 仅浅色 |
| S3 | 低 | SystemView | API 清单硬编码且无真实健康状态，可用 /healthcheck 点亮 |
| A1 | 中 | ApplyTaskView | 下发记录仅存内存，刷新即失 |
| A2 | 中 | ApplyTaskView | args/kwargs JSON 无即时校验，提交才报错 |
| A3 | 低 | ApplyTaskView | 历史行「刷新」查不到事件时弹 toast，反复点击很吵 |
| A4 | 低 | ApplyTaskView | .hrow / .hresult 硬编码浅色背景 |
| L1 | 中 | LoginView | redirect 参数未校验，存在开放重定向风险 |
| L2 | 低 | LoginView | 登录失败无前端节流/锁定提示 |
| LAY1 | 高 | AppLayout | <900px 侧边栏仍占 216px，移动端不可用 |
| LAY2 | 中 | DetailOverlay | 抽屉固定 58%/50% 宽，小屏不铺满；状态不同步到 URL |
| LAY3 | 低 | AppLayout | 顶栏无「最后更新时间」，channel.lastUpdate 未展示 |

---

## 2. 全局性问题

### G1【优先级：高】图表配色硬编码浅色，暗色/自定义主题下大面积失效

- **所属**：`frontend/src/composables/useChart.js` + Dashboard / Monitor / Broker 三个视图的全部 ECharts 实例。
- **现状**：主题系统本身是完备的——`styles/themes/dark.css` 与 `light.css` 都定义了图表令牌：
```css
--fu-chart-1: #5b93ff; ... --fu-chart-6: #34cde3;
--fu-chart-axis: #6d7589;
--fu-chart-split: rgba(150, 160, 185, 0.14);   /* dark.css L71-78 */
```
  但 `useChart.js` 的公共轴样式完全没消费这些令牌：
```js
// useChart.js L47-51
export const AXIS_STYLE = {
  axisLine: { lineStyle: { color: '#dcdfe6' } },
  axisLabel: { color: '#909399', fontSize: 11 },
  splitLine: { lineStyle: { color: '#f0f2f5' } }
}
```
  各视图还各自硬编码图例文字色与系列色，例如 DashboardView L38 `textStyle: { fontSize: 11, color: '#606266' }`、L74 饼图 `itemStyle: { borderColor: '#fff' }`；MonitorView L20/L67/L25/L92 同样写死 `#606266` / `#909399`。全前端 grep 出 40+ 处图表相关硬编码 hex。
- **影响**：切到「深色」或任何自定义暗色主题后，所有图表的坐标轴文字（#909399 / #606266 浅灰）叠在深底上接近不可读，分割线 #f0f2f5 变成亮白横线，饼图白色描边变成刺眼的白圈。主题系统的「最后一公里」断在图表层。
- **改进方案**：
  1. `useChart.js` 增加 `chartTokens()`：用 `getComputedStyle(document.documentElement)` 读取 `--fu-chart-axis`、`--fu-chart-split`、`--fu-text-muted`，`AXIS_STYLE` 与图例 `textStyle` 全部改为引用（ECharts 选项是纯 JS，不支持 CSS var，需在 setOption 时解析）。
  2. 主题变化时重渲染：在 `useChart` 内 `watch(() => document.documentElement.dataset.theme, render)`，或在 `stores/theme.js` 的 `watch(activeId, apply)` 之后广播事件让各图表 render。
  3. 系列色统一改从 `--fu-chart-1..6` 取值（顺带让已导出但从未使用的 `CHART_PALETTE`（useChart.js L42-45，死代码）真正落地，或直接删除）。
  4. 各视图内的 `color: '#67c23a'` 等改为按语义取 `--fu-chart-*` 或 EP 的 `--el-color-success` 解析值。
- **预期收益**：暗色与 14 个用户自定义主题（themes/ 目录）下所有图表一次修复可读性，是主题系统完整性的关键缺口。

### G2【优先级：高】useChart 每 2 秒 notMerge 重渲染，抹掉用户图表交互；全站无 dataZoom

- **所属**：`frontend/src/composables/useChart.js` L13-17、L34。
- **现状**：
```js
function render() {
  if (!el.value) return
  if (!chart) chart = echarts.init(el.value)
  chart.setOption(optionFn(), true)   // ← notMerge = true
}
watch(deps, render, { deep: true })
```
  数据源是 2 秒一个采样点的 timeline（app.js 中 `timeline` 每次 WS 推送都更新），于是：用户点了图例隐藏「失败」系列、拖了 dataZoom、hover 到某点看 tooltip——下一轮 2 秒推送 setOption 全量重绘，**用户的图例选择被还原**，任何交互状态都不保留。同时全站 8 个图表没有一个配置 `dataZoom`，Monitor 页 360 个采样点（12 分钟 × 2s）挤在固定宽度里无法局部放大。
- **改进方案**：
  1. 实时增量更新改用 `chart.setOption(optionFn(), { replaceMerge: [] })` 或 `notMerge: false`（增量合并），图例选中、zoom 窗口即可保留；仅当系列结构变化时才整体重设。
  2. 折线类图表加 `dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 4 }`]（inside 保证触屏/滚轮缩放），配合 `xAxis.max = 'dataMax'` 自动跟随最新窗口。
  3. `watch(deps, render, { deep: true })` 对 360 点 × 4 系列的深比较开销不小，可改为监听 `store.timeline.length` + 末点对象引用。
- **预期收益**：图表从「只能被动看」变成可交互分析；实时推送不再与用户操作打架，是监控类平台的高频痛点。

### G3【优先级：高】错误提示双份：axios 拦截器与各视图 catch 各弹一次

- **所属**：`frontend/src/api/client.js` L13-32 与 TasksView L67、WorkersView L34、WorkerDetailView L26、TaskDetailView L46 等所有手写 catch。
- **现状**：拦截器已对每个非 silent 请求弹 toast：
```js
// client.js L27-29
} else if (!err.config?.silent) {
  ElMessage.error(typeof detail === 'string' ? detail : '请求失败')
}
```
  而视图里又各自 `catch (err) { ElMessage.error(err?.message || '加载失败') }`（如 TasksView.vue L67）。同一请求失败 → **同一时刻弹两条内容几乎相同的红色 toast**（ElMessage 连续同文案会堆叠成两条）。
- **改进方案**：二选一——
  - 方案 A（推荐）：视图层负责提示，拦截器去掉 ElMessage，只保留 401 处理；silent 语义交给各调用点自己决定。
  - 方案 B：拦截器统一提示，视图 catch 里只处理状态（notFound 等），删掉所有重复 `ElMessage.error`。
  - 顺带修复：client.js L24-26 的 401 分支里有一段空 if 块（注释掉的残留跳转逻辑），应删除以免误导维护者。
- **预期收益**：消除全站所有错误场景的 toast 双弹，错误反馈路径单一化。

### G4【优先级：高】「表格密度」设置项存在但从未生效（断头功能）

- **所属**：`frontend/src/stores/settings.js` L33 + `frontend/src/views/ConfigView.vue` L595-601 + 全部 10 个 el-table。
- **现状**：配置页「交互偏好」里给用户提供了三档表格密度：
```html
<!-- ConfigView.vue L596-601 -->
<el-radio-group v-model="settings.tableSize" size="small">
  <el-radio-button value="small">紧凑</el-radio-button>
  <el-radio-button value="default">标准</el-radio-button>
  <el-radio-button value="large">宽松</el-radio-button>
</el-radio-group>
```
  该值被持久化到 localStorage（settings.js L104 watch → persist），但 grep 全前端只有 settings.js 与 ConfigView 这 7 处引用——**没有任何一个表格消费它**。所有表格都写死了 `size="small"`（TasksView L179、DashboardView L189、WorkerDetailView 各处）或 `size="default"`（WorkersView L111、BrokerView L111）。
- **改进方案**：在 AppLayout 内用 `<el-table :size="settings.tableSize">` 替换所有硬编码 size；或封装项目级 `FuTable` 组件（顺带统一 empty 插槽、row-click 等重复模板）。
- **预期收益**：修好一个已暴露给用户却不工作的设置项——这类「设置无效」比「没设置」更伤害信任。

### G5【优先级：高】配置页有未保存改动时无任何离开提醒

- **所属**：`frontend/src/views/ConfigView.vue`（dirtyKeys L40-58）。
- **现状**：ConfigView 维护了完整的「脏键」计算（`dirtyKeys`、顶部「保存修改（N）」按钮），但全前端 grep 不到任何 `beforeRouteLeave` / `beforeunload`。用户在「任务队列」分组改了 3 个配置 → 直接点侧边栏离开 → 草稿随组件销毁全部丢失，无任何确认。
- **改进方案**：
```js
// ConfigView.vue
import { onBeforeRouteLeave } from 'vue-router'
onBeforeRouteLeave(() => {
  if (!dirtyKeys.value.length) return true
  return ElMessageBox.confirm('配置页有未保存的改动，离开将丢失', '未保存提醒',
    { type: 'warning', confirmButtonText: '仍要离开', cancelButtonText: '返回' })
    .catch(() => false)
})
// onMounted 里再注册 window 'beforeunload' 监听作为浏览器级兜底，onUnmounted 移除
```
- **预期收益**：保护运维人员最重要的操作路径（改配置），消除静默数据丢失。

### G6【优先级：中】后台标签页不暂停轮询（无 visibilitychange）

- **所属**：`frontend/src/stores/app.js`（startPolling L148-153）、`views/TasksView.vue` L123、`views/BrokerView.vue` L67、`views/WorkerDetailView.vue` L124、`views/MonitorView.vue` L120。
- **现状**：全前端 grep 不到任何 `visibilitychange` 处理。轮询模式下 app store 每 pollInterval 拉一次 snapshot，同时 TasksView 5s、BrokerView 5s、WorkerDetail 5s、Monitor/Dashboard 15s 的页面级 setInterval 并行运行。用户开着监控页切到别的标签，浏览器后台仍按全速发请求（监控平台常见用法就是多开标签常驻）。
- **改进方案**：抽一个 `usePagePolling(fn, ms)` composable：内部监听 `visibilitychange`，hidden 时 clearInterval，visible 时立即补拉一次再恢复定时；把 app.js 的 pollOnce 与各页面 timer 全部迁移过去。
- **预期收益**：后台零无效请求，省服务端压力；回到页面第一眼就是新数据。

### G7【优先级：高】小屏/移动端适配缺失（侧边栏、抽屉、网格）

- **所属**：`layouts/AppLayout.vue`、`components/DetailOverlay.vue`、`views/SystemView.vue`。
- **现状**：
  - AppLayout 唯一的响应式断点是 `@media (max-width: 900px) { .broker-url, .badge { display: none } }`（L352-357）——**侧边栏在任何宽度都占 216px（收起 64px）**，390px 手机屏幕上正文只剩约 170px，表格横向滚动条永远在。
  - DetailOverlay 抽屉写死 `size="58%" / "50%"`（DetailOverlay.vue L13），小屏下 50% 宽度的任务详情表格完全不可读。
  - SystemView `grid-template-columns: repeat(auto-fit, minmax(420px, 1fr))`（L251）：视口 <420px 时网格单项强制 420px 宽，直接横向溢出。
- **改进方案**：
  1. AppLayout：`<900px` 时侧边栏改为 off-canvas（默认收起 + 汉堡按钮以 el-drawer 承载同一份菜单模板），桌面行为零 diff。
  2. DetailOverlay：宽度按断点 —— 移动端 `100%`，桌面保持 58% / 50%。
  3. SystemView：`minmax(min(420px, 100%), 1fr)` 消除溢出。
- **预期收益**：平板/手机（巡检场景常见：蹲在机房用手机看队列）从「勉强能看」到「能用」。

### G8【优先级：中】页面级散落硬编码浅色，绕开主题令牌

- **所属**：各视图 scoped style（完整清单见下）。
- **现状**（grep 实测，均在 `--fu-*` 令牌体系之外）：
```
| 文件                | 行        | 硬编码值            | 位置                     |
|---------------------|-----------|---------------------|--------------------------|
| DashboardView.vue   | 266 / 270 | #f2f4f7 / #fafbfc   | 事件流行分割线 / hover 底 |
| WorkersView.vue     | 221       | #fafbfc             | 展开行背景 .expand        |
| ApplyTaskView.vue   | 291 / 319 | #fcfdfe / #f6f8fa   | 历史卡片 / 结果 pre       |
| SystemView.vue      | 218       | #f7faff             | 快捷入口 hover 背景       |
| TaskDetailView.vue  | 330-335   | #3a3f47/#b34040/#fef7f7 | .code 文字 / .code.err |
| StatCard.vue        | 41        | rgba(31,45,61,.08)  | hover 阴影               |
```
- **影响**：切到暗色主题后，这些区块变成深页面里的浅色孤岛（尤其 WorkersView 展开行、TaskDetail 代码块：浅粉底 + 深红字在暗色下刺眼）。
- **改进方案**：逐条替换为已有令牌——`var(--fu-surface-2)`（展开/卡片背景）、`var(--fu-border)`（分割线）、`var(--fu-code-bg)` / `var(--fu-code-text)`（代码块，令牌已存在但 .code 没用上）、`var(--fu-brand-soft)`（hover）、`var(--fu-danger-soft)` + `var(--fu-danger)`（err）。建议加一条 CI 检查（grep 或 ESLint 规则）禁止 `.vue` scoped style 出现裸 hex。
- **预期收益**：自定义主题（themes/ 目录下 14 个用户主题）真正全覆盖，不留浅色死角。

### G9【优先级：低】无右键菜单、无键盘快捷键（交互增强缺口）

- **所属**：全局（grep 全前端无 `contextmenu`、无全局 keydown 监听）。
- **现状**：表格行上的高频操作（打开详情、撤销、终止、打开 worker）只能靠点文字按钮；监控平台重度用户习惯键盘 + 右键。
- **改进方案**：
  1. Tasks / Workers 表格加 `@row-contextmenu` + 轻量右键菜单（el-dropdown 定位到鼠标处），与操作列按钮复用同一组 handler。
  2. 全局快捷键：`?` 打开快捷键说明、`g d` / `g t` / `g w` 跳页面、`r` 当前页刷新、`/` 聚焦搜索框；用一个小 composable `useHotkeys` 集中注册，输入框聚焦时自动禁用。
- **预期收益**：高频运维操作效率提升；成本较低，适合第二批增强。

---

## 3. 页面级优化点

### 3.1 DashboardView（监控总览）

**D1【优先级：高】分布统计定时器泄漏：离开页面后 API 请求永不停止**
- 位置：`views/DashboardView.vue` L117-124。
- 现状：
```js
onMounted(async () => {
  ...
  await loadDistribution()
  setInterval(loadDistribution, 15000)   // ← 返回的 id 被丢弃
})
```
  组件没有 onUnmounted，定时器句柄被丢弃。切到任意其它页面后，这个 15s 定时器闭包持有组件状态，继续调用 `/api/dashboard/task-distribution`（MonitorView L120 有一模一样的问题，见 M1）。多次进出页面会叠加多个定时器。
- 改进：
```js
let distTimer = null
onMounted(() => { ...; distTimer = setInterval(loadDistribution, 15000) })
onUnmounted(() => clearInterval(distTimer))
```
  更彻底的做法：把「分布/排行类慢数据」的定时抽进 app store 或 composable（配合 G6 的可见性暂停），页面只订阅。
- 收益：消除后台无意义请求与内存泄漏；这类 bug 会随页面增多复利。

**D2【优先级：中】事件流：不可过滤、不可暂停、不可点击，类型无状态色**
- 位置：L212-229（模板）+ stores/app.js pushEvents（MAX_EVENTS=200）。
- 现状：
```html
<el-tag size="small" effect="plain" class="feed-type">{{ e.type }}</el-tag>
<span class="mono feed-name">{{ truncate(e.name || e.hostname || '', 44) }}</span>
```
  问题：① 40 条平铺，没有按类型（task-received / task-failed / worker-heartbeat…）过滤，也没有「暂停」——高吞吐时事件刷得太快，人眼根本读不到 failure；② `task-failed` 这样的关键事件与 heartbeat 用同一个灰色 plain tag，没有按类型着色/加粗；③ 行不可点击——任务事件本应能一键打开 TaskDetail（detail store 现成）；④ 无搜索框。
- 改进：
  - 头部加 `el-checkbox 暂停` + 类型多选过滤（el-dropdown 勾选）+「只看失败/重试」快捷开关；
  - feed-type tag 加映射：`{ 'task-failed': 'danger', 'task-retried': 'warning', 'task-started': 'primary', ... }`（可参考 format.js 的 TASK_STATE_TYPE）；
  - 行 `@click`：事件带 uuid 时 `detail.openTask(e.uuid)`，带 hostname 时 `detail.openWorker(e.hostname)`。
- 收益：事件流从「滚动日志」升级为「可审计的告警入口」，这是监控台的核心价值点。

**D3【优先级：中】状态分布饼图空态是「假数据灰环」**
- 位置：L76：
```js
data: data.length ? data : [{ name: '暂无数据', value: 1, itemStyle: { color: '#ebeef5' } }]
```
  空数据时渲染一个灰色圆环 + 图例「暂无数据 100%」，语义错误（看起来像真有一个状态叫「暂无数据」），且灰色 #ebeef5 硬编码。
- 改进：空数据时不给 series data，在图表容器上叠 `<el-empty :image-size="70" description="暂无任务数据" />`（与 useChart 的 el 共存，有数据时隐藏）。

**D4【优先级：低】趋势图无缩放能力；StatCard 不可点击联动**
- 现状：「实时吞吐趋势」120 个采样点固定宽度，无法放大看某段尖峰（G2 的 dataZoom 落地后此处自动受益）；顶部 6 张 StatCard（L142-151）纯展示——「在线 Worker 5」点一下应该能跳 /workers，「失败 12」应跳 /tasks 并带 state=FAILURE 过滤。
- 改进：StatCard 加可选 `to` prop（或 @click emit）；Dashboard 里给「在线 Worker」绑 `router.push('/workers')`，给「失败」绑 `router.push({ path: '/tasks', query: { state: 'FAILURE' } })`（TasksView 的 state 过滤需支持从 query 初始化，目前只支持 root_id / parent_id，见 L32-33）。

### 3.2 WorkersView（Workers 列表）

**W1【优先级：中】无多选与批量操作**
- 位置：L110-213（整个 el-table）。
- 现状：表格第一列是 expand 列，没有 `type="selection"`；shutdown / 重启进程池 / 扩缩容全部是行内 dropdown 单点操作。运维场景「把 3 台旧 worker 一起下线」要点 3 次确认框。
- 改进：加 selection 列 + 表头上方悬浮批量条（选中 N 台后出现「批量关闭」「批量重启进程池」按钮，逐个调用现成 API，结果用 ElNotification 汇总成功/失败数）。与 T3 共用同一个 BatchBar 组件。
- 收益：多节点运维效率显著提升。

**W2【优先级：中】展开行背景硬编码浅色**
- 位置：L219-222：
```css
.expand { padding: 12px 20px 14px 48px; background: #fafbfc; }
```
  暗色主题下展开行是一块浅灰面板，与深色卡片割裂（G8 清单成员）。
- 改进：`background: var(--fu-surface-2)`；vendor/element-plus.css L131 已定义 `--el-table-expanded-cell-bg-color: transparent`，自定义背景应与令牌体系统一。

**W3【优先级：低】负载列没有水位提示**
- 现状：L177-183 负载列只是 mono 灰色文本（loadavg.join(' ')），看不出过载与否；而 Broker 页对积压却有 tag 着色 + progress 条——同一平台内「水位可视化」标准不一致。
- 改进：按 loadavg[0] 与 concurrency 的比值着色：`>1` 红色、`>0.7` 橙色，列头加 tooltip 解释口径。

**W4【优先级：低】离线行控制按钮禁用无解释**
- 现状：L187-189 离线时「控制」按钮 disabled，用户不知道为什么。
- 改进：外包 `<el-tooltip :disabled="row.status" content="Worker 离线，控制操作不可用">`。

### 3.3 WorkerDetailView（Worker 详情抽屉）

**WD1【优先级：中】「占比」进度条实为相对最大值的比值，最大者恒 100%，语义误导**
- 位置：L405-419：
```html
<el-table-column label="占比" min-width="200">
  <template #default="{ row }">
    <el-progress
      :percentage="Math.round(row.count / Math.max(...totalRows.map(r => r.count)) * 100)"
      :stroke-width="10" :show-text="false" />
```
  列名叫「占比」（用户理解为占全部任务的比例），实现却是「占最大任务的比例」——第一名永远是 100% 满条，第二名的条长与「占比 40%」毫无对应关系。
- 改进：二选一：① 列名改「相对 Top1」并加 tooltip 说明口径；② 分母换成 totalRows 之和，成为真实占比（推荐）。
- 收益：消除数据可视化的语义陷阱（与 B1 同属「标尺不清」问题）。

**WD2【优先级：低】按钮文案中英混杂，同一功能三处三种叫法**
- 位置：L189 / L196 / L207 「Grow」「Shrink」「Autoscale」为英文，同页其它按钮（重启进程池、关闭节点、应用限流）全中文；WorkersView 的 dropdown 里对应项又叫「进程池 +1 / 进程池 -1 / 设置 Autoscale」——**同一功能三处三种叫法**。
- 改进：统一为「扩容 +N / 缩容 -N / 自动伸缩」，两个页面术语保持一致。

**WD3【优先级：低】限流表达式无前端校验**
- 位置：L288 `<el-input v-model="limitForm.ratelimit" placeholder="10/m" />` + L76-80 setRateLimit 只检查 taskname 非空，格式完全交给后端报错。
- 改进：提交前用正则（形如 `/^\d+\s*(\/\s*[smhd])?$/`）校验，不通过时 `ElMessage.warning('格式如 10/s、100/m、1000/h')`，或用 el-form rules 即时提示。

### 3.4 TasksView（任务列表）

**T1【优先级：高】撤销/终止按钮恒可点击，与详情页行为不一致**
- 位置：L236-244：
```html
<el-button text size="small" type="warning" @click="revoke(row, false)">撤销</el-button>
<el-button text size="small" type="danger" @click="revoke(row, true)">终止</el-button>
```
  没有任何 `disabled`。对比 TaskDetailView L121-123 三个按钮都有 `：disabled="finished"`（finished = SUCCESS / FAILURE / REVOKED / REJECTED / IGNORED）。列表页对一条 3 小时前 SUCCESS 的任务点「终止」，会走一遍确认框 → 调 API → 返回无效，纯粹误导。
- 改进：复用同一 TERMINAL 集合（建议挪到 format.js 导出），操作列按钮加 `：disabled="TERMINAL.includes(row.state)"`。
- 收益：杜绝无效高危操作入口，跨页行为一致。

**T2【优先级：高】keep-alive 缓存 + 5s 定时器：离页后台轮询、回页数据陈旧**
- 位置：`App.vue` L60 `<keep-alive :include="['TasksView']>` + `TasksView.vue` L120-126：
```js
onMounted(async () => {
  ...
  timer = setInterval(() => autoRefresh.value && load(true), 5000)
})
onUnmounted(() => clearInterval(timer))
```
  TasksView 被 keep-alive 缓存（script setup 下按文件名推断组件名），切走页面时触发的是 **deactivated 而非 unmounted**，`onUnmounted` 不执行 → 5s 定时器继续在后台跑（每次都是静默 load，用户看不到的请求一直在发）；再切回来时数据要等下一个 tick 才刷新，期间看到陈旧列表。
- 改进：
```js
import { onActivated, onDeactivated } from 'vue'
onActivated(() => { if (!timer) timer = setInterval(tick, 5000); load(true) })
onDeactivated(() => { clearInterval(timer); timer = null })
// 保留 onUnmounted 兜底非缓存场景；或统一用 G6 的 usePagePolling
```
- 收益：离页即停请求、回页即最新；也是 keep-alive 正确用法的范本。

**T3【优先级：中】无多选批量撤销/终止**
- 现状：操作列只有逐行三个按钮；一批积压 PENDING 任务要逐个点。
- 改进：加 selection 列 + 悬浮批量条「批量撤销（N）/ 批量终止（N）」；仅对非终态行可勾选（`：selectable` 函数）。与 W1 共用 BatchBar。

**T4【优先级：中】搜索 DSL 提示挂在输入框 tooltip 上，交互别扭**
- 位置：L152-161：
```html
<el-tooltip placement="bottom-start">
  <template #content> ...5 条 DSL 示例... </template>
  <el-input v-model="query.search" placeholder="搜索：result: / args: / kwargs: / state:" ... />
</el-tooltip>
```
  整个 el-input 成为 tooltip 触发器：鼠标悬停约 1 秒就弹出 5 行提示挡在输入区上，输入时反而看不到。
- 改进：提示挪到输入框 suffix slot 的一个问号图标（tooltip 只包图标），placeholder 保留一行精简语法。

**T5【优先级：低】自动刷新不随标签页隐藏暂停**
- 现状：L123 定时器无条件 5s load(true)（G6 的具体案例之一，本页是任务列表主力查询，后台空转成本最高）。
- 改进：随 G6 的 usePagePolling 落地即可。

### 3.5 TaskDetailView（任务详情抽屉）

**TD1【优先级：中】copy() 失败也提示「已复制」**
- 位置：L88-91：
```js
function copy(text) {
  navigator.clipboard?.writeText(String(text))
  ElMessage.success('已复制')
}
```
  两个问题：① writeText 的 Promise 未 await / 未 catch——非 HTTPS（很多内网运维环境是 http）或权限被拒时写入静默失败，用户却看到绿色「已复制」；② `navigator.clipboard` 为 undefined 时（老浏览器）同样提示成功。
- 改进：
```js
async function copy(text) {
  try {
    await navigator.clipboard.writeText(String(text))
    ElMessage.success('已复制')
  } catch {
    const ta = document.createElement('textarea')
    ta.value = String(text); document.body.appendChild(ta)
    const ok = document.execCommand('copy'); ta.remove()
    ok ? ElMessage.success('已复制') : ElMessage.error('复制失败，请手动选择复制')
  }
}
```

**TD2【优先级：中】执行时间线只列时间戳，缺阶段耗时拆解**
- 位置：L24-37 timeline computed + L163-168 el-timeline。
- 现状：时间线把 sent / received / started / succeeded 各自的时间戳平铺列出，但用户真正要的是「为什么慢」：received→started 是排队等待时长，started→succeeded 是执行时长。现在要拿秒表自己减。
- 改进：相邻两阶段之间计算 delta 并作为 timeline-item 的描述行显示（如 `started — 排队等待 3.2s`、`succeeded — 执行 128ms`）；排队等待超过阈值（如 5s）标橙色，一眼看出是 broker 积压还是任务本身慢。
- 收益：把详情页从「时间戳列表」变成「耗时归因工具」。

**TD3【优先级：低】代码块硬编码浅色（G8 成员）**
- 位置：L320-336：`.code { color: #3a3f47 }`、`.code.err { color: #b34040; background: #fef7f7 }`。暗色主题下 args / kwargs / traceback 面板是浅粉底 + 深灰字。
- 改进：`color: var(--fu-code-text); background: var(--fu-code-bg)`（令牌已存在，dark.css L57-58 专门定义了）；err 用 `var(--fu-danger-soft)` 底 + `var(--fu-danger)` 字。

**TD4【优先级：低】「获取结果」弹框内容不可复制**
- 位置：L74-86：ElMessageBox.alert 里塞一段 `<pre>`（dangerouslyUseHTMLString）。长结果只能在 pre 里手动选中复制。
- 改进：MessageBox 自定义按钮：confirm 按钮改为「复制」（调 copy(prettyJson(res))），cancel 为「关闭」。

### 3.6 MonitorView（实时图表）

**M1【优先级：高】loadDist 定时器泄漏（与 D1 同款）**
- 位置：L114-121：
```js
onMounted(async () => {
  ...
  await loadDist()
  setInterval(loadDist, 15000)   // ← 无 onUnmounted，句柄丢弃
})
```
  MonitorView 不在 keep-alive 列表里，切走即卸载但定时器照跑，持续请求 `/api/dashboard/task-distribution?top=12`。
- 改进：同 D1（保存句柄 + onUnmounted 清除；长期并入 app store 统一调度）。

**M2【优先级：中】range 只切客户端 timeline，数据不足时无提示**
- 位置：L11-13：
```js
const range = ref(120)
const points = computed(() => (store.timeline || []).slice(-range.value))
```
  选「12 分钟」但 WS 刚连上只有 30 个采样点时，图表只画一小截，用户以为数据丢了。timeline 上限 360 点（app.js MAX_TIMELINE），断开重连后 snapshot 整体替换还会造成 x 轴跳变。
- 改进：当 `store.timeline.length < range` 时 panel-sub 显示「当前仅 N 秒数据，积累中」；tooltip 带绝对时间避免误读。

**M3【优先级：中】「平均耗时排行」柱条不可点击跳转**
- 位置：L83-107（runtimeEl 图表）。
- 现状：看到某任务类型 avg_runtime 很高 → 想看它的具体任务，得手动去 /tasks 页在任务类型下拉里找。而 TasksView 明明有 taskname 过滤参数（buildParams L48）。
- 改进：图表 `on('click', p => router.push({ name: 'tasks', query: { taskname: p.name } }))`（TasksView 需支持从 query.taskname 初始化过滤，目前只读了 root_id / parent_id）；y 轴截断名（name.split('.').pop()）的完整任务名放进 tooltip。
- 收益：图表→列表的闭环分析路径（Dashboard 的 Top 任务图 D4 同理）。

**M4【优先级：低】耗时排名色阶阈值硬编码且无图例**
- 位置：L97-100：
```js
color: (p) => ['#67c23a', '#95d475', '#e6a23c', '#f89898', '#f56c6c'][
  Math.min(4, Math.floor(p.value / 2))]
```
  「<2s 绿、2-4s 浅橙…>8s 红」的规则写在代码里，界面上没有任何说明；且对 30s 级任务，颜色全部饱和在红，失去区分度。
- 改进：按当前数据 max 的分位数或 log 标度着色，panel-sub 注明「颜色按当前最大耗时的百分比」；阈值逻辑挪到 format.js 复用。

### 3.7 BrokerView（Broker 队列）

**B1【优先级：中】「积压水位」进度条与 tag 阈值是两套互不一致的标尺**
- 位置：L117-132：
```html
<el-tag :type="levelType(row.messages)" ...>{{ row.messages ?? 0 }}</el-tag>
<!-- levelType: >500 红, >100 橙 -->
...
<el-progress :percentage="Math.min(100, Math.round((row.messages || 0) / 10))"
             :status="row.messages > 500 ? 'exception' : row.messages > 100 ? 'warning' : 'success'" />
```
  进度条按 `messages / 10` 折算（1000 条 = 满条），但 tag 的状态阈值是 100 / 500：90 条消息时进度条已 90%（绿色），tag 还是 success；120 条时进度条 12% 却是 warning。同一数字两种视觉标尺，用户无法建立直觉。
- 改进：统一为一套分级函数 `levelOf(n)` 返回 {pct, status, label}，进度条 = 相对该级上限的百分比（分级 0 / 100 / 500 / 2000，超出后封顶 + 红色 + 数字显示真实值）；panel-sub 写明分级口径。

**B2【优先级：低】队列行无联动操作**
- 现状：表格只有查看列，没有操作列。看到某个队列积压 → 想知道谁在消费它，要去 Workers 页找 queues 列。
- 改进：操作列加「查看消费者」→ 跳转 /workers 并自动展开匹配队列的 worker（或打开对应 WorkerDetail）；「查看任务」→ /tasks。

### 3.8 ConfigView（系统配置）

**C1【优先级：高】配置项多但无搜索/过滤**
- 位置：L612-743 分组 tabs + cfg-list。
- 现状：服务端配置分组下每组是整列平铺的 cfg-item，没有关键词输入框。配置键动辄几十个（broker_url、task_routes、result_backend…），找一个键只能翻 tab 肉眼扫。label / key 都是现成文本，搜索成本极低但缺失。
- 改进：每个 tab-pane 顶部（或全局一个 sticky 搜索框）加 `el-input`，computed 过滤 `itemsByGroup[g.id`]（label + key 不区分大小写匹配），命中 key 高亮；进一步可支持 URL query 定位（`/config?tab=queue&key=basic_auth`）方便文档互链。
- 收益：配置页从「翻」到「找」，是使用频率最高的管理页的刚需。

**C2【优先级：中】轮询间隔 slider 与 input-number 上限不一致**
- 位置：L545-559：
```html
<el-slider v-model="pollSeconds" :min="POLL_MIN" :max="30000" ... />
<el-input-number v-model="pollSeconds" :min="POLL_MIN" :max="POLL_MAX" ... />
```
  滑块最多拖到 30s，输入框却能填 120s（POLL_MAX=120000，settings.js L21）：填 120000 后滑块停在最右端，视觉与值不符。
- 改进：slider 的 max 也用 POLL_MAX（或统一限制到 60s 并在 desc 说明），至少保证一致。

**C3【优先级：中】重启后固定 2.5s reload，服务未就绪时用户看到报错页**
- 位置：L192-199：
```js
await systemApi.restart()
ElMessage.success('正在重启服务，2.5 秒后自动刷新页面…')
setTimeout(() => location.reload(), 2500)
```
  后端进程拉起 + FastAPI 就绪通常 >2.5s；reload 打在半启动的后端上 → 白屏 / 502，用户以为重启失败了。
- 改进：reload 后进入「等待服务就绪」过渡：每 1s 轮询 `/healthcheck`，成功才渲染；或后端 restart 接口返回预计时间。至少把固定 2.5s 改成「先探活再 reload」循环（上限 30s）。

**C4【优先级：低】resetAll / removeTheme 的 confirm 无 catch**
- 位置：L132-138、L284-289：
```js
async function resetAll() {
  await ElMessageBox.confirm('将把所有...', '恢复启动值', {...})   // 用户点「取消」→ reject
  const res = await configApi.reset(null)
```
  点取消时 Promise reject 无人处理（控制台 Uncaught promise rejection 红字）；虽然功能上不会误执行，但和同文件 restartSystem（L175-183 有 try/catch）模式不一致。
- 改进：统一用 `.catch(() => { return })` 或 try/catch 包裹。

**C5【优先级：低】dict 编辑器不检测重复键**
- 位置：L212-229 updateDictRow / addDictRow 用 `Object.fromEntries` 序列化——用户新增一行与已有键相同，保存时静默覆盖，界面无任何提示。
- 改进：dictRows 渲染时给重复键加 `el-tag type="danger"`「重复」标记，或序列化前校验并提示。

### 3.9 SystemView（系统信息）

**S1【优先级：中】系统信息接口失败静默，全页「-」无报错**
- 位置：L71-73：
```js
onMounted(async () => {
  sys.value = await dashboardApi.system().catch(() => ({}))
})
```
  请求失败时整页渲染为「Broker URL -、Python 版本 - …」，与「真实值就是空」无法区分，也没有加载态（sys 初始为 {} 时直接渲染一排「-」）。
- 改进：加 `loading` / `failed` ref：失败时页面顶部 el-alert「系统信息获取失败：xxx（重试）」；加载中显示 v-loading。

**S2【优先级：中】API 清单网格小屏溢出 + hover 背景仅浅色**
- 位置：L251 `grid-template-columns: repeat(auto-fit, minmax(420px, 1fr))`（G7 成员，<420px 视口横向滚动）；L218 `.link-card:hover { background: #f7faff }`（G8 成员，暗色下闪浅蓝）。
- 改进：`minmax(min(420px, 100%), 1fr)`；hover 背景改 `var(--fu-brand-soft)`。

**S3【优先级：低】API 清单硬编码、无真实状态**
- 位置：L11-67 API_GROUPS 为手写数组（与 /docs 内容重复，后端加接口这里不会自动更新）；「健康检查」卡片只是新标签页跳转，本页不显示它现在到底是绿是红。
- 改进：进入页面时调 `/healthcheck`，在「健康检查」卡片与 WS 状态区显示实时绿/红点；API 清单保持静态可接受，但建议加「以 /docs 为准」的注脚降低维护心智。

### 3.10 ApplyTaskView（下发任务）

**A1【优先级：中】下发记录仅存内存，刷新即失**
- 位置：L18 `const history = ref([])`，L89 `history.value = history.value.slice(0, 30)`。
- 现状：刚下发的任务，30 秒后刷新页面，历史清空——而「我刚才发的那个任务 id 是多少」正是这个页面最核心的留存价值。
- 改进：history 持久化到 localStorage（key 如 `flower_apply_history`，含 ts / taskname / mode / id / state），onMounted 恢复；「清空」按钮已有。结果字段可能较大，落盘前截断 result 到约 500 字符。

**A2【优先级：中】args/kwargs JSON 无即时校验**
- 位置：L61-70（args / kwargs textarea）+ L39-47 parseJson 只在 submit 时执行。
- 现状：用户敲了一行带语法错误的 JSON（少个逗号），提交前界面无任何反馈，点「下发任务」才弹「args 不是合法的 JSON」。
- 改进：`watch([() => form.args, () => form.kwargs], debounce(300ms))` 实时 parse，出错时对应 el-form-item 挂 error 提示（即时红字 + 禁止提交）。

**A3【优先级：低】历史行「刷新」查不到事件时弹 toast**
- 位置：L97-107：
```js
} catch { ElMessage.warning('任务尚未产生事件记录') }
```
  刚下发 1 秒就点刷新，事件还没落库 → 每次点都弹一条 warning toast，连续点击刷屏。
- 改进：把状态写回行内（row.state 旁显示小字「暂无事件记录」），toast 只用于真正的网络错误。

**A4【优先级：低】.hrow / .hresult 硬编码浅色（G8 成员）**
- 位置：L291 `background: #fcfdfe`、L319 `background: #f6f8fa`。暗色主题下历史卡片是浅色块。
- 改进：`var(--fu-surface-2)` / `var(--fu-code-bg)`。

### 3.11 LoginView（登录）

**L1【优先级：中】redirect 参数未校验，存在开放重定向风险**
- 位置：L51：
```js
router.replace(route.query.redirect || { name: 'dashboard' })
```
  router 守卫生成的 redirect 是内部路径（router/index.js L76 `query: { redirect: to.fullPath }`），但这里对 query 值零校验——构造 `/#/login?redirect=//evil.com` 可能把登录成功的用户导向外部站点（经典 open redirect，内网工具同样可能被钓鱼利用）。
- 改进：
```js
const r = route.query.redirect
const safe = typeof r === 'string' && r.startsWith('/') && !r.startsWith('//')
router.replace(safe ? { path: r } : { name: 'dashboard' })
```

**L2【优先级：低】登录失败无节流/锁定反馈**
- 现状：密码错误只弹 toast（L52-55），可无限次尝试，前端无任何冷却。
- 改进：前端维护连续失败计数，3 次后按钮进入 15s 倒计时禁用（文案「失败 3 次，15 秒后可重试」）；服务端 detail 信息透传保留。

### 3.12 AppLayout / DetailOverlay（全局框架）

**LAY1【优先级：高】移动端无断点：侧边栏恒定占宽**
- 位置：`layouts/AppLayout.vue` L25 `asideWidth = collapsed ? '64px' : '216px'`；L352-357 唯一的媒体查询只隐藏 broker-url 与 badge。
- 现状：390px 手机上侧边栏（展开 216px / 收起 64px）+ 表格 min-width 让内容区几乎不可用；也没有汉堡按钮把菜单收进 drawer。
- 改进：
  1. `<900px` 断点：aside 默认隐藏，header 左侧出现汉堡按钮，点击以 el-drawer（direction=rtl, size=220px）承载同一份菜单模板；
  2. 菜单提取为子组件 `SideMenu` 供两处复用；
  3. 桌面行为完全不变（该断点以上零 diff）。
- 收益：手机/平板巡检场景可用；与 G7 的抽屉、网格断点一次做完。

**LAY2【优先级：中】详情抽屉宽度固定 + 状态不同步 URL**
- 位置：`components/DetailOverlay.vue` L10-17（size 写死 58% / 50%，无响应式）；stores/detail.js 只存 type / id。
- 现状：① 小屏 50% 宽的详情表格不可读（G7 成员）；② 排障时「把这条任务详情发给同事」只能发 task id 文本，不能发链接；刷新页面抽屉状态丢失。
- 改进：
  1. 宽度按断点：移动端 100%，桌面保持 58% / 50%；
  2. URL 同步：openTask / openWorker 时 router.replace 到带 query.open（形如 task:uuid）的当前路由，关闭时移除该 query；路由守卫或 AppLayout 挂载时解析 query.open 恢复抽屉——实现深链分享。
- 收益：移动端可读 + 详情可分享可刷新，排障协作效率显著提升。

**LAY3【优先级：低】顶栏无「最后更新时间」，channel.lastUpdate 未被展示**
- 位置：`layouts/AppLayout.vue` L102-117（channel badge 只显示模式与连接状态）；`stores/app.js` L58-63 已维护 `channel.lastUpdate`。
- 现状：数据是 2s / 5s 级实时，但断网重连、WS 卡顿期间界面不会变红（connected 仍可能为 true 而数据停更 30s），用户无从感知「数据还是新的吗」。
- 改进：badge tooltip 里加「最后更新 N 秒前」，并用 1s 定时器把超过 10s 未更新的 lastUpdate 显示为橙色「数据延迟 Ns」；这是监控台可信度的基础件。

---

## 4. 做得好的地方（保持）

审计中确认以下实现质量高，建议作为后续开发参照，不要回退：

- **主题令牌契约**：`styles/themes/_contract.css` 定义完整令牌集 + 兜底值，`vendor/element-plus.css` 用 `html[data-theme`] 高特异度把 EP 全部 `--el-*` 映射到 `--fu-*`，新增主题零组件改动——体系优秀，缺口只在图表层（G1）与个别 scoped 样式（G8）。
- **主题切换体验**：main.js 首屏防闪烁 bootstrap（L19-43）、theme.js 的远程主题 link reconcile（registry.js L81-87 修掉了「切回内置主题要刷新」的坑）、切换过渡 class（theme.js L86-92）。
- **实时通道**：ws.js 指数退避重连 + 心跳（L52-56）；app.js 轮询模式「连续 3 次失败才判断开」防抖（L141-142）、pollCursor 增量游标（L130-133）设计合理；WS / 轮询可切换且有 UI。
- **可访问性基础**：tokens.css L68-81 完整支持 `prefers-reduced-motion`；LoginView 表单校验 + Enter 提交；detail 抽屉支持 Esc 关闭（el-drawer 内置）。
- **交互细节**：危险操作普遍有二次确认（shutdown / restart / revoke / terminate / 删除主题）；TasksView 的调用链 root / parent 过滤 tag 可一键清除（L170-175）；ConfigView 的脏键 diff + 「保存修改（N）」计数是同类配置页少见的细致设计。

## 5. 实施建议（优先级路线图）

**第一批（高，建议 1 个迭代内）**
1. G1 + G8：图表与 scoped 样式全量接入主题令牌（含 data-theme 监听重渲染）——一次主题大修。
2. G2：useChart 增量 setOption + 实时图 dataZoom。
3. D1 / M1：两处定时器泄漏（5 分钟改动，立即止血）。
4. T1 / T2：任务列表按钮状态一致性 + keep-alive 定时器治理。
5. G3：错误 toast 去重（选方案 A，删视图层重复 ElMessage.error）。
6. G5：ConfigView 未保存离开保护。
7. G4：tableSize 落地（可顺手封装 FuTable）。
8. G7 / LAY1：移动端断点（侧边栏 drawer 化 + 抽屉 100% + minmax 修复）。
9. C1：配置搜索框。

**第二批（中）**
- G6 可见性暂停 + usePagePolling 统一（覆盖 T5 / WorkerDetail / Broker 的轮询）。
- D2 事件流过滤 / 暂停 / 点击跳转；M3 图表到任务列表联动（TasksView 需支持 query.taskname / state 初始化）。
- TD2 时间线阶段耗时拆解；C2 / C3 配置页两处一致性；W1 / T3 批量操作 BatchBar；TD1 clipboard 修复；LAY2 抽屉 URL 深链；S1 系统信息错误态；A1 / A2 下发页持久化 + 即时校验；L1 redirect 校验。

**第三批（低）**
- G9 右键菜单 + 快捷键；D3 / D4 / M4 / B2 / S3 等可视化与联动细节；WD2 术语统一；L2 登录节流。

---

*报告基于当前工作区源码逐行审阅生成；所有行号引用可在对应文件中复核。*
