# 58-data 项目记忆

## web-ui 子项目
- 位置：`D:\Code\Git\58-data\web-ui`
- 技术栈：Vue 3.5 + Vite 8 + TS 6 + Tailwind CSS 4.3 + pnpm 10
- 组件库：ax-ui-kit（自研 Axiom UI），位于 `src/components/ui/`
- Dev server 默认端口：5175（5173/5174 被占用）
- 规则文件：`.workbuddy/rules.md`（强制 Ax* 组件）

## ax-ui-kit Skill 修复记录
- 已补全缺失的 `assets/index.ts`、`assets/types.ts`、`assets/common.ts`
- 下次 sync.js 同步时会自动覆盖到目标项目

## 58 爬虫框架
- 设计文档：`2026-06-21-58-crawler-design.md` + `docs/plans/2026-06-21-crawler-ui.md`
- 进度（2026-06-21）：全部 6 阶段 13 任务完成，394 测试全过
- 技术栈：Python 3.13 + Playwright + fontTools + ddddocr + lxml + cssselect + SQLite
- 6层架构：配置/调度/请求池/浏览器拦截/解析/持久化
- Parser 插件：ershouche_list + ershouche_detail（自动 discover + url_pattern 匹配）
- 入口：`main.py`（argparse + 组件装配 + asyncio 桥接）

## 58 爬虫 Web 管理后台（已实现）
- 位置：`web/` 目录
- Flask + Flask-SocketIO + **threading**（已弃用 eventlet）+ flask-cors
- 9 个蓝图 29 个 API 路由：dashboard/queue/data/proxy/captcha/config/parsers/logs/crawler
- WebSocket 事件：log（日志推送）/ task_update（状态变更）/ metrics_update（指标更新）
- 打包：`build.py`（PyInstaller --onedir，输出 dist/58-crawler/ 含 EXE + Chromium）
- 启动：`python main.py --serve`（后台 daemon 线程，不阻塞爬虫）

## 58 爬虫双模式抓取设计（2026-06-21）
- 设计文档：`docs/plans/2026-06-21-dual-mode-fetch-design.md`
- 背景：Playwright 被 58 反爬检测（stealth/系统Chrome/CDP全失败），纯HTTP不触发验证码
- 方案：每任务级 fetch_mode（browser/http），三层参数合并（config < Parser < task.request_config）
- queue 表加 fetch_mode + request_config(JSON) 两列
- HTTP 模式用 httpx.AsyncClient，支持 GET/POST/PUT、headers/cookies/params/body/form_data/json_body
- Parser 零改动（_get_html 已兼容字符串），新增 requires_browser 标记
- 状态：已实现（407 测试全过）

## 58 爬虫 UI 设计结论（2026-06-21）
- 前端无法直读 SQLite，必须有后端 API 层
- 方案：Flask + Flask-SocketIO 内嵌爬虫主进程（已落地）
- 前端复用 ax-ui-kit，页面：Dashboard / Queue / DataBrowser / ProxyPool / CaptchaLog / Config / Parsers / Logs
- 关键并发问题：SQLite WAL + 连接隔离 + 单写线程
- WebSocket 推日志/任务状态，HTTP 轮询指标（5s/10s）
- 权限模型：绑定 127.0.0.1，可选 admin 密码，危险操作二次确认
- 风险：Playwright sync API 与 Flask 同进程事件循环冲突，爬虫用 async Playwright + asyncio.run 桥接

## 工作流系统 (Workflow System) — 2026-06-23
- 热插拔自定义脚本执行。`workflows/` 目录放 `.py` 暴露 `async def execute(params) -> dict`
- `core/workflow_registry.py`：自动发现（importlib）+ `enqueue_workflow(name, params)` 便捷函数
- `core/workflow_scheduler.py`：后台线程轮询执行，异步支持
- `web/api/workflows.py`：Flask 蓝图 `/api/workflows`（4 路由：GET /, POST /run, GET /tasks, GET /tasks/<id>）
- WebSocket 事件 `workflow_task_update`：任务状态变更推送
- `main.py`：组件装配，`--serve` 时自动启动调度器
- 数据库 `workflow_queue` 表：id / workflow_name / params(JSON) / status / result(JSON) / error / timestamps
- 状态机：pending → running → done/failed。独立于爬虫 queue
- 设计文档：`docs/plans/2026-06-23-workflow-system-design.md`
- 实施计划：`docs/plans/2026-06-23-workflow-system-plan.md`
- 457/457 测试全过（含 15 个新测试），零原有回归

## 修复记录 — 2026-06-24
- `web-ui/src/views/DataBrowserView.vue`：修复 `<Transition>` 动画警告 — 组件 template 有多个根节点（div + AxDialog），Vue 3 编译为 Fragment。`<Transition name="fade" mode="out-in">`（DefaultLayout.vue:15）要求单元素根节点。**修复方式**：将全部内容包裹在单个根 `<div class="space-y-ax-md relative">` 内。QueueView 和 CookiePresetsView 也有 AxDialog 但已在根 div 内部，无需改动。
