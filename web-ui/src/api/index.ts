import { api, http } from './http'

export const dashboardApi = {
  getMetrics: () => api.get('/dashboard/metrics'),
  getProgress: (hours = 24) => api.get('/dashboard/progress', { hours }),
  getRecent: (limit = 20) => api.get('/dashboard/recent', { limit }),
}

export const crawlerApi = {
  start: () => api.post('/crawler/start'),
  pause: () => api.post('/crawler/pause'),
  stop: () => api.post('/crawler/stop'),
  status: () => api.get('/crawler/status'),
}

export const queueApi = {
  stats: () => api.get('/queue/stats'),
  list: (p: { page?: number; size?: number; status?: string; parser?: string; search?: string }) => api.get('/queue', p),
  retry: (id: number) => api.post(`/queue/${id}/retry`),
  retryBlocked: () => api.post('/queue/retry-blocked'),
  create: (payload: { url: string; parser_name?: string; fetch_mode?: string; request_config?: Record<string, any> }) => api.post('/queue', payload),
}

export const dataApi = {
  tables: () => api.get('/data/tables'),
  query: (table: string, p: { page?: number; size?: number }) => api.get(`/data/${table}`, p),
  exportUrl: (table: string) => `/api/data/${table}/export?format=csv`,
}

export const proxyApi = {
  stats: () => api.get('/proxy/stats'),
  list: (p: { page?: number; size?: number; status?: string }) => api.get('/proxy', p),
  fetch: (num = 10) => api.post(`/proxy/fetch?num=${num}`),
  healthCheck: () => api.post('/proxy/health-check'),
  kill: (id: number) => api.del(`/proxy/${id}`),
}

export const captchaApi = {
  stats: () => api.get('/captcha/stats'),
  list: (p: { page?: number; size?: number }) => api.get('/captcha', p),
}

export const configApi = {
  getAll: () => api.get('/config'),
  update: (data: Record<string, string>) => api.put('/config', data),
  reset: () => api.post('/config/reset'),
  /** 测试 URL — 走完整 Parser pipeline（browser 模式可能较慢，60s 超时） */
  getUrl: (payload: {
    url: string
    parser?: string       // 可选, 从 Parser 卡片进入时携带
    show_window?: boolean // 可选, 显示浏览器窗口（调试用）
    keep_open_seconds?: number // 可选, 保持浏览器打开 N 秒
  }) => http.post('/config/get-url', payload, { timeout: 60000 }),
  /** 列出当前保持打开的 debug 浏览器会话 */
  getDebugPages: () => api.get('/config/debug-pages'),
  /** 手动关闭 debug 浏览器页面 */
  closeDebugPage: (sessionId: string) => api.post('/config/close-debug-page', { session_id: sessionId }),
  /** 测试 AI 服务连接 */
  testAi: () => api.post('/config/test-ai'),
  /** AI 生成 HTML 预览模板 */
  generateTemplate: (payload: { table: string; prompt: string }) =>
    http.post('/config/generate-template', payload, { timeout: 120000 }),
  /** 模板 CRUD */
  getTemplates: (table: string) => api.get('/config/templates', { table }),
  saveTemplate: (payload: { table_name: string; template_html: string; template_name?: string; id?: number }) =>
    api.post('/config/templates', payload),
  deleteTemplate: (id: number) => api.del(`/config/templates/${id}`),
}

export const logsApi = {
  getAll: () => api.get('/logs', { size: -1 }),
}

export const parsersApi = {
  list: () => api.get('/parsers'),
  rescan: () => api.post('/parsers/rescan'),
  test: (name: string, url: string) => api.post(`/parsers/${name}/test`, { url }),
}

export const cookiePresetsApi = {
  list: () => api.get('/cookie-presets'),
  get: (id: number) => api.get(`/cookie-presets/${id}`),
  save: (payload: { name: string; domain: string; cookies_json: string; id?: number }) =>
    api.post('/cookie-presets', payload),
  delete: (id: number) => api.del(`/cookie-presets/${id}`),
  toggle: (id: number) => api.post(`/cookie-presets/${id}/toggle`),
}
