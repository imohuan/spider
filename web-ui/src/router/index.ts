import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', name: 'dashboard', component: () => import('@/views/DashboardView.vue'), meta: { title: 'Dashboard', desc: '总览 · 实时指标和任务流水' } },
  { path: '/queue', name: 'queue', component: () => import('@/views/QueueView.vue'), meta: { title: '任务队列', desc: 'queue 表 · 状态机驱动的 URL 队列' } },
  { path: '/data', name: 'data', component: () => import('@/views/DataBrowserView.vue'), meta: { title: '数据浏览', desc: 'Parser 业务表 · 查询/导出' } },
  { path: '/proxy', name: 'proxy', component: () => import('@/views/ProxyPoolView.vue'), meta: { title: 'IP 池', desc: 'proxy_pool 表 · 代理 IP 生命周期' } },
  { path: '/captcha', name: 'captcha', component: () => import('@/views/CaptchaLogView.vue'), meta: { title: '验证码日志', desc: 'captcha_log 表 · 接码记录' } },
  { path: '/config', name: 'config', component: () => import('@/views/ConfigView.vue'), meta: { title: '配置', desc: 'config 表 · 运行时可调参数' } },
  { path: '/parsers', name: 'parsers', component: () => import('@/views/ParsersView.vue'), meta: { title: 'Parser 管理', desc: '插件注册表 · 启用/禁用/测试' } },
  { path: '/logs', name: 'logs', component: () => import('@/views/LogsView.vue'), meta: { title: '日志', desc: '完整 run.log 显示 · 实时追加' } },
]

export const router = createRouter({ history: createWebHashHistory(), routes })
